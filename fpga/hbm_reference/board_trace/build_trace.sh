#!/usr/bin/env bash
# Package and link the traced copy with the same U55C platform and memory mapping.
set -eo pipefail

src=$(cd -- "$(dirname -- "$0")" && pwd)
routed_override=""
if [[ "${1:-}" == --finish ]]; then
  if (( $# < 2 || $# > 4 )); then
    echo 'Usage: build_trace.sh --finish BUILD_DIRECTORY [REPO [ROUTED_DCP]]' >&2
    exit 2
  fi
  work=$(cd -- "$2" && pwd)
  repo="${3:-$HOME/thesis/ramulator-examples}"
  routed_override="${4:-}"
else
  repo="${1:-$HOME/thesis/ramulator-examples}"
fi
repo=$(cd -- "$repo" && pwd)
baseline="$repo/.fpga/bitstream-xfTkobFQ/probe-single"
original_link="$baseline/hw-0UQ0baFI"
platform="${FPGA_PLATFORM_XCU55C:-/opt/xilinx/platforms/xilinx_u55c_gen3x16_xdma_3_202210_1/xilinx_u55c_gen3x16_xdma_3_202210_1.xpfm}"
vivado_root="${FPGA_TRACE_VIVADO_ROOT:-/opt/Xilinx/Vivado/2024.2}"
vitis_root="${FPGA_TRACE_VITIS_ROOT:-/opt/Xilinx/Vitis/2024.2}"
xclbinutil="${FPGA_XCLBINUTIL:-/opt/xilinx/xrt/bin/xclbinutil}"

test -x "$xclbinutil"
test -f "$original_link/fpga_kernel.xclbin"
grep -Fxq 'sp=fpga_kernel_1.m_axi_0:HBM[0]' "$original_link/connectivity.cfg"
if [[ "${1:-}" != --finish ]]; then
  test -f "$platform"
  work=$(mktemp -d "$repo/.fpga/probe-board-trace.XXXXXX")
fi
prepared="$work/prepared"
link="$work/link"
printf 'Trace build: %s\n' "$work"

if [[ "${1:-}" != --finish ]]; then
  python3 -B "$src/prepare_trace.py" --repo "$repo" prepare \
    --prepared "$baseline" --baseline "$original_link/fpga_kernel.xclbin" \
    --output "$prepared"

  (
    source "$vivado_root/settings64.sh"
    cd "$prepared"
    "$vivado_root/bin/vivado" -mode batch -source "$repo/fpga/tcl/package.tcl" \
      -tclargs "$prepared" xcu55c-fsvh2892-2L-e 10 8
  ) 2>&1 | tee "$work/package.log"

  PYTHONPATH="$repo" python3 -B - "$prepared/fpga_kernel.xo" <<'PY_CHECK'
import sys
from fpga.run import kernel_metadata
kernel_metadata(sys.argv[1], ["m_axi_0"])
PY_CHECK

  mkdir "$link"
  cp "$original_link/connectivity.cfg" "$link/"
  (
    source "$vitis_root/settings64.sh"
    cd "$link"
    "$vitis_root/bin/v++" --link --target hw --platform "$platform" \
      --config "$link/connectivity.cfg" --kernel_frequency 100 --optimize 0 \
      --save-temps --temp_dir "$link/temp" --log_dir "$link/logs" \
      --report_dir "$link/reports" -o "$link/fpga_kernel.xclbin" "$prepared/fpga_kernel.xo"
  ) 2>&1 | tee "$link/link.log"
fi
test -s "$link/fpga_kernel.xclbin"

# Vitis keeps routed implementation checkpoints under the implementation run.
if [[ -n "$routed_override" ]]; then
  test -f "$routed_override"
  routed=("$(cd -- "$(dirname -- "$routed_override")" && pwd)/$(basename -- "$routed_override")")
else
  mapfile -t routed < <(find "$link/temp" -type f -path '*/impl_*/*' -name '*routed.dcp' | sort)
fi
if ((${#routed[@]} != 1)); then
  printf 'Expected one routed implementation checkpoint under %s/temp.\n' "$link" >&2
  find "$link/temp" -name '*.dcp' -print >&2
  exit 1
fi
timing=$(mktemp -d "$link/timing.XXXXXX")
(
  source "$vivado_root/settings64.sh"
  cd "$timing"
  "$vivado_root/bin/vivado" -mode batch -source "$repo/fpga/tcl/check_implementation.tcl" \
    -tclargs "${routed[0]}" "$timing"
) 2>&1 | tee "$timing/check.log"

"$xclbinutil" --info --input "$link/fpga_kernel.xclbin" > "$link/xclbin-info.txt"
python3 -B "$src/prepare_trace.py" --repo "$repo" bundle --prepared "$prepared" \
  --linked "$link" --timing "$timing" --baseline "$original_link/fpga_kernel.xclbin" \
  --xclbinutil "$xclbinutil" --output "$work/${work##*/}.tar.gz"
