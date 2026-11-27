"""Regenerate the English U55C latency figures and validate the archived summaries."""
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
PHASES = (0, 97, 195, 292)
NAMES = (
    "U55C hardware",
    "Ramulator 2.0 · 1800 MT/s",
    "Ramulator 2.1 · 1800 MT/s",
    "Ramulator 2.1 · 2000 MT/s",
)
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


def compare(reference, values):
    ref_q, q = quantiles(reference), quantiles(values)
    shift = ref_q[0] - q[0]
    aligned = [value + shift for value in values]
    gap = max(abs(bisect_right(reference, x) - bisect_right(aligned, x))
              for x in set(reference) | set(aligned))
    return q, shift, ref_q[2] - (q[2] + shift), ref_q[3] - (q[3] + shift), gap / 10


def load_runs():
    hardware = read_latencies(HERE.parent / "spaced_reads_u55c_08.csv")
    runs = {phase: [hardware] for phase in PHASES}
    profiles = (
        ("ramulator-2.0", "comparison.tsv"),
        ("ramulator-2.1/matched-rate-1800", "../comparison-matched-rate-1800.tsv"),
        ("ramulator-2.1/bambu-2000", "../comparison-bambu-2000.tsv"),
    )
    for directory, summary in profiles:
        directory = HERE / directory
        with (directory / summary).open() as stream:
            recorded = {row["run"]: row for row in csv.DictReader(stream, delimiter="\t")}
        for phase in PHASES:
            key = f"phase-{phase}"
            path = directory / key / "latencies.csv"
            if phase == 292 and directory.name == "ramulator-2.0":
                path = HERE.parent / "spaced_reads_u55c_ramulator_phase292.csv"
            values = read_latencies(path)
            q, shift, p95, p99, gap = compare(hardware, values)
            actual = [*q, shift, p95, p99, gap]
            fields = ("p50", "p90", "p95", "p99", "max", "shift_HW_minus_sim",
                      "residual_p95", "residual_p99", "max_cdf_gap_pp")
            expected = [float(recorded[key][name]) for name in fields]
            if actual != expected:
                raise ValueError(f"Recorded summary differs from recomputation for {path}")
            runs[phase].append(values)
    return runs


def save(fig, out, filename):
    fig.savefig(out / f"{filename}.png", dpi=180, facecolor="white")
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


def comparison_legend(fig, start=0, include_markers=False):
    handles = [Line2D([], [], color=COLORS[i], linestyle=STYLES[i], linewidth=2.2,
                      marker=MARKERS[i] if include_markers else None)
               for i in range(start, len(NAMES))]
    fig.legend(handles, NAMES[start:], loc="lower center", bbox_to_anchor=(0.5, 0.023),
               ncol=len(handles), frameon=False, fontsize=9, handlelength=2.8)


def plot_distribution(runs, out):
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.8), sharey=True)
    fig.subplots_adjust(left=0.075, right=0.97, bottom=0.21, top=0.75, wspace=0.16)
    header(fig, "U55C HBM2 read latency distributions",
           "Warm-up phase 292 · 1,000 reads per trace · AXI address handshake to data response")
    median = quantiles(runs[0])[0]
    for ax, align in zip(axes, (False, True)):
        for i, values in enumerate(runs):
            shift = median - quantiles(values)[0] if align else 0
            values = [value + shift for value in values]
            support = sorted({0, *values, 70})
            ax.step(support, [bisect_right(values, x) / len(values) for x in support], where="post",
                    color=COLORS[i], linestyle=STYLES[i], linewidth=2)
        ax.set_title("Median-aligned latencies" if align else "Measured and simulated latencies", loc="left")
        ax.set(xlim=(20 if align else 0, 70), ylim=(0, 1.02), xlabel="Read latency (100 MHz cycles)")
        ax.yaxis.set_major_formatter(PercentFormatter(1))
        styled_grid(ax)
    axes[0].set_ylabel("Reads completed within latency")
    comparison_legend(fig)
    save(fig, out, "u55c-latency-cdf")


def plot_quantiles(runs, out):
    fig, ax = plt.subplots(figsize=(10.5, 4.8))
    fig.subplots_adjust(left=0.095, right=0.97, bottom=0.20, top=0.77)
    header(fig, "U55C HBM2 read latency quantiles",
           "Warm-up phase 292 · 1,000 reads per trace · Original latencies")
    width = 0.18
    for i, values in enumerate(runs):
        bars = ax.bar([x + (i - 1.5) * width for x in range(5)], quantiles(values), width=width,
                      color=COLORS[i], label=NAMES[i])
        ax.bar_label(bars, padding=2.5, fontsize=8)
    ax.set(xticks=range(5), xticklabels=("P50", "P90", "P95", "P99", "Maximum"),
           ylim=(0, 74), ylabel="Read latency (100 MHz cycles)")
    styled_grid(ax)
    fig.legend(loc="lower center", bbox_to_anchor=(0.5, 0.023), ncol=4, frameon=False, fontsize=9)
    save(fig, out, "u55c-latency-quantiles")


def plot_phase_sensitivity(runs, out):
    fig, axes = plt.subplots(1, 3, figsize=(11.5, 4.6))
    fig.subplots_adjust(left=0.075, right=0.97, bottom=0.22, top=0.74, wspace=0.38)
    header(fig, "U55C latency agreement across warm-up phases",
           "Each simulation trace is shifted to the hardware median before computing errors")
    metrics = (
        ("Maximum CDF gap", "Percentage points", 4, (0, 12)),
        ("P95 residual", "Hardware minus model (cycles)", 2, (-0.35, 6.6)),
        ("P99 residual", "Hardware minus model (cycles)", 3, (-0.15, 1.22)),
    )
    for ax, (title, units, index, limits) in zip(axes, metrics):
        for i in range(1, len(NAMES)):
            values = [compare(runs[phase][0], runs[phase][i])[index] for phase in PHASES]
            ax.plot(PHASES, values, color=COLORS[i], linestyle=STYLES[i],
                    marker=MARKERS[i], linewidth=2, markersize=6)
        ax.set_title(title, loc="left")
        ax.set(xlabel="Warm-up (cycles)", ylabel=units, xticks=PHASES, ylim=limits)
        styled_grid(ax)
    axes[2].set_yticks([0, 1])
    comparison_legend(fig, start=1, include_markers=True)
    save(fig, out, "u55c-warm-up-sensitivity")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=HERE / "figures")
    out = parser.parse_args().output
    out.mkdir(parents=True, exist_ok=True)
    runs = load_runs()
    plot_distribution(runs[292], out)
    plot_quantiles(runs[292], out)
    plot_phase_sensitivity(runs, out)


if __name__ == "__main__":
    main()
