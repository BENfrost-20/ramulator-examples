"""Fingerprint actual source/build provenance before interpreting Ramulator clocks."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

FILES=('etc/libmdpi/mdpi_driver.cpp','src/HLS/interface/bus_interface.cpp')
RAMFILES=('src/dram/impl/HBM2.cpp','src/dram/impl/DDR4.cpp','src/addr_mapper/impl/linear_mappers.cpp',
          'src/dram_controller/impl/generic_dram_controller.cpp','src/base/request.h')


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def git(path,*args):
    p=subprocess.run(['git','-C',str(path),*args],capture_output=True,text=True)
    return p.stdout.strip() if not p.returncode else None


def audit(bambu,ramulator):
    b=Path(bambu);r=Path(ramulator)
    meta={'bambu':{'revision':git(b,'rev-parse','HEAD'),'remotes':git(b,'remote','-v'),'files':{}},
          'ramulator':{'revision':git(r,'rev-parse','HEAD'),'remotes':git(r,'remote','-v'),'files':{}},
          'warnings':[]}
    for root,group,files in ((b,'bambu',FILES),(r,'ramulator',RAMFILES)):
        for file in files:
            path=root/file
            if path.is_file():meta[group]['files'][file]=sha(path)
            else:meta['warnings'].append('Missing '+str(path))
    driver=(b/FILES[0]).read_text()
    bridge=all(name in driver for name in ('__m_interface_mem_ramulator','receive_external_requests','mem_interface_ramulator'))
    meta['bambu']['ramulator_bridge_in_examined_driver']=bridge
    if not bridge:meta['warnings'].append('Examined Bambu driver has no Ramulator bridge; not evidence for installed Ramulator cosimulation')
    meta['bambu']['fractional_phase_accumulator']=all(name in driver for name in ('clock_phase += clock_ratio','memory->tick()','clock_phase -= 1.0'))
    meta['bambu']['write_completion']='Ramulator acceptance; not device-cell completion' if 'write_request' in driver and 'writes_issued' in driver else 'unverified'
    meta['bambu']['truncating_tick_scaling']=bool(re.search(r'\(int\)\s*\([^;]*frequency_scaling_factor',driver))
    if meta['bambu']['truncating_tick_scaling']:
        meta['warnings'].append('Driver truncates each tick batch times ratio to int; fractional ratios require audit of tick batching')
    hbm=(r/RAMFILES[0]).read_text()
    org=re.search(r'org_presets\s*=\s*\{(.*?)\n\s*\};',hbm,re.S)
    timing=re.search(r'timing_presets\s*=\s*\{(.*?)\n\s*\};',hbm,re.S)
    meta['ramulator']['hbm2_org_presets']=re.findall(r'\{"([^"]+)"',org[1]) if org else []
    meta['ramulator']['hbm2_timing_presets']=re.findall(r'\{"([^"]+)"',timing[1]) if timing else []
    meta['ramulator']['hbm2_levels']=['channel','pseudochannel','bankgroup','bank','row','column']
    meta['ramulator']['hbm2_transaction_bytes']=32 if 'm_internal_prefetch_size = 2' in hbm and re.search(r'HBM2_4Gb[^\n]*128',hbm) else None
    meta['warnings'] += ['Source checkout fingerprints do not prove the installed binaries were built from these sources.',
                         'HBM2_4Gb includes two pseudochannels per modeled channel; channel=32 is not a proof of 32 physical pseudochannels.',
                         'HBM2_2Gbps is not a verified U55C HBM2e timing model. Vendor controller/address policy alignment remains unknown.']
    return meta


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--bambu-source',required=True);p.add_argument('--ramulator-source',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    result=audit(a.bambu_source,a.ramulator_source);Path(a.output).parent.mkdir(parents=True,exist_ok=True);Path(a.output).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
