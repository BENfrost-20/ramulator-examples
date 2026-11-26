#!/usr/bin/env bash
set -euo pipefail
src=$(cd -- "$(dirname -- "$0")" && pwd)
evidence="$src/../../../../evidence"
exe="$HOME/u280-ddr-sim.sqrjcm/spaced-ramulator.tGg3Pa/obj_dir/Vfpga_kernel"
test -x "$exe" || { echo "Simulator missing: $exe" >&2; exit 1; }
out=$(mktemp -d "$HOME/u250-ddr-peak-diagnostic.XXXXXX")
printf 'Diagnostic output: %s\n' "$out"
mkdir "$out/hardware"
for i in 1 2 3; do
  cp "$evidence/spaced_reads_u250_ddr_legacy02_run${i}_20261125.csv" "$out/hardware/reads-$i.csv"
done
for profile in xci refresh-2x-diagnostic refresh-4x-diagnostic; do
  dest="$out/$profile"
  mkdir "$dest"
  cp "$src/$profile.yaml" "$dest/config.yaml"
  sha256sum "$dest/config.yaml" "$exe" > "$dest/inputs.sha256"
  for phase in 0 97 195 292; do
    phase_dir="$dest/phase-$phase"
    mkdir "$phase_dir"
    (cd "$phase_dir" && "$exe" "$dest/config.yaml" "$phase") 2>&1 | tee "$phase_dir/run.log"
    grep -q '^PASS 1000 AXI reads' "$phase_dir/run.log"
  done
done
python3 "$src/summarize.py" "$out" | tee "$out/diagnostic-summary.tsv"
printf 'DIAGNOSTIC_RESULTS: %s\n' "$out"
