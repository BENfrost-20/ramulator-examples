import csv
from bisect import bisect_right
import sys
from math import ceil
from pathlib import Path


def load(path):
    with path.open() as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 1000:
        raise ValueError(f"Expected 1000 samples: {path}")
    values = []
    for i, row in enumerate(rows, 1):
        ar, valid, r, latency = (int(row[k]) for k in ("ar_cycle", "rvalid_cycle", "r_cycle", "latency_cycles"))
        if int(row["sample"]) != i or not ar < valid == r or r - ar != latency:
            raise ValueError(f"Invalid sample {i}: {path}")
        values.append(latency)
    return sorted(values)


def quantiles(values):
    return [values[ceil(len(values) * q) - 1] for q in (.5, .9, .95, .99, 1)]


hw = load(Path(sys.argv[1]))
ref = quantiles(hw)
print("run\tp50\tp90\tp95\tp99\tmax\tshift_HW_minus_sim\tresidual_p95\tresidual_p99\tmax_cdf_gap_pp")
print("hardware", *ref, "-", "-", "-", "-", sep="\t")
for path in sorted(Path(sys.argv[2]).glob("phase-*/latencies.csv"), key=lambda p:int(p.parent.name[6:])):
    sim = load(path)
    q = quantiles(sim)
    shift = ref[0] - q[0]
    aligned = [value + shift for value in sim]
    support = set(hw) | set(aligned)
    gap = max(abs(bisect_right(hw, x) - bisect_right(aligned, x)) for x in support)
    print(path.parent.name, *q, shift, ref[2] - (q[2] + shift), ref[3] - (q[3] + shift),
          f"{100 * gap / len(hw):.1f}", sep="\t")
