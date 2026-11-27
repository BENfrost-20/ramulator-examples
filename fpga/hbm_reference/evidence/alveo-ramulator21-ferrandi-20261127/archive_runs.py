"""Validate and archive a completed Ferrandi campaign."""
from collections import Counter, defaultdict
import csv
import gzip
import hashlib
import json
from pathlib import Path
from statistics import median
import shutil
import sys
import tarfile

HERE = Path(__file__).resolve().parent
PERIOD_PS = {
    "u280-hbm2-matched-1800": 1111,
    "u280-hbm2-bambu-2000": 1000,
    "ddr4-xci-matched-2400": 833,
    "u250-ddr4-bambu-2400": 833,
}
CHANNELS = {
    "u280-hbm2-matched-1800": 16,
    "u280-hbm2-bambu-2000": 16,
    "ddr4-xci-matched-2400": 1,
    "u250-ddr4-bambu-2400": 4,
}
PHASES = (0, 97, 195, 292)
AXI_EVENTS = {"AR": 1000, "read_accepted": 1000, "read_completed": 1000, "R": 1000}


def verify_inputs(source):
    manifest = source / "replay-inputs.sha256"
    for line in manifest.read_text().splitlines():
        digest, name = line.split(None, 1)
        if Path(name).is_absolute():
            continue
        for root in (source, HERE):
            if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest:
                raise ValueError(f"Input hash differs for {root / name}")


def verify_axi(run):
    with (run / "latencies.csv").open() as stream:
        samples = list(csv.DictReader(stream))
    with (run / "ramulator-axi.jsonl").open() as stream:
        events = [json.loads(line) for line in stream]
    counts = Counter(event["event"] for event in events)
    if len(samples) != 1000 or counts != AXI_EVENTS:
        raise ValueError(f"Expected 1,000 completed reads in {run}")
    started = [event["axi_cycle"] for event in events if event["event"] == "AR"]
    ended = [event["axi_cycle"] for event in events if event["event"] == "R"]
    expected = [int(sample["latency_cycles"]) for sample in samples]
    if [b - a for a, b in zip(started, ended)] != expected:
        raise ValueError(f"AXI trace differs from the latency CSV in {run}")
    model_addresses = {event["ramulator_addr"] for event in events if event["event"] == "read_accepted"}
    if model_addresses != {0x40000000}:
        raise ValueError(f"Unexpected model address in {run}: {model_addresses}")


def summarize_commands(files, scope):
    reads = Counter()
    refreshes = defaultdict(list)
    for file in files:
        with file.open() as stream:
            for row in csv.DictReader(stream):
                node = (int(row["Channel"]), int(row[scope]))
                if row["command"] in ("RD", "RDA"):
                    reads[node] += 1
                elif row["command"] == "REFab":
                    refreshes[node].append(int(row["clock"]))
    if len(reads) != 1 or sum(reads.values()) != 1000:
        raise ValueError(f"Expected 1,000 DRAM reads on one target: {reads}")
    (target, count), = reads.items()
    ticks = refreshes[target]
    cadence = median(b - a for a, b in zip(ticks, ticks[1:]))
    return count, *target, len(ticks), cadence


def main():
    source = Path(sys.argv[1]).resolve()
    verify_inputs(source)
    reference = HERE.parent / "u55c-ramulator21-ferrandi-20261127/ramulator-2.1/provenance.txt"
    provenance = source / "reused-u55c-provenance.txt"
    if provenance.read_bytes() != reference.read_bytes():
        shutil.copyfile(provenance, HERE / "replay-provenance.txt")
    shutil.copyfile(source / "replay-inputs.sha256", HERE / "replay-inputs.sha256")
    stats = []
    with (HERE / "diagnostics.tar.gz").open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as zipped:
            with tarfile.open(fileobj=zipped, mode="w") as archive:
                for profile, period in PERIOD_PS.items():
                    for phase in PHASES:
                        relative = Path("runs") / profile / f"phase-{phase}"
                        run = source / relative
                        verify_axi(run)
                        commands = sorted(run.glob("commands.csv.ch*"))
                        if len(commands) != CHANNELS[profile]:
                            raise ValueError(f"Missing command trace for {run}")
                        scope = "PseudoChannel" if profile.startswith("u280-hbm2") else "Rank"
                        count, channel, node, refreshes, cadence = summarize_commands(commands, scope)
                        stats.append((profile, phase, count, channel, scope, node, refreshes,
                                      cadence, f"{cadence * period / 1_000_000:.6f}"))
                        target = HERE / relative
                        target.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(run / "latencies.csv", target / "latencies.csv")
                        for file in [run / "run.log", run / "ramulator-axi.jsonl", *commands]:
                            archive.add(file, arcname=str(relative / file.name))
    with (HERE / "refresh-cadence.tsv").open("w", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        writer.writerow(("profile", "warmup_cycles", "dram_reads", "channel", "refresh_scope",
                         "scope_id", "refab_count", "median_dram_ticks", "median_us"))
        writer.writerows(stats)
    print(f"Validated {len(stats):,} replays and {1000 * len(stats):,} AXI and DRAM reads.")


if __name__ == "__main__":
    main()
