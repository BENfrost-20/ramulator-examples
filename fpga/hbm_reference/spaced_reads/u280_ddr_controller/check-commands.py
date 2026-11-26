import collections
import csv
import sys
from pathlib import Path

trace = Path(sys.argv[1])
anchor = int(sys.argv[2], 0) - 0x1000000000
mode = int(sys.argv[3])
b = anchor ^ (0x100, 0x20000, 0x200)[mode]

def coordinates(a):
    row = a >> 17
    group = (a >> 6) & 3
    bank = (a >> 9) & 3
    burst_column = ((a >> 11) & 63) << 1 | (a >> 8) & 1
    return [0, 0, group, bank, row, burst_column]

expected = [coordinates(anchor), coordinates(b)] * 500
observed = []
counts = collections.Counter()
with trace.open(newline="") as file:
    for _, tick, command, *address in csv.reader(file):
        counts[command] += 1
        if command in {"RD", "RDA"}:
            observed.append(list(map(int, address)))
if observed != expected:
    mismatch = next((i for i, (a, b) in enumerate(zip(observed, expected)) if a != b), None)
    raise SystemExit(f"Read-command address mismatch in {trace}: {len(observed)} reads, first mismatch {mismatch}")
if not counts["ACT"] or not (counts["REF"] or counts["REFab"]):
    raise SystemExit(f"ACT or refresh missing from {trace}")
print("PASS DDR4 read coordinates", dict(sorted(counts.items())))
