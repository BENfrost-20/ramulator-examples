"""Execute one unambiguous vendor-exported launcher on an authorized machine."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.execution import launch
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--export',required=True);p.add_argument('--simulator',choices=['questa','vcs'],default='questa');p.add_argument('--timeout',type=float,default=3600);a=p.parse_args()
root=Path(a.export).resolve()/a.simulator
scripts=sorted(root.glob('*.sh'))
if len(scripts)!=1:raise SystemExit('Expected one exported launcher; inspect '+str(root)+': '+str(scripts))
if not 0<a.timeout<=86400:raise SystemExit('Invalid timeout')
env=os.environ.copy();prefix=env.get('FPGA_'+a.simulator.upper())
if prefix:env['PATH']=prefix+os.pathsep+env.get('PATH','')
# Run the original generated compile/elaborate/simulate script. No IP model
# is relabeled or replaced if encrypted compilation or licensing fails.
log=root/'run-export.log'
code=launch(['bash',str(scripts[0])],root,log,env,a.timeout)
print(log)
if code is None:raise SystemExit('Vendor launcher timed out; its process group was terminated; inspect '+str(log))
sys.exit(code)
