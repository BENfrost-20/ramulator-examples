"""Version-gated Questa/VCS support for vendor-generated simulation projects.
No default IP settings, controller model, address mapping or timing fidelity is
invented. An IP example is labeled a smoke test, never benchmark validation.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from fpga.run import board,capture,run,tool,write
from fpga.prepare import digest,ports

SUPPORTED={'questa':'2024.1','vcs':'V-2023.12-SP1'}


def validate(config,simulator,prepared=None):
    if config['simulator']!=simulator or config['simulator_release']!=SUPPORTED[simulator]: raise ValueError('Vivado 2024.2 requires '+simulator+' '+SUPPORTED[simulator]+'; installed executable alone is insufficient')
    executable='vsim' if simulator=='questa' else 'vcs'
    prefix=os.environ.get('FPGA_'+simulator.upper())
    binary=str(Path(prefix)/executable) if prefix else shutil.which(executable) or executable
    identity=capture([binary,'-version' if simulator=='questa' else '-ID'])
    if identity['exit_code'] or SUPPORTED[simulator] not in identity['output']: raise ValueError('Usable supported simulator not verified: '+str(identity))
    for name in ('xci','compiled_libraries'):
        if 'REPLACE' in config[name] or not Path(config[name]).exists(): raise ValueError('Missing '+name+': '+config[name])
    libs=Path(config['compiled_libraries']);init='modelsim.ini' if simulator=='questa' else 'synopsys_sim.setup'
    if not (libs/init).is_file(): raise ValueError('Missing compiled encrypted-library map '+str(libs/init))
    b,profile=board(config['board'])
    if config['ip_vlnv']!=profile['model_ip']: raise ValueError('Board memory IP mismatch; no HBM fallback for DDR/non-AMD boards')
    if prepared:
        for name in ('project','testbench_top','initialization','native_protocol','conversion','evidence'):
            if name not in config or not config[name] or 'REPLACE' in str(config[name]): raise ValueError('Integrated vendor workload requires verified '+name)
        for name in ('interface_clocks_mhz','memory_clocks_mhz','platform_differences'):
            if not config.get(name): raise ValueError('Missing model alignment field '+name)
        if not Path(config['project']).is_file(): raise ValueError('Integrated vendor project missing; IP example is not a workload backend')
        if config['observation_boundary']!='wrapper/platform AXI': raise ValueError('Document and implement a common observation boundary')
        if any(config['fidelity'].get(key) in ('unknown',None,'') for key in ('read_latency','write_latency','bank_row','refresh','controller_policy','queues')):
            raise ValueError('Timing behavior/omissions not verified; complete fidelity evidence before reference use')
        info=json.loads((Path(prepared)/'manifest.json').read_text())
        if info.get('reference_only'): raise ValueError('Regenerate Ferrandi DUT for board reference experiment')
        for name,sha in info['rtl_sha256'].items():
            if digest(Path(prepared)/'rtl'/name)!=sha: raise ValueError('Prepared RTL changed')
    return identity,profile


def bind_monitors(prepared,out):
    prepared=Path(prepared);info=json.loads((prepared/'manifest.json').read_text())
    parsed=ports((prepared/'rtl'/(info['top']+'.v')).read_text(),info['top'])
    signals=['arvalid','arready','arid','araddr','arlen','arsize','arburst','rvalid','rready','rid','rlast','rresp',
             'awvalid','awready','awid','awaddr','awlen','awsize','awburst','wvalid','wready','wstrb','wlast','bvalid','bready','bid','bresp']
    lines=[]
    for i,p in enumerate(info['axi_ports']):
        connections=['.clk(ap_clk)','.resetn(ap_rst_n)']+[f'.{s}({p}_{s})' for s in signals]
        lines += [f'bind fpga_kernel axi_trace #(.ID_W({parsed[p+"_arid"][1]}),.FILE("trace-{i}.jsonl")) trace_{i}('+','.join(connections)+');']
    (Path(out)/'bind_monitors.sv').write_text('\n'.join(lines)+'\n')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['preflight','ip-example','export'])
    p.add_argument('--config',required=True);p.add_argument('--simulator',choices=SUPPORTED,default='questa')
    p.add_argument('--prepared');p.add_argument('--output',required=True);args=p.parse_args()
    c=json.loads(Path(args.config).read_text());identity,profile=validate(c,args.simulator,args.prepared if args.command=='export' else None)
    out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=False)
    write(out/'provenance.json',{'config':c,'config_sha256':digest(args.config),'simulator':identity,'vivado':capture([tool('vivado'),'-version']),
                                'status':'preflight only; no completed vendor workload reference'})
    if args.command=='preflight':return
    if args.command=='ip-example':
        run([tool('vivado'),'-mode','batch','-source',ROOT/'validation/tcl/ip_example.tcl','-tclargs',profile['part'],Path(c['xci']).resolve(),args.simulator,out,Path(c['compiled_libraries']).resolve()],out,out/'generate.log')
        print('Exported IP example smoke only. Inspect generated simulator script and run deliberately; not a benchmark result.')
    else:
        if not args.prepared: raise ValueError('--prepared required for integrated DUT export')
        bind_monitors(args.prepared,out)
        run([tool('vivado'),'-mode','batch','-source',ROOT/'validation/tcl/export_vendor.tcl','-tclargs',Path(c['project']).resolve(),args.simulator,
             Path(c['compiled_libraries']).resolve(),out,c['testbench_top'],c['runtime'],Path(args.prepared).resolve(),ROOT/'validation/rtl/axi_trace.sv'],out,out/'export.log')
        print('Exported integrated project; execute the vendor-generated simulator launcher deliberately. Verify workload oracle and traces before collecting a reference result.')

if __name__=='__main__':
    try:main()
    except (ValueError,OSError,KeyError) as e:print('ERROR: '+str(e),file=sys.stderr);sys.exit(2)
