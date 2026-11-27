#!/usr/bin/env bash
# Run the one-word native Bambu probe in a fresh Ferrandi directory.
set -eo pipefail

options=()
prefix=probe-bambu
ramulator_config=
case "$#" in
  0) ;;
  1)
    if [[ "$1" =~ ^([2-9]|[1-9][0-9]+)$ ]]; then
      options=("--mem-delay-read=$1" "--mem-delay-write=$1")
      prefix="probe-bambu-fixed$1"
    else
      echo 'Memory delay must be an integer of at least two cycles.' >&2
      exit 2
    fi
    ;;
  2)
    if [[ "$1" != --ramulator-config || ! -f "$2" || ! -r "$2" ]]; then
      echo 'Expected --ramulator-config and a readable YAML file.' >&2
      exit 2
    fi
    ramulator_config=$(realpath -- "$2")
    options=(--enable-ramulator)
    prefix=probe-bambu-ramulator
    ;;
  *)
    echo 'Usage: bash run_bambu_native.sh [CYCLES | --ramulator-config FILE]' >&2
    exit 2
    ;;
esac

repo=$(cd -- "$(dirname -- "$0")/../.." && pwd)
toolchain="$HOME/thesis/toolchain-ramulator21-dca0351"
bambu="${FPGA_BAMBU:-$toolchain/bambu-install/bin/bambu}"
settings="${FPGA_BAMBU_SETTINGS:-$toolchain/bambu-install/settings.sh}"
clang_bin="${FPGA_CLANG_BIN:-$HOME/thesis/toolchains/clang-13/bin}"
verilator="${FPGA_VERILATOR:-/opt/verilator/verilator-5.030/bin/verilator}"
mkdir -p "$repo/.fpga"
run=$(mktemp -d "$repo/.fpga/$prefix.XXXXXX")
printf 'Bambu run: %s\n' "$run"

cp "$repo/fpga/calibration/memory_probe.c" "$run/"
cd "$run"
cat > probe_kernel.c <<'C_SRC'
#define main calibration_standalone_main
#include "memory_probe.c"
#undef main
C_SRC
printf '%s\n' '<function><testbench data="{3}" n="1"/></function>' > input.xml
source "$settings"
export PATH="$clang_bin:$(dirname -- "$verilator"):$PATH"
export CCACHE_DISABLE=1
unset RAMULATOR2_CONFIG RAMULATOR_OVERRIDE_CHANNELS VERILATOR_ROOT BAMBU_IPC_SIM_CMD OUT_LVL
if [[ -n "$ramulator_config" ]]; then
  cp "$ramulator_config" ramulator-config.yaml
  export RAMULATOR2_CONFIG="$PWD/ramulator-config.yaml"
  export RAMULATOR2_DIR="${RAMULATOR2_DIR:-$toolchain/ramulator-install}"
  export RAMULATOR_OVERRIDE_CHANNELS=0
  sha256sum ramulator-config.yaml
fi

if ! "$bambu" "$PWD/probe_kernel.c" \
  --top-fname=memory_probe --compiler=I386_CLANG13 -m64 -O2 \
  --device-name=xcu55c-2Lfsvh2892 --clock-period=10 \
  --generate-interface=INFER --memory-allocation-policy=NO_BRAM \
  --channels-type=MEM_ACC_11 --channels-number=1 --base-address=1073741824 \
  --generate-tb="$PWD/input.xml" --tb-param-size=data:4 \
  "${options[@]}" \
  --simulate --simulator=VERILATOR --max-sim-cycles=1000000 \
  --output-directory=output-clang13 -v5 >cosimulation.log 2>&1; then
  tail -60 cosimulation.log
  exit 1
fi

cat input.xml
grep -m 1 'Bambu executed with' cosimulation.log
grep -E 'Total cycles|Average execution' cosimulation.log
if [[ -n "$ramulator_config" ]]; then
  grep -E 'Memory clock:|\[MDPI-(MEMORY|PROFILE)\]' cosimulation.log
elif [[ $# -eq 1 ]]; then
  grep -En 'TestbenchMEMAXI #|\.(READ|WRITE)_DELAY\((READ|WRITE)_DELAY \?' \
    output-clang13/HLS_output/simulation/bambu_testbench.v
fi
printf 'Bambu report: %s/output-clang13/bambu_results.xml\n' "$run"
printf 'Bambu log: %s/cosimulation.log\n' "$run"
