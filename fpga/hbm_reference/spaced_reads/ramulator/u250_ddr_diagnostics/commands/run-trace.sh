#!/usr/bin/env bash
set -euo pipefail
src=$(cd -- "$(dirname -- "$0")" && pwd)
work="$HOME/hbm-u280-ramulator.Y4brzt"
exe="$HOME/u280-ddr-sim.sqrjcm/spaced-ramulator.tGg3Pa/obj_dir/Vfpga_kernel"
baseline="$HOME/u250-ddr-ramulator.uBjlm3"
out=$(mktemp -d "$HOME/u250-ddr-command-diagnostic.XXXXXX")
printf 'Diagnostic output: %s\n' "$out"
test -x "$exe"
git -C "$work/ramulator2" rev-parse HEAD > "$out/ramulator-revision.txt"
git -C "$work/ramulator2" diff > "$out/existing-source.diff"
cmake -S "$work/ramulator2" -B "$out/build" \
  -DCMAKE_CXX_COMPILER=/usr/bin/g++-13 -DCMAKE_BUILD_TYPE=RelWithDebInfo \
  '-DCMAKE_CXX_FLAGS_RELWITHDEBINFO=-O0 -g -DNDEBUG' \
  "-DFETCHCONTENT_SOURCE_DIR_YAML-CPP=$work/build/_deps/yaml-cpp-src" \
  "-DFETCHCONTENT_SOURCE_DIR_ARGPARSE=$work/build/_deps/argparse-src" \
  > "$out/configure.log" 2>&1 || { tail -50 "$out/configure.log"; exit 1; }
cmake --build "$out/build" --target ramulator --parallel 4 > "$out/build.log" 2>&1 ||
  { tail -50 "$out/build.log"; exit 1; }
library=$(find "$out/build" -name libramulator.so -print -quit)
test -n "$library"
library_dir=$(dirname "$library")
export LD_LIBRARY_PATH="$library_dir${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
ldd "$exe" > "$out/loaded-libraries.txt"
grep -F "$library" "$out/loaded-libraries.txt"
cp "$src/xci.yaml" "$out/config.yaml"
for phase in 0 97 195 292; do
  dir="$out/phase-$phase"
  mkdir "$dir"
  (cd "$dir" && gdb --batch --return-child-result -x "$src/trace.gdb" \
    --args "$exe" "$out/config.yaml" "$phase") > "$dir/gdb.log" 2>&1 ||
    { tail -50 "$dir/gdb.log"; exit 1; }
  grep '^PASS 1000 AXI reads' "$dir/gdb.log"
  cmp "$baseline/phase-$phase/latencies.csv" "$dir/latencies.csv"
done
python3 "$src/analyze.py" "$out" | tee "$out/command-summary.tsv"
printf 'DIAGNOSTIC_RESULTS: %s\n' "$out"
