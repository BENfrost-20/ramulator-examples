#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "$0")" && pwd)
src="$root/src"
anchor=${1:?Pass the aligned DDR[0] anchor recorded by HACC}
ram=${RAMULATOR2_DIR:-$HOME/hbm-u280-ramulator.Y4brzt/install}
verilator=${FPGA_VERILATOR:-/opt/verilator/verilator-5.030/bin/verilator}
cxx=${FPGA_VERILATOR_CXX:-/usr/bin/g++-13}
lib="$ram/lib/libramulator.so"
test -r "$lib"
out=$(mktemp -d "$PWD/u280-ddr-controller-sim.XXXXXX")
printf 'Results directory: %s\n' "$out"
cp "$src/u280_ddr4_2022_2.yaml" "$out/"
config="$out/u280_ddr4_2022_2.yaml"
sha256sum "$lib" "$config" "$src"/{*.sv,*.hpp,bench.cpp} > "$out/inputs.sha256"
"$verilator" --cc --exe --build -j "${J:-4}" --Mdir "$out/obj_dir" --top-module fpga_kernel -Wno-fatal \
  -MAKEFLAGS "CXX=$cxx LINK=$cxx" \
  -CFLAGS "-std=c++20 -DFPGA_WITH_RAMULATOR -I$src -I$ram/include/ramulator -I$ram/include" \
  -LDFLAGS "-L$ram/lib -Wl,-rpath,$ram/lib -Wl,--no-as-needed -lramulator -Wl,--as-needed" \
  "$src/fpga_kernel.sv" "$src/control.sv" "$src/bench.cpp" 2>&1 | tee "$out/build.log"

names=(same-row same-bank different-bank)
for phase in 0 195 390 585; do
  mkdir "$out/phase-$phase"
  for mode in 0 1 2; do
    name=${names[mode]}
    dir="$out/phase-$phase/$name"
    mkdir "$dir"
    (cd "$dir" && "$out/obj_dir/Vfpga_kernel" "$config" "$phase" "$mode" "$anchor") 2>&1 | tee "$dir/run.log"
    cp "$dir/latencies.csv" "$out/phase-$phase/$name-1.csv"
    grep '^DRAM_CMD,' "$dir/run.log" > "$dir/dram-commands.csv"
    python3 "$root/check-commands.py" "$dir/dram-commands.csv" "$anchor" "$mode" | tee "$dir/commands-summary.txt"
  done
  python3 "$root/summarize.py" "$out/phase-$phase" | tee "$out/phase-$phase/summary.tsv"
done
printf 'RESULTS: %s\n' "$out"
