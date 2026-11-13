"""Run self-checking real RTL control/counter tests; never silently skip tools."""
import argparse
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fpga.run import run

p=argparse.ArgumentParser(description=__doc__);p.add_argument('--simulator',choices=['verilator','xsim'],default='verilator');p.add_argument('--bench',choices=['control','completion'],default='completion');p.add_argument('--output',default='.fpga/completion-test');a=p.parse_args()
out=Path(a.output).resolve();out.mkdir(parents=True,exist_ok=False)
top=a.bench+'_tb'
files=[ROOT/'fpga/rtl/control.sv',ROOT/'fpga/rtl/drain.sv',ROOT/('fpga/tests/'+top+'.sv')]
if a.simulator=='verilator':
    run([os.environ.get('FPGA_VERILATOR','verilator'),'--binary','--timing','-Wno-fatal','--top-module',top,'--Mdir',out/'obj',*files],out,out/'compile.log')
    run([out/('obj/V'+top)],out,out/'run.log')
else:
    run(['xvlog','--sv',*files],out,out/'compile.log')
    run(['xelab',top,'-s','control_test'],out,out/'elaborate.log')
    run(['xsim','control_test','-runall'],out,out/'run.log')
if ('CONTROL TEST PASS' if a.bench=='control' else 'COMPLETION TRACKER TEST PASS') not in (out/'run.log').read_text(): raise SystemExit('Simulation did not complete checks')
print((out/'run.log').read_text())
