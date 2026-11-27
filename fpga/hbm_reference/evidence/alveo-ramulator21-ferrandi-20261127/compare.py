"""Validate the Alveo replays and produce English latency comparison figures."""
import argparse
from bisect import bisect_right
import csv
from math import ceil
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import PercentFormatter

HERE = Path(__file__).resolve().parent
EVIDENCE = HERE.parent
U55C = EVIDENCE / "u55c-ramulator21-ferrandi-20261127"
RUNS = HERE / "runs"
PHASES = (0, 97, 195, 292)
COLORS = ("#242B36", "#BF5A13", "#007D75", "#4263AD")
STYLES = ("-", "--", "-", ":")
MARKERS = (None, "s", "o", "^")

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 10,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.labelcolor": "#303842",
    "axes.titlesize": 12,
    "axes.titleweight": "bold",
    "xtick.color": "#303842",
    "ytick.color": "#303842",
    "svg.hashsalt": "u55c-ramulator-ferrandi",
})


BOARDS = {
    "u55c-hbm2": (
        "U55C HBM2",
        ["spaced_reads_u55c_08.csv"],
        f"{U55C.name}/ramulator-2.0/phase-{{phase}}/latencies.csv",
        "1800 MT/s",
        (U55C / "ramulator-2.1/matched-rate-1800", "Ramulator 2.1 · 1800 MT/s"),
        (U55C / "ramulator-2.1/bambu-2000", "Ramulator 2.1 · 2000 MT/s"),
    ),
    "u280-hbm2": (
        "U280 HBM2",
        [f"spaced_reads_u280_hbm_legacy{node:02d}_run{run}.csv"
         for node in (1, 2) for run in (1, 2, 3)] +
        [f"spaced_reads_u280_hbm_legacy01_run{run}_20261124.csv" for run in (1, 2, 3)],
        "spaced_reads_u280_ramulator_phase{phase}.csv",
        "1800 MT/s",
        (RUNS / "u280-hbm2-matched-1800", "Ramulator 2.1 · 1800 MT/s"),
        (RUNS / "u280-hbm2-bambu-2000", "Ramulator 2.1 · 2000 MT/s"),
    ),
    "u280-ddr4": (
        "U280 DDR4",
        [f"spaced_reads_u280_ddr_legacy01_run{run}_20261124.csv" for run in (1, 2, 3)],
        "spaced_reads_ddr4_ramulator_xci_phase{phase}.csv",
        "2400 MT/s XCI",
        (RUNS / "ddr4-xci-matched-2400", "Ramulator 2.1 · 2400 MT/s XCI"),
    ),
    "u250-ddr4": (
        "U250 DDR4",
        [f"spaced_reads_u250_ddr_legacy02_run{run}_20261125.csv" for run in (1, 2, 3)],
        "spaced_reads_ddr4_ramulator_xci_phase{phase}.csv",
        "2400 MT/s XCI",
        (RUNS / "ddr4-xci-matched-2400", "Ramulator 2.1 · 2400 MT/s XCI"),
        (RUNS / "u250-ddr4-bambu-2400", "Ramulator 2.1 · 2400 MT/s Bambu"),
    ),
}


def read_latencies(path):
    with path.open() as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 1000:
        raise ValueError(f"Expected 1,000 reads in {path}")
    for sample, row in enumerate(rows, 1):
        ar, valid, r, latency = (int(row[k]) for k in ("ar_cycle", "rvalid_cycle", "r_cycle", "latency_cycles"))
        if int(row["sample"]) != sample or not ar < valid == r or latency != r - ar:
            raise ValueError(f"Invalid AXI timing for sample {sample} in {path}")
    return sorted(int(row["latency_cycles"]) for row in rows)


def quantiles(values):
    return [values[ceil(len(values) * p) - 1] for p in (0.5, 0.9, 0.95, 0.99, 1)]


def save(fig, out, filename):
    svg = out / f"{filename}.svg"
    fig.savefig(svg, facecolor="white", metadata={"Date": None})
    svg.write_text("\n".join(line.rstrip() for line in svg.read_text().splitlines()) + "\n")
    plt.close(fig)


def header(fig, title, detail):
    fig.text(0.07, 0.95, title, fontsize=18, weight="bold", color="#17212E", va="top")
    fig.text(0.07, 0.88, detail, fontsize=10, color="#465469", va="top")


def styled_grid(ax):
    ax.set_axisbelow(True)
    ax.grid(axis="y", color="#DCE3EB", linewidth=0.7)
    ax.spines["left"].set_color("#BBC5D0")
    ax.spines["bottom"].set_color("#BBC5D0")


def simulation_paths(board, baseline, variants, phase):
    baseline_file = EVIDENCE / baseline.format(phase=phase)
    if board == "u55c-hbm2" and phase == 292:
        baseline_file = EVIDENCE / "spaced_reads_u55c_ramulator_phase292.csv"
    return [baseline_file, *(profile / f"phase-{phase}" / "latencies.csv" for profile, _ in variants)]


def compare(hardware, model):
    hw_q, sim_q = quantiles(hardware), quantiles(model)
    shift = hw_q[0] - sim_q[0]
    aligned = [value + shift for value in model]
    gap = max(abs(bisect_right(hardware, x) / len(hardware) - bisect_right(aligned, x) / len(aligned))
              for x in set(hardware) | set(aligned))
    return shift, 100 * gap, hw_q[2] - sim_q[2] - shift, hw_q[3] - sim_q[3] - shift


def legend(fig, labels, indices, markers=False, bars=None):
    handles = bars if bars is not None else [
        Line2D([], [], color=COLORS[i], linestyle=STYLES[i], linewidth=2,
               marker=MARKERS[i] if markers else None) for i in indices
    ]
    fig.legend(handles, [labels[i] for i in indices], loc="lower center",
               bbox_to_anchor=(0.5, 0.025), ncol=len(indices), frameon=False, fontsize=8.5)


def distribution(title, labels, runs, detail, out, board):
    fig, axes = plt.subplots(1, 2, figsize=(11.7, 4.8), sharey=True)
    fig.subplots_adjust(left=0.075, right=0.97, bottom=0.21, top=0.75, wspace=0.16)
    header(fig, f"{title} read latency distributions", detail)
    shifts = [compare(runs[0], run)[0] for run in runs]
    right = max(max(run) + max(shift, 0) for run, shift in zip(runs, shifts)) + 4
    for ax, align in zip(axes, (False, True)):
        for idx, (run, shift) in enumerate(zip(runs, shifts)):
            values = [v + shift for v in run] if align else run
            points = sorted({0, right, *values})
            ax.step(points, [bisect_right(values, x) / len(values) for x in points], where="post",
                    color=COLORS[idx], linestyle=STYLES[idx], linewidth=2)
        ax.set_title("Median-aligned latencies" if align else "Measured and simulated latencies", loc="left")
        ax.set(xlim=(min(runs[0]) - 5 if align else 0, right), ylim=(0, 1.02),
               xlabel="Read latency (100 MHz cycles)")
        ax.yaxis.set_major_formatter(PercentFormatter(1))
        styled_grid(ax)
    axes[0].set_ylabel("Reads completed within latency")
    legend(fig, labels, range(len(labels)))
    save(fig, out, f"{board}-latency-cdf")


def plot_quantiles(title, labels, runs, detail, out, board):
    fig, ax = plt.subplots(figsize=(11, 4.8))
    fig.subplots_adjust(left=0.085, right=0.97, bottom=0.20, top=0.77)
    header(fig, f"{title} read latency quantiles", detail)
    width = 0.76 / len(labels)
    bars = []
    for idx, run in enumerate(runs):
        values = quantiles(run)
        positions = [x + (idx - (len(labels) - 1) / 2) * width for x in range(5)]
        container = ax.bar(positions, values, width=width, color=COLORS[idx])
        ax.bar_label(container, padding=2.5, fontsize=8)
        bars.append(container)
    ax.set(xticks=range(5), xticklabels=("P50", "P90", "P95", "P99", "Maximum"),
           ylim=(0, max(map(max, runs)) * 1.14), ylabel="Read latency (100 MHz cycles)")
    styled_grid(ax)
    legend(fig, labels, range(len(labels)), bars=bars)
    save(fig, out, f"{board}-latency-quantiles")


def warmup(title, labels, by_phase, out, board):
    fig, axes = plt.subplots(1, 3, figsize=(11.7, 4.6))
    fig.subplots_adjust(left=0.08, right=0.97, bottom=0.22, top=0.74, wspace=0.40)
    header(fig, f"{title} latency agreement across warm-ups",
                 "Each simulation trace is shifted to the hardware median")
    metrics = (
        ("Maximum CDF gap", "Percentage points", 1),
        ("P95 residual", "Hardware minus model (cycles)", 2),
        ("P99 residual", "Hardware minus model (cycles)", 3),
    )
    for ax, (name, units, index) in zip(axes, metrics):
        for i in range(1, len(labels)):
            values = [by_phase[phase][i - 1][index] for phase in PHASES]
            ax.plot(PHASES, values, color=COLORS[i], linestyle=STYLES[i],
                    marker=MARKERS[i], linewidth=2, markersize=6)
        ax.axhline(0, color="#BBC5D0", linewidth=0.8)
        ax.set_title(name, loc="left")
        ax.set(xlabel="Warm-up (cycles)", ylabel=units, xticks=PHASES)
        styled_grid(ax)
    legend(fig, labels, range(1, len(labels)), markers=True)
    save(fig, out, f"{board}-warm-up-sensitivity")


def overview(summaries, out):
    fig, axes = plt.subplots(2, 2, figsize=(11.4, 7.4), sharex=True, sharey=True)
    fig.subplots_adjust(left=0.12, right=0.96, bottom=0.12, top=0.79, wspace=0.25, hspace=0.31)
    header(fig, "Effect of Ramulator 2.1 on Alveo latency agreement",
                 "Matched data rates · Change in median-aligned CDF gap · Positive values mean worse agreement")
    changes_by_board = {
        board: [by_phase[p][1][1] - by_phase[p][0][1] for p in PHASES]
        for board, by_phase in summaries.items()
    }
    all_changes = [change for changes in changes_by_board.values() for change in changes]
    ymin, ymax = min(0, *all_changes) - 1.3, max(0, *all_changes) + 1.3
    for ax, (board, changes) in zip(axes.flat, changes_by_board.items()):
        ax.axhline(0, color="#828B98", linewidth=1)
        ax.plot(PHASES, changes, color=COLORS[2], marker="o", linewidth=2, markersize=5)
        for phase, delta in zip(PHASES, changes):
            offset = 8 if delta >= 0 else -13
            ax.annotate(f"{delta:+.2f}", (phase, delta), xytext=(0, offset), textcoords="offset points",
                        ha="center", fontsize=8, color="#303842")
        ax.set_title(BOARDS[board][0], loc="left")
        ax.set(xticks=PHASES, ylim=(ymin, ymax))
        ax.margins(x=0.12)
        styled_grid(ax)
    fig.supxlabel("Warm-up (cycles)", y=0.035, color="#303842")
    fig.supylabel("Change in maximum CDF gap (percentage points)", x=0.035, y=0.46, color="#303842")
    save(fig, out, "alveo-model-agreement")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=HERE / "figures")
    out = parser.parse_args().output
    out.mkdir(parents=True, exist_ok=True)
    campaigns = {}
    rows = []
    replicate_rows = []
    for board, (title, files, baseline, rate, *variants) in BOARDS.items():
        captures = {file: read_latencies(EVIDENCE / file) for file in files}
        hardware = sorted(v for capture in captures.values() for v in capture)
        labels = [f"{title.split()[0]} hardware", f"Ramulator 2.0 · {rate}", *(v[1] for v in variants)]
        rows.append((board, "hardware", "-", len(hardware), *quantiles(hardware), "-", "-", "-", "-"))
        for file, capture in captures.items():
            replicate_rows.append((board, file, len(capture), *quantiles(capture)))
        by_phase = campaigns[board] = {}
        for phase in PHASES:
            simulations = [read_latencies(path) for path in simulation_paths(board, baseline, variants, phase)]
            by_phase[phase] = [compare(hardware, run) for run in simulations]
            for label, run, (shift, gap, p95, p99) in zip(labels[1:], simulations, by_phase[phase]):
                rows.append((board, label, phase, len(run), *quantiles(run), shift, f"{gap:.3f}", p95, p99))
            if phase == 292:
                detail = (f"Warm-up 292 cycles · {len(hardware):,} hardware reads from {len(captures)} capture(s) · 1,000 reads per simulation")
                distribution(title, labels, [hardware, *simulations], detail, out, board)
                plot_quantiles(title, labels, [hardware, *simulations], detail, out, board)
        warmup(title, labels, by_phase, out, board)
    overview(campaigns, out)

    reports = (
        ("comparison.tsv", ("board", "series", "warmup_cycles", "reads", "p50", "p90",
                            "p95", "p99", "max", "median_shift_cycles", "max_cdf_gap_pp",
                            "residual_p95_cycles", "residual_p99_cycles"), rows),
        ("hardware-replicates.tsv", ("board", "file", "reads", "p50", "p90", "p95", "p99", "max"),
         replicate_rows),
    )
    for name, header, data in reports:
        with (out.parent / name).open("w", newline="") as stream:
            writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
            writer.writerow(header)
            writer.writerows(data)


if __name__ == "__main__":
    main()
