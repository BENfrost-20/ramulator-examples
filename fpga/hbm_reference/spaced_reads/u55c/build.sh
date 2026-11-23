#!/usr/bin/env bash
set -eo pipefail
cd -- "$(dirname -- "$0")"
src=$PWD
vivado=${FPGA_TRACE_VIVADO_ROOT:-/opt/Xilinx/Vivado/2024.2}
vitis=${FPGA_TRACE_VITIS_ROOT:-/opt/Xilinx/Vitis/2024.2}
platform=${FPGA_PLATFORM_XCU55C:-/opt/xilinx/platforms/xilinx_u55c_gen3x16_xdma_3_202210_1/xilinx_u55c_gen3x16_xdma_3_202210_1.xpfm}
xclbinutil=${FPGA_XCLBINUTIL:-/opt/xilinx/xrt/bin/xclbinutil}
test -r "$platform"
work=$(mktemp -d "$src/build.XXXXXX")
printf 'Build directory: %s\n' "$work"
printf 'set rtl_files [list {%s/fpga_kernel.sv} {%s/control.sv}]\n' "$src" "$src" > "$work/sources.tcl"
cp registers.tcl "$work/"
(
  source "$vivado/settings64.sh"
  cd "$work"
  "$vivado/bin/vivado" -mode batch -source "$src/package.tcl" -tclargs "$work" xcu55c-fsvh2892-2L-e 10 8
) 2>&1 | tee "$work/package.log"
(
  source "$vitis/settings64.sh"
  cd "$work"
  "$vitis/bin/v++" --link --target hw --platform "$platform" --config "$src/connectivity.cfg" \
    --kernel_frequency 100 --optimize 0 --save-temps --temp_dir "$work/temp" \
    --log_dir "$work/logs" -o "$work/fpga_kernel.xclbin" "$work/fpga_kernel.xo"
) 2>&1 | tee "$work/link.log"
mapfile -t routed < <(find "$work/temp" -type f -path '*/impl_*/*' -name '*routed.dcp' | sort)
[[ ${#routed[@]} -eq 1 ]] || { echo 'Expected one routed checkpoint'; exit 1; }
mkdir "$work/timing"
(
  source "$vivado/settings64.sh"
  cd "$work/timing"
  "$vivado/bin/vivado" -mode batch -source "$src/check_implementation.tcl" -tclargs "${routed[0]}" "$work/timing"
) 2>&1 | tee "$work/timing/check.log"
"$xclbinutil" --input "$work/fpga_kernel.xclbin" --info > "$work/xclbin-info.txt"
grep -Eiq 'UUID \(IINTF\):[[:space:]]+b7ac1abe1e3e1cb686d5a81232452676' "$work/xclbin-info.txt"
python3 -B - "$work/xclbin-info.txt" <<'PY'
import re
import sys
from pathlib import Path

info = Path(sys.argv[1]).read_text()
for clock, frequency in (("DATA_CLK", 100), ("hbm_aclk", 450)):
    pattern = rf"Name:\s+{clock}\s+Index:\s+\d+\s+Type:\s+\w+\s+Frequency:\s+{frequency} MHz"
    if not re.search(pattern, info):
        raise SystemExit(f"Unexpected linked frequency for {clock}")
PY
cp host.cpp host-build.py host-flags.json connectivity.cfg "$work/"
(
  cd "$work"
  sha256sum fpga_kernel.xclbin host.cpp host-build.py host-flags.json connectivity.cfg xclbin-info.txt > SHA256SUMS
  tar -czf "$work/hbm-spaced-hacc.tar.gz" fpga_kernel.xclbin host.cpp host-build.py host-flags.json connectivity.cfg xclbin-info.txt SHA256SUMS timing
)
printf 'HACC_BUNDLE: %s\n' "$work/hbm-spaced-hacc.tar.gz"
