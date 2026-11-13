"""Focused deployment commands; nothing programs a board automatically."""
import argparse
from collections import Counter
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

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fpga.catalog import registry, select, SMALL
from fpga.provenance import verify_bambu
from fpga.prepare import ABI, digest, layout, make_abi_header, prepare
from fpga.hostgen import write as hostgen
from tools.execution import load_board_profiles, stage_case


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


def run(argv,cwd,log):
    print('$ '+shlex.join(map(str,argv)),flush=True)
    with Path(log).open('w') as f:
        f.write('$ '+shlex.join(map(str,argv))+'\n');f.flush()
        p=subprocess.run(list(map(str,argv)),cwd=cwd,stdout=f,stderr=subprocess.STDOUT)
    if p.returncode: raise ValueError(f'Command exited {p.returncode}; see {log}')


def generate(case,args):
    provenance=verify_bambu(tool('bambu'))
    b,p=board(args.board);period=float(case.get('clock_period_ns',b['default_clock_ns']))
    out=Path(args.output).resolve()/case['name'];out.mkdir(parents=True,exist_ok=False)
    snapshot=out/'snapshot';snapshot.mkdir()
    if case['suite']=='calibration':
        source=ROOT/'fpga/calibration/memory_probe.c'
        shutil.copyfile(source,snapshot/source.name)
        flags=[f.replace('@/fpga/calibration/memory_probe.c',str(snapshot/source.name)) for f in case['flags']]
        argv=[tool('bambu'),*flags,f"--device-name={b['bambu_device']}",f'--clock-period={period}',f'--output-directory={out}/hls']
    else:
        # Shared staging preserves source trees, flags/macros, board, clock and YAML.
        argv,yaml=stage_case(case,snapshot,None,tool('bambu'),b)
        # Remove simulation-only requests; DUT flags remain unchanged.
        argv=[a for a in argv if a not in ('--simulate','--enable-ramulator') and not a.startswith(('--simulator=','--generate-tb=','--tb-','--max-sim-cycles=','--output-directory='))]
        argv.append(f'--output-directory={out}/hls')
    identity=capture([tool('bambu'),'--version'])
    if identity['exit_code']: raise ValueError('Bambu version check failed; see '+str(out))
    write(out/'generation.json',{'case':case['name'],'board':args.board,'period_ns':period,'argv':argv,'compiler':'I386_CLANG13',
                               'bambu':identity,'provenance':provenance,'source_sha256':{m:digest(ROOT/m) for m in case['members']},'git_base':capture(['git','-C',str(ROOT),'rev-parse','HEAD'])})
    run(argv,out,out/'bambu.log')
    top=layout(case)['top']
    candidates=list((out/'hls').rglob(top+'.v'))
    if len(candidates)!=1: raise ValueError('Expected one generated '+top+'.v; inspect '+str(out/'hls'))
    rtl_dir=candidates[0].parent
    gen=json.loads((out/'generation.json').read_text())
    gen['rtl_sha256']={name:digest(rtl_dir/name) for name in (top+'.v','panda_libtech.v')}
    gen['rtl_dir']=str(rtl_dir)
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


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('command',choices=['inventory','preflight','generate','prepare','package','link','host','native'])
    ap.add_argument('--board',default='xcu55c');ap.add_argument('--tests',action='append',default=[])
    ap.add_argument('--all-supported',action='store_true');ap.add_argument('--output')
    ap.add_argument('--rtl-dir');ap.add_argument('--prepared');ap.add_argument('--generation')
    ap.add_argument('--fix-adapter-log2',action='store_true');ap.add_argument('--period',default='10')
    ap.add_argument('--target',choices=['hw','hw_emu'],default='hw_emu')
    args=ap.parse_args()
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
        if len(cases)!=1 or not args.rtl_dir: raise ValueError('prepare requires one exact --tests case and --rtl-dir containing TOP.v + panda_libtech.v')
        out=Path(args.output).resolve();info=prepare(cases[0],args.rtl_dir,out,args.fix_adapter_log2)
        if args.generation:
            gen=json.loads(Path(args.generation).read_text())
            if gen['case']!=cases[0]['name'] or gen['board']!=args.board: raise ValueError('Generation case/board mismatch')
            if gen.get('rtl_sha256')!=info['original_sha256']: raise ValueError('RTL does not match generation fingerprints')
            if info['frontend']!=gen['compiler']: raise ValueError('Generated frontend differs from generation receipt')
            info['generation']=gen
        else: info['reference_only']=True
        write(out/'manifest.json',info);registers(info,out);hostgen(cases[0],info,out)
        print('Prepared '+str(out));return 0
    if not args.prepared: raise ValueError('--prepared required')
    out=Path(args.prepared).resolve();info=json.loads((out/'manifest.json').read_text())
    if args.command=='host':
        xrt=Path(os.environ.get('XILINX_XRT','/opt/xilinx/xrt'))
        flags=json.loads((out/'host-flags.json').read_text())
        run([os.environ.get('CXX','g++'),'-std=c++17','-O2','-Wno-unknown-pragmas','-pthread','-I'+str(out),'-I'+str(ROOT/'fpga/host'),'-I'+str(xrt/'include'),*flags,
             ROOT/'fpga/host/host.cpp','-L'+str(xrt/'lib'),'-Wl,-rpath,'+str(xrt/'lib'),'-lxrt_coreutil','-o',out/'host'],out,out/'host-build.log');return 0
    if info.get('reference_only'): raise ValueError('Reference RTL has no board-correct generation receipt; regenerate actual selected Bambu DUT first')
    gen=info['generation'];b,p=board(gen['board']);period=gen['period_ns'];plat,r=receipt(gen['board'],p,period)
    for name,sha in info['rtl_sha256'].items():
        if digest(out/'rtl'/name)!=sha: raise ValueError('Prepared RTL changed: '+name)
    if args.command=='package':
        run([tool('vivado'),'-mode','batch','-source',ROOT/'fpga/tcl/package.tcl','-tclargs',out,p['part'],period],out,out/'package.log')
        if not (out/'fpga_kernel.xo').is_file(): raise ValueError('XO missing')
    else:
        connections=[]
        for i,port in enumerate(info['axi_ports']): connections.append(f'sp=fpga_kernel_1.{port}:{p["resources"][i if info["banks"]==2 else 0]}')
        cfg=out/'connectivity.cfg';cfg.write_text('[connectivity]\nnk=fpga_kernel:1:fpga_kernel_1\n'+'\n'.join(connections)+'\n')
        dest=out/args.target;dest.mkdir(exist_ok=False)
        run([tool('v++'),'--link','--target',args.target,'--platform',plat,'--config',cfg,'--kernel_frequency',str(1000/period),
             '--save-temps','--temp_dir',dest/'temp','--log_dir',dest/'logs','--report_dir',dest/'reports','-o',dest/'fpga_kernel.xclbin',out/'fpga_kernel.xo'],dest,dest/'link.log')
        if not (dest/'fpga_kernel.xclbin').is_file(): raise ValueError('xclbin missing')
        write(dest/'build.json',{'target':args.target,'platform':r,'manifest_sha256':digest(out/'manifest.json'),'xclbin_sha256':digest(dest/'fpga_kernel.xclbin'),
                                 'implementation_timing':'inspect routed DCP with check_implementation.tcl; link completion alone is not timing approval'})
        if args.target=='hw_emu': run(['emconfigutil','--platform',plat,'--od',dest],dest,dest/'emconfig.log')
    return 0

if __name__=='__main__':
    try: sys.exit(main())
    except (ValueError,OSError,KeyError,subprocess.SubprocessError) as e:
        print('ERROR: '+str(e),file=sys.stderr);sys.exit(2)
