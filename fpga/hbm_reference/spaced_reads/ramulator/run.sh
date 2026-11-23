#!/usr/bin/env bash
set -euo pipefail
src=$(cd -- "$(dirname -- "$0")" && pwd)
: "${RAMULATOR2_DIR:?Set RAMULATOR2_DIR to the Ferrandi Ramulator install}"
verilator=${FPGA_VERILATOR:-verilator}
cxx=${FPGA_VERILATOR_CXX:-g++}
lib=$(find "$RAMULATOR2_DIR/lib" "$RAMULATOR2_DIR/lib64" -name libramulator.so -print -quit 2>/dev/null || true)
test -f "$lib" || { echo 'Cannot find libramulator.so'; exit 1; }
test -f "$RAMULATOR2_DIR/include/ramulator/base/config.h"
out=$(mktemp -d "$PWD/spaced-ramulator.XXXXXX")
printf 'Results directory: %s\n' "$out"
cp "$src/hbm2_u55c_1800.yaml" "$out/"
sha256sum "$lib" "$src/fpga_kernel.sv" "$src/control.sv" "$out/hbm2_u55c_1800.yaml" > "$out/inputs.sha256"
"$verilator" --cc --exe --build -j "${J:-1}" --Mdir "$out/obj_dir" --top-module fpga_kernel -Wno-fatal \
  -MAKEFLAGS "CXX=$cxx LINK=$cxx" \
  -CFLAGS "-std=c++20 -DFPGA_WITH_RAMULATOR -I$src -I$RAMULATOR2_DIR/include/ramulator -I$RAMULATOR2_DIR/include" \
  -LDFLAGS "-L$(dirname "$lib") -Wl,-rpath,$(dirname "$lib") -Wl,--no-as-needed -lramulator -Wl,--as-needed" \
  "$src/fpga_kernel.sv" "$src/control.sv" "$src/bench.cpp" 2>&1 | tee "$out/build.log"
for phase in 0 97 195 292; do
  mkdir "$out/phase-$phase"
  (cd "$out/phase-$phase" && "$out/obj_dir/Vfpga_kernel" "$out/hbm2_u55c_1800.yaml" "$phase") \
    2>&1 | tee "$out/phase-$phase/run.log"
done
python3 "$src/compare.py" "$src/hardware.csv" "$out" | tee "$out/comparison.tsv"
printf 'RESULTS: %s\n' "$out"
