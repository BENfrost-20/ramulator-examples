#!/usr/bin/env bash
set -eo pipefail
cd -- "$(dirname -- "$0")"
src=$PWD
board=${1:-u55c}
if (( $# > 1 )) || [[ "$board" != u55c && "$board" != u280 ]]; then
  echo 'Usage: build.sh [u55c|u280]' >&2
  exit 2
fi
if [[ "$board" == u280 ]]; then
  release=2022.2
  part=xcu280-fsvh2892-2L-e
  platform=${FPGA_PLATFORM_XCU280:-xilinx_u280_gen3x16_xdma_1_202211_1}
  interface=fb2b2c5a19ed63593fea95f51fbc8eb9
  build_root=$(cd "$src/../../../.." && pwd)/.fpga
  build_prefix=spaced-u280-hbm
  bundle=hbm-spaced-u280-hacc.tar.gz
else
  release=2024.2
  part=xcu55c-fsvh2892-2L-e
  platform=${FPGA_PLATFORM_XCU55C:-/opt/xilinx/platforms/xilinx_u55c_gen3x16_xdma_3_202210_1/xilinx_u55c_gen3x16_xdma_3_202210_1.xpfm}
  interface=b7ac1abe1e3e1cb686d5a81232452676
  build_root=$src
  build_prefix=build
  bundle=hbm-spaced-hacc.tar.gz
fi
vivado=${FPGA_TRACE_VIVADO_ROOT:-/opt/Xilinx/Vivado/$release}
vitis=${FPGA_TRACE_VITIS_ROOT:-/opt/Xilinx/Vitis/$release}
xclbinutil=${FPGA_XCLBINUTIL:-/opt/xilinx/xrt/bin/xclbinutil}
mkdir -p "$build_root"
work=$(mktemp -d "$build_root/$build_prefix.XXXXXX")
printf 'Build directory: %s\n' "$work"
(
  source "$vitis/settings64.sh"
  cd "$work"
  platforminfo --platform "$platform"
) 2>&1 | tee "$work/platforminfo.txt"
printf 'set rtl_files [list {%s/fpga_kernel.sv} {%s/control.sv}]\n' "$src" "$src" > "$work/sources.tcl"
cp registers.tcl "$work/"
(
  source "$vivado/settings64.sh"
  cd "$work"
  "$vivado/bin/vivado" -mode batch -source "$src/package.tcl" -tclargs "$work" "$part" 10 8 "$release"
) 2>&1 | tee "$work/package.log"
(
  source "$vitis/settings64.sh"
  cd "$work"
  "$vitis/bin/v++" --link --target hw --platform "$platform" --config "$src/connectivity.cfg" \
    --kernel_frequency 100 --optimize 0 --save-temps --temp_dir "$work/temp" \
    --log_dir "$work/logs" -o "$work/fpga_kernel.xclbin" "$work/fpga_kernel.xo"
) 2>&1 | tee "$work/link.log"
routed=()
while IFS= read -r checkpoint; do
  routed+=("$checkpoint")
done < <(find "$work/temp" -type f -path '*/impl_*/*' -name '*routed.dcp' | sort)
[[ ${#routed[@]} -eq 1 ]] || { echo 'Expected one routed checkpoint'; exit 1; }
mkdir "$work/timing"
(
  source "$vivado/settings64.sh"
  cd "$work/timing"
  "$vivado/bin/vivado" -mode batch -source "$src/check_implementation.tcl" -tclargs "${routed[0]}" "$work/timing"
) 2>&1 | tee "$work/timing/check.log"
"$xclbinutil" --input "$work/fpga_kernel.xclbin" --info > "$work/xclbin-info.txt"
grep -Eiq "UUID \(IINTF\):[[:space:]]+$interface([[:space:]]|$)" "$work/xclbin-info.txt" || {
  echo "Unexpected interface UUID for $board; see $work/xclbin-info.txt" >&2
  exit 1
}
python3 -B - "$work/xclbin-info.txt" "$board" <<'PY'
import re
import sys
from pathlib import Path

info = Path(sys.argv[1]).read_text()
clocks = [("DATA_CLK", 100)]
if sys.argv[2] == "u55c":
    clocks.append(("hbm_aclk", 450))
for clock, frequency in clocks:
    pattern = rf"Name:\s+{clock}\s+Index:\s+\d+\s+Type:\s+\w+\s+Frequency:\s+{frequency} MHz"
    if not re.search(pattern, info):
        raise SystemExit(f"Unexpected linked frequency for {clock}")
PY
cp host.cpp host-build.py host-flags.json connectivity.cfg "$work/"
sha256sum fpga_kernel.sv control.sv > "$work/rtl-sha256.txt"
(
  cd "$work"
  files=(fpga_kernel.xclbin host.cpp host-build.py host-flags.json
         connectivity.cfg xclbin-info.txt platforminfo.txt rtl-sha256.txt)
  sha256sum "${files[@]}" > SHA256SUMS
  tar -czf "$bundle" "${files[@]}" SHA256SUMS timing
)
printf 'HACC_BUNDLE: %s\n' "$work/$bundle"
