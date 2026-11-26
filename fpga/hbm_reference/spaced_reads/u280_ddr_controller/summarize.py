import csv
import math
import sys
from pathlib import Path

names = {"same-row": 0x100, "same-bank": 0x20000, "different-bank": 0x200}
root = Path(sys.argv[1])
anchor = None
print("case\trun\tsamples\tp50\tp95\tp99\tmax\tp50_minus_same_row")
rows = {}
for name, mask in names.items():
    paths = sorted(path for path in root.glob(f"{name}-*.csv")
                   if path.stem.rsplit("-", 1)[1].isdigit())
    if not paths:
        raise SystemExit(f"Missing samples for {name} in {root}")
    for path in paths:
        run = path.stem.rsplit("-", 1)[1]
        with path.open(newline="") as file:
            samples = list(csv.DictReader(file))
        if len(samples) != 1000:
            raise SystemExit(f"Expected 1000 samples in {path}")
        if anchor is None:
            anchor = int(samples[0]["axi_address"], 0)
        previous = 0
        latencies = []
        for i, sample in enumerate(samples):
            ar = int(sample["ar_cycle"])
            rv = int(sample["rvalid_cycle"])
            r = int(sample["r_cycle"])
            latency = int(sample["latency_cycles"])
            address = int(sample["axi_address"], 0)
            if (int(sample["sample"]) != i + 1 or address != anchor ^ (mask if i % 2 else 0)
                or ar < previous + (8 if i else 50) or r <= ar or rv != r or latency != r - ar):
                raise SystemExit(f"Bad address or handshake timing in {path}, sample {i + 1}")
            latencies.append(latency)
            previous = r
        # Exclude the first access from the steady-state summary.
        ordered = sorted(latencies[1:])
        quantiles = [ordered[math.ceil(len(ordered) * p) - 1] for p in (0.50, 0.95, 0.99, 1)]
        rows[name, run] = quantiles
for (name, run), quantiles in rows.items():
    baseline = rows.get(("same-row", run))
    if baseline is None:
        raise SystemExit(f"Missing same-row baseline for run {run}")
    print(name, run, 999, *quantiles, quantiles[0] - baseline[0], sep="\t")
