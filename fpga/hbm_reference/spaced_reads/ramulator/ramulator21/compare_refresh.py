"""Validate the recorded commands and report refresh cadence for the target pseudochannel."""
import csv
from collections import Counter
from pathlib import Path
from statistics import median
import sys


def main():
    root = Path(sys.argv[1])
    print("profile\tphase\tread_commands\tchannel\tpseudochannel\tREFab\tmedian_interval_dram_ticks")
    for profile in ("bambu-2000", "matched-rate-1800"):
        for phase in (0, 97, 195, 292):
            channels = sorted((root / profile / f"phase-{phase}").glob("commands.csv.ch*"))
            if not channels:
                raise ValueError(f"Missing command logs for {profile} phase {phase}")
            reads = Counter()
            refresh = {}
            for path in channels:
                with path.open() as stream:
                    for row in csv.DictReader(stream):
                        key = (row["Channel"], row["PseudoChannel"])
                        if row["command"] in ("RD", "RDA"):
                            reads[key] += 1
                        elif row["command"] == "REFab":
                            refresh.setdefault(key, []).append(int(row["clock"]))
            if len(reads) != 1 or sum(reads.values()) != 1000:
                raise ValueError(f"Expected 1000 reads on one target, got {reads}")
            (key, count), = reads.items()
            ticks = refresh[key]
            cadence = median(b - a for a, b in zip(ticks, ticks[1:]))
            print(profile, phase, count, *key, len(ticks), cadence, sep="\t")


if __name__ == "__main__":
    main()
