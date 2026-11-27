#!/usr/bin/env bash
set -euo pipefail
src=$(cd -- "$(dirname -- "$0")" && pwd)
evidence="$src/../../../../evidence"
campaign="$HOME/thesis/ramulator-examples/.fpga/u280-source.D5TZxl/.fpga/spaced-u280-hbm.0Qo0j9/campaign-2022.2"
build="$campaign/runs/u250-ddr"
attempt=link-fixed100-20261125-123114
project="$build/$attempt/temp/link/vivado/vpl/prj"
exe="$HOME/u280-ddr-sim.sqrjcm/spaced-ramulator.tGg3Pa/obj_dir/Vfpga_kernel"
test -x "$exe"
test -d "$project"
(cd "$build" && sha256sum -c "$src/xclbin.sha256")
grep -Fq -- '--clock.id 4:fpga_kernel_1.ap_clk' "$build/xclbin-info.txt"
grep -Fqx 'sp=fpga_kernel_1.m_axi_0:DDR[0]' "$build/connectivity.cfg"
out=$(mktemp -d "$HOME/u250-ddr-ramulator.XXXXXX")
printf 'Results: %s\n' "$out"
python3 "$src/profile.py" "$project" "$out/config.yaml" | tee "$out/profile.log"
cp "$src/xclbin.sha256" "$out/"
sha256sum "$out/config.yaml" "$exe" > "$out/simulation-inputs.sha256"
for phase in 0 97 195 292; do
  mkdir "$out/phase-$phase"
  (cd "$out/phase-$phase" && "$exe" "$out/config.yaml" "$phase") 2>&1 | tee "$out/phase-$phase/run.log"
  grep -q '^PASS 1000 AXI reads' "$out/phase-$phase/run.log"
done
for hw in "$evidence"/spaced_reads_u250_ddr_legacy02_run{1,2,3}_20261125.csv; do
  basename "$hw"
  python3 "$src/../../compare.py" "$hw" "$out"
done | tee "$out/comparison.tsv"
printf 'RESULTS: %s\n' "$out"
