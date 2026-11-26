"""Generate a DDR4 profile from the exact XCI used in the hardware build."""
import json
from pathlib import Path
import sys

implementation = Path(sys.argv[1])
output = Path(sys.argv[2])
candidates = []
for path in implementation.rglob('*_ddr4_mem00_0.xci'):
    ip = json.loads(path.read_text(), strict=False)['ip_inst']
    if ip.get('component_reference', '').startswith('xilinx.com:ip:ddr4:'):
        if ip.get('cell_name', '').split('/')[-1] == 'ddr4_mem00':
            candidates.append((path, ip))
if len(candidates) != 1:
    raise SystemExit(f'Expected exactly one DDR[0] controller XCI, found {[p for p, _ in candidates]}')
path, ip = candidates[0]
parameters = ip['parameters']

def read(group, name):
    return parameters[group]['C0.' + name][0]['value']

def model(name):
    return int(read('model_parameters', 'DDR4_' + name))

def component(name):
    return read('component_parameters', 'DDR4_' + name)

geometry = [model(k) for k in ('MEM_COMP_WIDTH', 'ROW_WIDTH', 'COLUMN_WIDTH', 'BANK_WIDTH', 'BANK_GROUP_WIDTH', 'CS_WIDTH', 'DQ_WIDTH')]
if geometry != [4, 17, 10, 2, 2, 1, 72]:
    raise SystemExit(f'Unsupported DDR[0] geometry: {geometry}')
if model('tCK') != 833 or int(component('TimePeriod')) != 833:
    raise SystemExit('Expected 833 ps DDR4-2400; check the simulator clock ratio')
if component('AutoPrecharge').lower() != 'false':
    raise SystemExit('Review the row policy for this XCI')
timings = {
    'nBL': 4,
    'nCL': int(component('CasLatency')),
    'nCWL': int(component('CasWriteLatency')),
    'nRC': model('tRAS') + model('tRP'),
    **{'n' + key.replace('_', ''): model('t' + key)
       for key in ('RAS', 'RCD', 'RP', 'WR', 'RTP', 'RRD_S', 'RRD_L',
                   'WTR_S', 'WTR_L', 'FAW', 'RFC', 'REFI')},
}
if min(timings.values()) <= 0:
    raise SystemExit(f'Invalid generated timings: {timings}')

profile = [
    f'# Source: {path}',
    f'# Module: {component("MemoryPart")}. Payload bus excludes ECC bits.',
    'Frontend:', '  impl: GEM5', 'MemorySystem:', '  impl: GenericDRAM',
    '  clock_ratio: 12', '  DRAM:', '    impl: DDR4', '    org:',
    '      preset: DDR4_8Gb_x4', '      channel: 1', '      rank: 1',
    '      channel_width: 64', '    timing:', '      preset: DDR4_2400U',
    *(f'      {key}: {value}' for key, value in timings.items()),
    '  Controller:', '    impl: Generic', '    Scheduler:', '      impl: FRFCFS',
    '    RefreshManager:', '      impl: AllBank', '    RowPolicy:',
    '      impl: OpenRowPolicy', '  AddrMapper:', '    impl: RoBaRaCoCh',
]
output.write_text('\n'.join(profile) + '\n')
print(path)
print('Module:', component('MemoryPart'))
print('Ordering:', component('Ordering'))
print('AXI arbitration:', component('AxiArbitrationScheme'))
print(timings)
