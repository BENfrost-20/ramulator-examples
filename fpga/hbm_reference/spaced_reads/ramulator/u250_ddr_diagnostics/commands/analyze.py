"""Associate issued DDR4 commands with single-outstanding AXI reads."""
from bisect import bisect_right
from collections import Counter
import csv
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
counts = Counter()
gaps = []
print('phase\treads_3c\t3c_with_ACT\treads_5c\t5c_with_ACT\tREFab\tmin_REFab_to_ACT_ticks')
for phase in (0, 97, 195, 292):
    folder = root / f'phase-{phase}'
    with (folder / 'ddr4-commands.tsv').open() as stream:
        commands = [(int(r['tick']), r['command']) for r in csv.DictReader(stream, delimiter='\t')]
    events = [json.loads(line) for line in (folder / 'ramulator-axi.jsonl').read_text().splitlines()]
    accepted = [e['dram_tick'] for e in events if e['event'] == 'read_accepted']
    completed = [e['dram_tick'] for e in events if e['event'] == 'read_completed']
    with (folder / 'latencies.csv').open() as stream:
        latencies = [int(r['latency_cycles']) for r in csv.DictReader(stream)]
    reads = [t for t, command in commands if command in ('RD', 'RDA')]
    acts = [t for t, command in commands if command == 'ACT']
    refs = [t for t, command in commands if command == 'REFab']
    if not (len(accepted) == len(completed) == len(latencies) == len(reads) == 1000 and refs and acts):
        raise SystemExit(f'Incomplete or inconsistent trace in {folder}')
    if not all(start < rd <= end for start, rd, end in zip(accepted, reads, completed)):
        raise SystemExit(f'DRAM and AXI clocks disagree in {folder}')
    stats = Counter((latency, bisect_right(acts, rd) > bisect_right(acts, start))
                    for latency, start, rd in zip(latencies, accepted, reads))
    counts.update(stats)
    phase_gaps = [act - ref for ref in refs
                  for i in [bisect_right(acts, ref)] if i < len(acts)
                  for act in [acts[i]]]
    gaps.extend(phase_gaps)
    print(phase, stats[3, False] + stats[3, True], stats[3, True],
          stats[5, False] + stats[5, True], stats[5, True], len(refs), min(phase_gaps), sep='\t')
print('pooled', counts[3, False] + counts[3, True], counts[3, True],
      counts[5, False] + counts[5, True], counts[5, True], '-', min(gaps), sep='\t')
if min(gaps) < 421:
    raise SystemExit('Observed an ACT fewer than 421 DRAM ticks after REFab')
