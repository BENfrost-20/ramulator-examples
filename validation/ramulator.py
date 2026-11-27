"""Run existing small recipes with the pinned Ferrandi Bambu/Ramulator integration.
Experimental results stay outside golden approval. No backend fallback.
"""
import argparse
import json
import os
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from fpga.catalog import select
from fpga.prepare import digest,layout
from fpga.provenance import verify_bambu
from fpga.run import board,tool,write
from tools.execution import stage_case,launch,measure
from tools.ramulator import installed_library, require_headers


def ramulator_install():
    prefix=Path(os.environ.get('RAMULATOR2_DIR','/missing'))
    receipt=os.environ.get('FPGA_RAMULATOR_RECEIPT')
    if not receipt:raise ValueError('Set FPGA_RAMULATOR_RECEIPT linking the installed ferrandi/ramulator2 library hash to the pinned build; no Jesun fallback')
    r=json.loads(Path(receipt).read_text());selected=json.loads((ROOT/'fpga/toolchain.json').read_text())['ramulator2']
    if r.get('repository')!=selected['repository'] or r.get('revision')!=selected['revision']:raise ValueError('Ramulator receipt does not identify the selected Ferrandi dependency')
    require_headers(prefix)
    library = installed_library(prefix, os.environ.get('RAMULATOR2_LIBDIR')).absolute()
    if digest(library) != r.get('library_sha256') or not r.get('build_evidence'):
        raise ValueError('Ramulator binary/source evidence missing or library changed')
    return dict(r, library=str(library), version=selected['version'])


def execute(case,args,provenance,dependency):
    b,_=board(args.board);out=Path(args.output).resolve()/case['name'];out.mkdir(parents=True,exist_ok=False)
    snapshot=out/'snapshot';snapshot.mkdir();case=dict(case,flags=list(case['flags']))
    if case['suite']=='calibration':
        n=args.n;inputs=list(7*i+3 for i in range(max(1,n)))
        xml=ET.Element('function');ET.SubElement(xml,'testbench',data='{'+','.join(map(str,inputs))+'}',n=str(n))
        ET.ElementTree(xml).write(out/'input.xml',encoding='utf-8',xml_declaration=True)
        # Preserve the C kernel; rename only its unused standalone harness.
        wrapper=out/'probe_kernel.c'
        wrapper.write_text('#define main calibration_standalone_main\n#include "'+str(ROOT/'fpga/calibration/memory_probe.c')+'"\n#undef main\n')
        case['flags']=[f for f in case['flags'] if f!='@/fpga/calibration/memory_probe.c']
        case['flags'] += [str(wrapper),'--generate-tb='+str(out/'input.xml'),'--tb-param-size=data:'+str(4*max(1,n))]
        case['limit']=1000000
        # Raw little-endian input bytes match host and functional fixture inputs.
        (out/'input-0.bin').write_bytes(b''.join(x.to_bytes(4,'little') for x in inputs[:n]))
    elif args.n!=513:raise ValueError('--n is a calibration parameter; fixed suite dimensions cannot be changed')
    for flag in ('--simulate','--simulator=VERILATOR','--enable-ramulator'):
        if flag not in case['flags']:case['flags'].append(flag)
    argv,yaml=stage_case(case,snapshot,args.config,tool('bambu'),b)
    # No channel override: modeled channels and HLS banks are distinct.
    env=dict(os.environ,RAMULATOR2_CONFIG=str(yaml),RAMULATOR_OVERRIDE_CHANNELS='0',
             RAMULATOR2_DIR=str(Path(os.environ['RAMULATOR2_DIR']).resolve()),
             RAMULATOR2_LIBDIR=str(Path(dependency['library']).parent))
    for name in ('BAMBU_IPC_SIM_CMD','OUT_LVL'):env.pop(name,None)
    log=out/'cosimulation.log';code=launch(argv,out,log,env,args.timeout)
    with log.open() as stream:reads,writes,completed,ticks,initialized,reported,mismatch=measure(stream)
    timing=ET.parse(out/'output/bambu_results.xml').find('./timing/simulation')
    if timing is None:raise ValueError('Missing completed Bambu simulation timing')
    cycles=sum(int(node.text) for node in timing.findall('run'))
    success=(code==0 and timing.get('return_value')=='0' and initialized and not mismatch and reads==completed and (reads>0 or (case['suite']=='calibration' and args.n==0)))
    if case.get('marker'):success=success and any(s.strip()==case['marker'] for s in log.read_text().splitlines())
    top=layout(case)['top'];files=[*sorted((out/'output').rglob(top+'.v')),*sorted((out/'output').rglob('panda_libtech.v'))]
    data={'case':case['name'],'mode':'bambu_ramulator','n':args.n if case['suite']=='calibration' else layout(case)['n'],
          'functional_status':'pass' if success else 'fail','core_cycles':cycles,'drain_cycles':None,
          'measurement':'Bambu reported simulation-run cycles; not yet aligned with wrapper edge-distance counter',
          'observation_boundary':'Bambu MDPI backend, outside deployment relocation/control wrapper',
          'kernel_mhz':1000/float(case.get('clock_period_ns',b['default_clock_ns'])),
          'source_fingerprints':{m:digest(ROOT/m) for m in case['members']},'rtl_fingerprints':{str(p.relative_to(out)):digest(p) for p in files},
          'input_fingerprint':digest(out/'input-0.bin') if case['suite']=='calibration' else None,
          'yaml_sha256':digest(yaml),'bambu':provenance,'ramulator':dependency,
          'traffic':{'accepted_reads':reads,'completed_reads':completed,'accepted_writes':writes,'dram_ticks':ticks},
          'write_completion':'acceptance into Ramulator timing backend; not controller/device drain',
          'alignment_status':'unverified','argv':argv,'limitations':['No per-AXI-ID latency is inferred from aggregated MDPI summaries','Transformed integration RTL requires separate equivalence/alignment evidence']}
    write(out/'result.json',data)
    if not success:raise ValueError('Ferrandi co-simulation failed: '+str(log))
    print(out/'result.json')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--board',default='xcu55c');p.add_argument('--tests',action='append',default=[])
    p.add_argument('--config',required=True);p.add_argument('--output',required=True);p.add_argument('--n',type=int,default=513);p.add_argument('--timeout',type=float,default=600)
    a=p.parse_args()
    if a.n<0 or a.n>513 or not 0<a.timeout<=86400:raise ValueError('Invalid small calibration size/timeout')
    prov=verify_bambu(tool('bambu'),require_ramulator=True);dep=ramulator_install()
    for c in select(a.tests):execute(c,a,prov,dep)

if __name__=='__main__':
    try:main()
    except (ValueError,OSError,KeyError,ET.ParseError) as e:print('ERROR: '+str(e),file=sys.stderr);sys.exit(2)
