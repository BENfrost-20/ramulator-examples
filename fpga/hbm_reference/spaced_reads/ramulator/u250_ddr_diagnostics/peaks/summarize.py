"""Summarize peak fractions with the same +25-cycle shift for each model."""
from collections import Counter
import csv
from math import ceil
from pathlib import Path
import sys

root = Path(sys.argv[1])
phases = (0, 97, 195, 292)
profiles = ('xci', 'refresh-2x-diagnostic', 'refresh-4x-diagnostic')

def load(path, offset):
    values = []
    with path.open() as stream:
        for i, row in enumerate(csv.DictReader(stream), 1):
            ar, valid, response, latency = (int(row[k]) for k in
                ('ar_cycle', 'rvalid_cycle', 'r_cycle', 'latency_cycles'))
            if not (int(row['sample']) == i and ar < valid == response and response - ar == latency):
                raise ValueError(f'Invalid sample {i} in {path}')
            values.append(latency + offset)
    if len(values) != 1000:
        raise ValueError(f'Expected 1,000 samples in {path}')
    return values

def report(profile, phase, values):
    count = Counter(values)
    total = len(values)
    ordered = sorted(values)
    p50, p99 = (ordered[ceil(total * q) - 1] for q in (.5, .99))
    percent = lambda n: f'{100 * n / total:.2f}'
    print(profile, phase, total, percent(count[28]), percent(count[30]),
          percent(sum(v > 45 for v in values)), p50, p99, sep='\t')

print('profile\tphase\tsamples\tpct_at_28\tpct_at_30\tpct_above_45\tp50_cycles\tp99_cycles')
report('hardware', 'pooled', [v for i in (1, 2, 3)
                             for v in load(root / 'hardware' / f'reads-{i}.csv', 0)])
for profile in profiles:
    pooled = []
    for phase in phases:
        values = load(root / profile / f'phase-{phase}' / 'latencies.csv', 25)
        report(profile, phase, values)
        pooled.extend(values)
    report(profile, 'pooled', pooled)
