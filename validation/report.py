"""Collect fingerprints/traffic and compare only explicitly aligned measurements."""
import argparse
from collections import defaultdict
import hashlib
import itertools
import json
from pathlib import Path
import statistics
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from fpga.prepare import digest
from fpga.run import write
from validation.axi_monitor import analyze

MODES=('bambu_ramulator','functional_axi_ram','hw_emu','vendor_memory_reference','physical_board')
ALIGN=('case','n','source_fingerprint','rtl_fingerprint','input_fingerprint','kernel_mhz','measurement','observation_boundary')


def canonical(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def eligible(left,right):
    reasons=[]
    if any(x.get('functional_status')!='pass' for x in (left,right)):reasons.append('functional status is not pass')
    for key in ALIGN:
        if left.get(key) is None or right.get(key) is None or left.get(key)!=right.get(key): reasons.append('unaligned/missing '+key)
    for x in (left,right):
        if not x.get('core_cycles') or x['core_cycles']<0:reasons.append('missing/invalid cycles')
        if x['mode'] in ('functional_axi_ram','hw_emu'):reasons.append(x['mode']+' is not a detailed performance reference')
        if x['mode']=='vendor_memory_reference' and not x.get('model',{}).get('fidelity_verified'):reasons.append('vendor timing fidelity not verified')
        if x.get('alignment_status')!='verified':reasons.append('topology/timings/queues/CDC alignment not verified')
    return sorted(set(reasons))


def compare(records):
    for r in records:
        if r['mode'] not in MODES:raise ValueError('Unknown mode '+r['mode'])
    groups=defaultdict(list)
    for r in records:groups[(r['case'],r.get('n'))].append(r)
    comparisons=[]
    for key,items in groups.items():
        for a,b in itertools.combinations(items,2):
            if a['mode']==b['mode']:continue
            reasons=eligible(a,b)
            pair={'case':key[0],'n':key[1],'left':a['mode'],'right':b['mode'],'status':'not comparable' if reasons else 'aligned','reasons':reasons}
            if not reasons:pair.update(cycle_ratio_left_over_right=a['core_cycles']/b['core_cycles'],cycle_difference_left_minus_right=a['core_cycles']-b['core_cycles'])
            comparisons.append(pair)
    return comparisons


def collect(args):
    info=json.loads(Path(args.manifest).read_text());model=json.loads(Path(args.model).read_text()) if args.model else {}
    result=[]
    metrics={Path(p).name:analyze(p) for p in args.trace}
    for line in Path(args.results).read_text().splitlines():
        if not line.strip():continue
        raw=json.loads(line)
        if raw.get('case')!=info['case']:raise ValueError('Result/manifest case mismatch')
        actual=raw.get('mode')
        if actual and actual!=args.mode:raise ValueError('Do not relabel results: '+actual+' != '+args.mode)
        input_file=raw.get('input_file')
        ip=(Path(args.results).resolve().parent/input_file) if input_file else None
        result.append(dict(raw,mode=args.mode,source_fingerprint=canonical(info['generation']['source_sha256']) if info.get('generation',{}).get('source_sha256') else None,
                           rtl_fingerprint=canonical(info['rtl_sha256']),input_fingerprint=digest(ip) if ip and ip.is_file() else None,
                           kernel_mhz=1000/info['generation']['period_ns'] if info.get('generation') else None,
                           measurement=info['abi']['counter_convention'],observation_boundary='wrapper/platform AXI',
                           alignment_status='unverified',model=model,traffic=metrics,
                           traffic_scope='whole trace; not assigned to individual repetition without a measurement-window trace',
                           manifest_sha256=digest(args.manifest),configuration_fingerprint=digest(args.model) if args.model else None,
                           toolchain=info.get('generation',{}).get('provenance'),limitations=['No cross-model alignment inferred automatically','Short calibration runs cannot establish refresh/steady-state behavior']))
    write(args.output,result);print('Collected '+str(len(result))+' records; alignment remains unverified until documented.')


def report(args):
    records=[]
    for path in args.records:
        data=json.loads(Path(path).read_text())
        records.extend(data if isinstance(data,list) else [data])
    comparisons=compare(records);out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    write(out/'results.json',{'records':records,'comparisons':comparisons})
    lines=['# Experimental memory comparison','',
           'Only observed results are included. No vendor/board result is synthesized from a script or native test.',
           'Accelerator cycles exclude initialization, register setup and host DMA. Core and AXI-drained completion are separate.',
           '', '| Case | Mode | n | Functional | Core cycles | Drained cycles |', '|---|---|---:|---|---:|---:|']
    for r in records: lines += [f"| {r['case']} | {r['mode']} | {r.get('n','unknown')} | {r.get('functional_status','unknown')} | {r.get('core_cycles','not measured')} | {r.get('drain_cycles','not measured')} |"]
    lines += ['', '## Comparison eligibility','']
    if not comparisons:lines += ['No cross-mode measurement pairs are available.']
    for p in comparisons:
        lines += [f"* {p['case']} n={p['n']}: {p['left']} / {p['right']}: {p['status']}. "+('; '.join(p['reasons']) if p['reasons'] else f"cycle ratio {p['cycle_ratio_left_over_right']:.6g}, signed difference {p['cycle_difference_left_minus_right']}")]
    lines += ['', 'Single/banked speedups are not computed without a documented topology and common-input pairing. No latency is subtracted or tuned to force agreement.',
              'Native functional checks and unavailable vendor/hardware measurements must remain separate in the capability matrix.',
              'All raw clocks, model identities, configuration hashes, traffic metrics, repetitions and limitations are retained in results.json.','']
    (out/'comparison.md').write_text('\n'.join(lines));print(out/'comparison.md')


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    c=sub.add_parser('collect');c.add_argument('--manifest',required=True);c.add_argument('--results',required=True);c.add_argument('--mode',choices=MODES,required=True)
    c.add_argument('--model');c.add_argument('--trace',action='append',default=[]);c.add_argument('--output',required=True)
    r=sub.add_parser('report');r.add_argument('--records',nargs='+',required=True);r.add_argument('--output',required=True)
    a=p.parse_args();(collect if a.command=='collect' else report)(a)

if __name__=='__main__':
    try:main()
    except (OSError,ValueError,KeyError) as e:print('ERROR: '+str(e),file=sys.stderr);sys.exit(2)
