"""Focused deployment commands; nothing programs a board automatically."""
import argparse
from collections import Counter
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from zipfile import BadZipFile, ZipFile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fpga.catalog import registry, select, SMALL
from fpga.deploy import checked_digest, export_bundle
from fpga.provenance import verify_bambu
from fpga.prepare import ABI, digest, layout, make_abi_header, prepare
from fpga.hostgen import write as hostgen
from tools.execution import load_board_profiles


def write(path,data):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    Path(path).write_text(json.dumps(data,indent=2)+'\n')


def capture(argv):
    try:
        p=subprocess.run(argv,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=20)
        return {'exit_code':p.returncode,'output':p.stdout[-16000:]}
    except (OSError,subprocess.TimeoutExpired) as e: return {'exit_code':None,'output':str(e)}


def tool(name):
    return os.environ.get('FPGA_'+name.upper().replace('+','P'),shutil.which(name) or name)


def board(name):
    boards=load_board_profiles()
    if name not in boards: raise ValueError('Not in existing board registry: '+name)
    extra=json.loads(Path(os.environ.get('FPGA_PROFILE',ROOT/'fpga/profiles/boards.json')).read_text())
    if name not in extra: raise ValueError(name+': add deployment metadata; a board entry alone is insufficient')
    profile=extra[name]
    required={'vendor','part','tools','memory_kind','resources','platform_env','model_ip'}
    if required-profile.keys(): raise ValueError(name+': missing deployment fields '+str(required-profile.keys()))
    if profile['vendor']!='amd': raise ValueError(name+': AMD XO/Vitis backend is technically unsupported for vendor '+profile['vendor']+'; add a vendor backend and external-memory model')
    return boards[name],profile


def receipt(name,profile,period):
    platform_path=os.environ.get(profile['platform_env'])
    if not platform_path or not Path(platform_path).is_file():
        raise ValueError('Set '+profile['platform_env']+' to a verified development .xpfm; candidate is '+str(profile.get('candidate_platform')))
    receipt_path=os.environ.get('FPGA_PLATFORM_RECEIPT')
    if not receipt_path: raise ValueError('Set FPGA_PLATFORM_RECEIPT using profiles/receipt.example.json after inspecting platforminfo, shell and XRT compatibility')
    r=json.loads(Path(receipt_path).read_text())
    for k in ('board','part','tool_release','platform_sha256','shell_vbnv','xrt_version','kernel_mhz','interface_clocks_mhz','memory_clocks_mhz','resources','evidence'):
        if k not in r or r[k] in ('',None,[],{}) or 'REPLACE' in str(r[k]): raise ValueError('Unverified receipt field '+k)
    if r['board']!=name or r['part']!=profile['part'] or r['tool_release']!='2024.2': raise ValueError('Receipt board/part/tool mismatch')
    if r['platform_sha256']!=digest(platform_path): raise ValueError('Platform fingerprint changed')
    if not math.isclose(r['kernel_mhz'],1000/period,rel_tol=0.0001): raise ValueError('Receipt clock differs from selected recipe clock')
    for resource in profile['resources']:
        if not resource.startswith(profile['memory_kind']+'['): raise ValueError('External memory kind mismatch')
        if r['resources'].get(resource,{}).get('capacity_bytes',0)<65536: raise ValueError('Missing verified external resource/capacity: '+resource)
    return Path(platform_path).resolve(),r


def preflight(args):
    b,p=board(args.board)
    identities={name:{'path':shutil.which(tool(name)),'version':capture([tool(name),flag])} for name,flag in
                [('vivado','-version'),('v++','--version'),('bambu','--version'),('vsim','-version')]}
    errors=[]
    for name in ('vivado','v++'):
        if identities[name]['version']['exit_code'] or '2024.2' not in identities[name]['version']['output']: errors.append(name+': usable release 2024.2 not verified')
    if not identities['bambu']['path']: errors.append('Bambu unavailable; no Vitis HLS replacement permitted')
    try: provenance=verify_bambu(tool('bambu'))
    except (ValueError,OSError,subprocess.SubprocessError) as e: provenance=None;errors.append(str(e))
    xrt=Path(os.environ.get('XILINX_XRT','/opt/xilinx/xrt'))
    headers={h:(xrt/'include'/h).is_file() for h in ('xrt/xrt_device.h','experimental/xrt_ip.h','experimental/xrt_xclbin.h')}
    if not all(headers.values()): errors.append('Required XRT headers missing under '+str(xrt))
    try: plat,r=receipt(args.board,p,float(args.period)); verified={'path':str(plat),'receipt':r}
    except (ValueError,OSError) as e: errors.append(str(e));verified=None
    data={'host':platform.platform(),'board':args.board,'board_registry':b,'deployment_profile':p,'tools':identities,
          'bambu_provenance':provenance,'xrt_headers':headers,'platform':verified,'licenses':'not checked out; version/header presence does not prove usable license',
          'errors':errors,'capability_status':'blocked' if errors else 'preflight passed; package/link license checkout still required'}
    write(args.output,data);print(json.dumps(data,indent=2));return bool(errors)


def run(argv, cwd, log):
    command = shlex.join(list(map(str, argv)))
    print('$ ' + command, flush=True)
    started = time.monotonic()
    with Path(log).open('w') as handle:
        handle.write('$ ' + command + '\n')
        handle.flush()
        try:
            result = subprocess.run(list(map(str, argv)), cwd=cwd, stdout=handle,
                                    stderr=subprocess.STDOUT)
        finally:
            seconds = round(time.monotonic() - started, 3)
            handle.write(f'\nWall time: {seconds:.3f} s\n')
    print(f'Wall time: {seconds:.3f} s ({log})', flush=True)
    if result.returncode:
        raise ValueError(f'Command exited {result.returncode}; see {log}')
    return seconds


def generate(case,args):
    provenance=verify_bambu(tool('bambu'))
    b,p=board(args.board);period=float(os.environ.get('CLOCK_PERIOD_NS') or case.get('clock_period_ns',b['default_clock_ns']))
    if not math.isfinite(period) or period<=0:raise ValueError('CLOCK_PERIOD_NS must be positive and finite')
    out=Path(args.output).resolve()/case['name'];out.mkdir(parents=True,exist_ok=False)
    snapshot=out/'snapshot';snapshot.mkdir()
    if case['suite']=='calibration':
        source=ROOT/'fpga/calibration/memory_probe.c'
        shutil.copyfile(source,snapshot/source.name)
        source_hashes = {case['members'][0]: digest(snapshot/source.name)}
        flags=[f.replace('@/fpga/calibration/memory_probe.c',str(snapshot/source.name)) for f in case['flags']]
        argv=[tool('bambu'),*flags,f"--device-name={b['bambu_device']}",f'--clock-period={period}',f'--output-directory={out}/hls']
    else:
        # This focused subset has explicit source members. Hardware staging
        # deliberately needs no Ramulator install, YAML or MDPI model build.
        if case.get('archive') or case.get('trees'):raise ValueError('Hardware staging for archive/tree recipes is not implemented')
        inputs=snapshot/'inputs'
        for member in case['members']:
            target=inputs/member;target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(ROOT/member,target)
        source_hashes = {member: digest(inputs/member) for member in case['members']}
        flags=[f.replace('@/',str(inputs)+'/') for f in case['flags']]
        flags=[f for f in flags if f not in ('--simulate','--enable-ramulator') and not f.startswith(('--simulator=','--generate-tb=','--tb-','--output-directory='))]
        argv=[tool('bambu'),f"--device-name={b['bambu_device']}",f'--clock-period={period}',*flags,f'--output-directory={out}/hls']
    identity=capture([tool('bambu'),'--version'])
    if identity['exit_code']: raise ValueError('Bambu version check failed; see '+str(out))
    write(out/'generation.json',{'case':case['name'],'board':args.board,'period_ns':period,'argv':argv,'compiler':'I386_CLANG13',
                               'bambu':identity,'provenance':provenance,'source_sha256':source_hashes,'git_base':capture(['git','-C',str(ROOT),'rev-parse','HEAD'])})
    seconds = run(argv, out, out / 'bambu.log')
    top=layout(case)['top']
    candidates=list((out/'hls').rglob(top+'.v'))
    if len(candidates)!=1: raise ValueError('Expected one generated '+top+'.v; inspect '+str(out/'hls'))
    rtl_dir=candidates[0].parent
    gen=json.loads((out/'generation.json').read_text())
    gen['rtl_sha256']={name:digest(rtl_dir/name) for name in (top+'.v','panda_libtech.v')}
    gen['rtl_dir']=str(rtl_dir)
    gen['wall_seconds'] = seconds
    write(out/'generation.json',gen)
    print('Generated; prepare --rtl-dir '+str(rtl_dir)+' --generation '+str(out/'generation.json'))


def registers(info,out):
    specs=[(name,offset,64 if name in ('CORE_CYCLES','DRAIN_CYCLES') else 32) for name,offset in ABI['registers'].items() if name!='BASE0']
    specs += [('base'+str(i),32+8*i,64) for i in range(len(info['axi_ports']))]
    lines=[]
    for name,offset,size in specs:
        lines += [f'set reg [ipx::add_register {name} $ab]',f'set_property address_offset {offset} $reg',f'set_property size {size} $reg']
        if name.startswith('base'):
            ports=[info['axi_ports'][int(name[4:])]]
            lines += ['ipx::add_register_parameter ASSOCIATED_BUSIF $reg', 'set_property value {'+':'.join(ports)+'} [ipx::get_register_parameters ASSOCIATED_BUSIF -of_objects $reg]']
    (out/'registers.tcl').write_text('\n'.join(lines)+'\n')


def native(case,args):
    out=Path(args.output).resolve()/case['name'];out.mkdir(parents=True,exist_ok=True)
    info=layout(case);hostgen(case,info,out)
    src=out/'native.cpp';src.write_text('''#include "case.hpp"
#include <iostream>
int main(){for(unsigned rep=0;rep<2;++rep){
 for(unsigned n : std::vector<unsigned>'''+ ('{0,1,63,64,65,127,128,129,512,513}' if case['suite']=='calibration' else '{case_n}')+''') {
 auto initial=case_input(n,rep),expected=case_expected(initial,n);
 auto packed=pack(initial,case_banks);if(unpack(packed,initial.size())!=initial)return 1;
 auto got=pack(expected,case_banks);if(unpack(got,expected.size())!=expected)return 2;
 }}std::cout<<case_name<<" native/packing PASS\\n";}
''')
    flags=json.loads((out/'host-flags.json').read_text())
    argv=[os.environ.get('CXX','c++'),'-std=c++17','-O2','-Wno-unknown-pragmas','-I'+str(ROOT/'fpga/host'),*flags,str(src),'-o',str(out/'native')]
    run(argv,out,out/'compile.log');run([out/'native'],out,out/'native.log')
    write(out/'native-result.json',{'case':case['name'],'mode':'native_reference','functional_status':'pass','rtl_simulated':False,
                                   'sources':{m:digest(ROOT/m) for m in case['members']},'compiler':capture([argv[0],'--version'])})
    print((out/'native.log').read_text())


def kernel_metadata(xo, expected_ports):
    with ZipFile(xo) as archive:
        names = [name for name in archive.namelist() if Path(name).name == 'kernel.xml']
        if len(names) != 1:
            raise ValueError('XO must contain exactly one kernel.xml')
        root = ET.fromstring(archive.read(names[0]))
        kernel = root if root.tag == 'kernel' else root.find('kernel')
    if kernel is None or kernel.get('name') != 'fpga_kernel':
        raise ValueError('XO must describe the fpga_kernel RTL kernel')
    if kernel.get('hwControlProtocol') != 'user_managed':
        raise ValueError('XO requires user_managed control')
    ports = {item.get('name'): item.get('mode') for item in kernel.findall('ports/port')}
    masters = {name for name, mode in ports.items() if mode == 'master'}
    if ports.get('S_AXI_CONTROL') != 'slave' or masters != set(expected_ports):
        raise ValueError('XO AXI interfaces differ from the prepared kernel')
    if any(arg.get('port') not in ports for arg in kernel.findall('args/arg')):
        raise ValueError('XO kernel.xml contains an argument with an unknown AXI port')


def memory_mapping(info, resources, overrides):
    ports = info['axi_ports']
    groups = info['base_register_banks']
    banks = {group: resources[group] for group in set(groups)}
    selected = {}
    for override in overrides:
        port, _, resource = override.partition('=')
        if port not in ports or resource not in resources:
            raise ValueError(f'Expected a prepared port and verified resource: {override}')
        group = groups[ports.index(port)]
        if group in selected and selected[group] != resource:
            raise ValueError('Aliased AXI ports must use the same memory resource')
        selected[group] = resource
    banks.update(selected)
    if len(set(banks.values())) != len(banks):
        raise ValueError('Separate memory banks require distinct resources')
    return {port: banks[group] for port, group in zip(ports, groups)}


def package(prepared, info, part, period):
    seconds = run([tool('vivado'), '-mode', 'batch', '-source',
                   ROOT / 'fpga/tcl/package.tcl', '-tclargs', prepared, part, period],
                  prepared, prepared / 'package.log')
    xo = prepared / 'fpga_kernel.xo'
    kernel_metadata(xo, info['axi_ports'])
    write(prepared / 'package.json', {
        'manifest_sha256': digest(prepared / 'manifest.json'),
        'xo_sha256': digest(xo),
        'wall_seconds': seconds,
    })


def link(prepared, dest, info, args, platform_path, platform_receipt, resources):
    xo = prepared / 'fpga_kernel.xo'
    source_hash = digest(prepared / 'manifest.json')
    abi_path = prepared / 'abi.hpp'
    abi_hash = checked_digest(abi_path, info['abi_sha256']) if 'abi_sha256' in info else digest(abi_path)
    xo_hash = digest(xo)
    package_path = prepared / 'package.json'
    package_receipt = json.loads(package_path.read_text()) if package_path.is_file() else {}
    if package_receipt and (package_receipt['manifest_sha256'] != source_hash or
                            package_receipt['xo_sha256'] != xo_hash):
        raise ValueError('Packaged XO differs from its receipt; run package again')

    mapping = memory_mapping(info, resources, args.memory)
    dest.mkdir(parents=True, exist_ok=False)
    linked_xo = dest / xo.name
    shutil.copyfile(xo, linked_xo)
    checked_digest(linked_xo, xo_hash)
    kernel_metadata(linked_xo, info['axi_ports'])
    cfg = dest / 'connectivity.cfg'
    cfg.write_text('[connectivity]\nnk=fpga_kernel:1:fpga_kernel_1\n' +
                   ''.join(f'sp=fpga_kernel_1.{port}:{resource}\n'
                           for port, resource in mapping.items()))
    xclbin = dest / 'fpga_kernel.xclbin'
    seconds = run([tool('v++'), '--link', '--target', args.target, '--platform', platform_path,
                   '--config', cfg, '--kernel_frequency', str(1000 / info['generation']['period_ns']),
                   '--save-temps', '--temp_dir', dest / 'temp', '--log_dir', dest / 'logs',
                   '--report_dir', dest / 'reports', '-o', xclbin, linked_xo],
                  dest, dest / 'link.log')
    if not xclbin.is_file() or not xclbin.stat().st_size:
        raise ValueError('Link returned without a nonempty xclbin')
    times = {'generate': info['generation'].get('wall_seconds'),
             'prepare': info.get('wall_seconds'), 'package': package_receipt.get('wall_seconds'),
             'link': seconds}
    if args.target == 'hw_emu':
        times['emconfig'] = run(['emconfigutil', '--platform', platform_path, '--od', dest],
                                 dest, dest / 'emconfig.log')
    write(dest / 'build.json', {
        'target': args.target, 'platform': platform_receipt, 'memory': mapping,
        'manifest_sha256': source_hash, 'abi_sha256': abi_hash,
        'xo_sha256': xo_hash, 'xclbin_sha256': digest(xclbin),
        'wall_seconds': times,
        'implementation_timing': 'Inspect routed timing and DRC reports before deployment.',
    })


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('command',choices=['inventory','preflight','generate','prepare','package','link','bundle','host','native'])
    ap.add_argument('--board',default='xcu55c');ap.add_argument('--tests',action='append',default=[])
    ap.add_argument('--all-supported',action='store_true');ap.add_argument('--output')
    ap.add_argument('--rtl-dir');ap.add_argument('--prepared');ap.add_argument('--generation')
    ap.add_argument('--fix-adapter-log2',action='store_true');ap.add_argument('--period',default='10')
    ap.add_argument('--target',choices=['hw','hw_emu'],default='hw_emu')
    ap.add_argument('--link-dir', type=Path, help='New link directory, or completed directory for bundle')
    ap.add_argument('--memory', action='append', default=[], metavar='PORT=RESOURCE',
                    help='Remap a prepared port during link; repeat for additional groups')
    ap.add_argument('--bundle', type=Path, metavar='ARCHIVE',
                    help='Export a .tar.gz after a successful hardware link')
    args=ap.parse_args()
    if args.bundle and (args.command != 'link' or args.target != 'hw'):
        ap.error('--bundle requires link --target hw')
    if args.bundle:
        if args.bundle.exists() or args.bundle.is_symlink():
            ap.error(f'Bundle already exists: {args.bundle}')
        if not shutil.which(tool('xclbinutil')):
            ap.error('Set FPGA_XCLBINUTIL or add xclbinutil to PATH for export')
    if args.memory and args.command != 'link':
        ap.error('--memory is only valid for link')
    if args.link_dir and args.command not in ('link', 'bundle'):
        ap.error('--link-dir is only valid for link or bundle')
    if args.command != 'bundle':
        args.output=args.output or (".fpga/"+args.command+".json" if args.command in ("inventory","preflight") else ".fpga/build")
    if args.command=='inventory':
        matrix={'boards':load_board_profiles(),'cases':[{ 'name':c['name'],'suite':c['suite'],
                  'implementation':'adapter implemented, generated interface verification required' if c['name'] in SMALL else 'not yet implemented',
                  'functional_rtl':'not run','bitstream':'not built','vendor_model':'not run','board':'not tested'} for c in registry().values()]}
        write(args.output,matrix);print(json.dumps(matrix,indent=2));return 0
    if args.command=='preflight': return preflight(args)
    cases=select(args.tests,args.all_supported)
    if args.command in ('generate','native'):
        for case in cases: (generate if args.command=='generate' else native)(case,args)
        return 0
    if args.command=='prepare':
        started = time.monotonic()
        if len(cases)!=1 or not args.rtl_dir: raise ValueError('prepare requires one exact --tests case and --rtl-dir containing TOP.v + panda_libtech.v')
        out=Path(args.output).resolve();info=prepare(cases[0],args.rtl_dir,out,args.fix_adapter_log2)
        if args.generation:
            gen=json.loads(Path(args.generation).read_text())
            if gen['case']!=cases[0]['name'] or gen['board']!=args.board: raise ValueError('Generation case/board mismatch')
            if gen.get('rtl_sha256')!=info['original_sha256']: raise ValueError('RTL does not match generation fingerprints')
            if info['frontend']!=gen['compiler']: raise ValueError('Generated frontend differs from generation receipt')
            info['generation']=gen
        else: info['reference_only']=True
        registers(info,out)
        info['host_sha256'] = hostgen(cases[0], info, out)
        info['abi_sha256'] = digest(out / 'abi.hpp')
        info['wall_seconds'] = round(time.monotonic() - started, 3)
        write(out/'manifest.json',info)
        print('Prepared '+str(out));return 0
    if not args.prepared: raise ValueError('--prepared required')
    out = Path(args.prepared).resolve()
    if args.command == 'bundle':
        dest = args.link_dir.resolve() if args.link_dir else out / 'hw'
        archive = Path(args.output).resolve() if args.output else dest / 'hacc-bundle.tar.gz'
        export_bundle(out, dest, archive, tool('xclbinutil'))
        return 0
    info = json.loads((out / 'manifest.json').read_text())
    if args.command == 'host':
        run([sys.executable, ROOT / 'fpga/host/build.py', '--prepared', out],
            out, out / 'host-build.log')
        return 0
    if info.get('reference_only'):
        raise ValueError('Reference RTL has no board-correct generation receipt; regenerate actual selected Bambu DUT first')
    gen = info['generation']
    _, profile = board(gen['board'])
    period = gen['period_ns']
    platform_path, platform_receipt = receipt(gen['board'], profile, period)
    with (out / '.build.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError(f'Package or link already active in {out}') from error
        for name, expected in info['rtl_sha256'].items():
            checked_digest(out / 'rtl' / name, expected)
        if args.command == 'package':
            package(out, info, profile['part'], period)
        else:
            dest = args.link_dir.resolve() if args.link_dir else out / args.target
            link(out, dest, info, args, platform_path, platform_receipt, profile['resources'])
            if args.bundle:
                export_bundle(out, dest, args.bundle.resolve(), tool('xclbinutil'))
    return 0

if __name__=='__main__':
    try: sys.exit(main())
    except (ValueError,OSError,KeyError,subprocess.SubprocessError,BadZipFile,ET.ParseError) as e:
        print('ERROR: '+str(e),file=sys.stderr);sys.exit(2)
