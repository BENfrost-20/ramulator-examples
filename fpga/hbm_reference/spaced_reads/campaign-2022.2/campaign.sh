#!/usr/bin/env bash
set -eEuo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
src="$root/src"
vivado=/opt/Xilinx/Vivado/2022.2
vitis=/opt/Xilinx/Vitis/2022.2
xclbinutil=/opt/xilinx/xrt/bin/xclbinutil
platform_dir=/opt/xilinx/platforms
u250_name=xilinx_u250_gen3x16_xdma_4_1_202210_1
u250_package=xilinx-u250-gen3x16-xdma-4.1-202210-1-dev_1-3512975_all.deb
session=spaced-2022-2
u280_hbm=$(dirname -- "$root")

fail() { printf '%s\n' "$*" >&2; exit 1; }

start_window() {
  tmux new-window -d -t "$session" -n "$1" bash "$root/campaign.sh" run "$1" "${2:-initial}"
}

case "${1:-}" in
  start)
    command -v tmux >/dev/null || fail 'Missing tmux'
    for tool in "$vivado/bin/vivado" "$vitis/bin/v++" "$xclbinutil"; do
      [[ -x "$tool" ]] || fail "Missing executable: $tool"
    done
    [[ -s "$u280_hbm/fpga_kernel.xo" && -d "$u280_hbm/.ipcache" ]] ||
      fail "Place the campaign directly inside the existing U280 HBM build directory."
    (cd "$src" && sha256sum -c "$u280_hbm/rtl-sha256.txt")
    grep -Fq 'Vivado v2022.2' "$u280_hbm/package.log" ||
      fail 'The reusable U280 XO must come from Vivado 2022.2.'
    grep -Fq 'create_clock -period 10 -name ap_clk' "$u280_hbm/kernel-clock.xdc" ||
      fail 'The reusable U280 XO must have a 10 ns kernel constraint.'
    mkdir -p "$root/runs"
    tmux new-session -d -s "$session" -n status bash -c 'printf "Campaign directory: %s\n" "$1"; exec bash' bash "$root"
    start_window u280-ddr
    start_window u250-ddr
    start_window u55c-hbm
    printf 'Campaign: %s\ntmux attach -t %s\n' "$root" "$session"
    exit
    ;;
  resume-u250)
    [[ -f "$root/runs/u250-ddr/initial.exit" ]] || fail 'Wait for the initial U250 window to finish.'
    [[ $(< "$root/runs/u250-ddr/initial.exit") != 0 ]] || fail 'The U250 bundle already passed.'
    [[ -r "${FPGA_PLATFORM_XCU250:-}" || -r "$HOME/$u250_package" ||
       -r "$platform_dir/$u250_name/$u250_name.xpfm" ]] ||
      fail "Place $u250_package in your home before resuming."
    tmux list-windows -t "$session" -F '#W' | grep -Fxq u250-ddr &&
      fail 'The U250 tmux window is still open.'
    if [[ -f "$root/runs/u250-ddr/last-resume.exit" ]] &&
       [[ $(< "$root/runs/u250-ddr/last-resume.exit") == 0 ]]; then
      fail 'The U250 bundle already passed.'
    fi
    tmux set-environment -t "$session" FPGA_PLATFORM_XCU250 "${FPGA_PLATFORM_XCU250:-}"
    start_window u250-ddr "resume-$(date +%Y%m%d-%H%M%S)"
    exit
    ;;
  run) ;;
  *) fail 'Usage: campaign.sh start | resume-u250' ;;
esac

target=${2:?Missing target}
attempt=${3:?Missing attempt}
work="$root/runs/$target"
mkdir -p "$work"
exec > >(tee -a "$work/$attempt.log") 2>&1
trap 'status=$?; printf "%s\n" "$status" > "$work/$attempt.exit.tmp"; mv "$work/$attempt.exit.tmp" "$work/$attempt.exit"; if [[ "$attempt" == resume-* ]]; then cp "$work/$attempt.exit" "$work/last-resume.exit"; fi; printf "%s %s exit=%s\n" "$target" "$attempt" "$status"' EXIT
trap 'printf "Build failed at line %s: %s\n" "$LINENO" "$BASH_COMMAND" >&2' ERR
printf 'Target %s, attempt %s · %s\n' "$target" "$attempt" "$work"
case "$target" in
  u280-ddr)
    part=xcu280-fsvh2892-2L-e
    platform_name=xilinx_u280_gen3x16_xdma_1_202211_1
    interface=fb2b2c5a19ed63593fea95f51fbc8eb9
    bank='DDR[0]'
    ;;
  u250-ddr)
    part=xcu250-figd2104-2L-e
    platform_name=$u250_name
    interface=807a580e5f507d484d26c2217aa787
    bank='DDR[0]'
    ;;
  u55c-hbm)
    part=xcu55c-fsvh2892-2L-e
    platform_name=xilinx_u55c_gen3x16_xdma_3_202210_1
    interface=b7ac1abe1e3e1cb686d5a81232452676
    bank='HBM[0]'
    printf 'Queued until either the U280 or initial U250 window releases its build slot.\n'
    until [[ -f "$root/runs/u280-ddr/initial.exit" || -f "$root/runs/u250-ddr/initial.exit" ]]; do
      sleep 10
    done
    ;;
  *) fail "Unexpected target: $target" ;;
esac

printf '[connectivity]\nnk=fpga_kernel:1:fpga_kernel_1\nsp=fpga_kernel_1.m_axi_0:%s\n' "$bank" > "$work/connectivity.cfg"
xo="$work/fpga_kernel.xo"
cache=()
if [[ "$target" == u280-ddr ]]; then
  xo="$u280_hbm/fpga_kernel.xo"
  cache=(--remote_ip_cache "$u280_hbm/.ipcache")
  printf 'Reusing the U280 XO and IP cache from %s\n' "$u280_hbm"
elif [[ ! -f "$work/package.ok" ]]; then
  printf 'set rtl_files [list {%s/fpga_kernel.sv} {%s/control.sv}]\n' "$src" "$src" > "$work/sources.tcl"
  cp "$src/registers.tcl" "$work/"
  (
    set +u
    source "$vivado/settings64.sh"
    set -u
    cd "$work"
    "$vivado/bin/vivado" -mode batch -source "$src/package.tcl" -tclargs "$work" "$part" 10 8 2022.2
  ) | tee "$work/package.$attempt.log"
  [[ -s "$work/fpga_kernel.xo" ]] || fail 'Vivado did not produce an XO.'
  touch "$work/package.ok"
fi

platform="$platform_dir/$platform_name/$platform_name.xpfm"
if [[ "$target" == u250-ddr && ! -r "$platform" ]]; then
  platform="${FPGA_PLATFORM_XCU250:-$HOME/.fpga/platforms/u250/opt/xilinx/platforms/$u250_name/$u250_name.xpfm}"
  if [[ ! -r "$platform" && -r "$HOME/$u250_package" ]]; then
    platform_stage="$HOME/.fpga/platforms/u250"
    mkdir -p "$platform_stage"
    dpkg-deb -x "$HOME/$u250_package" "$platform_stage"
    platform=$(find "$platform_stage" -type f -name "$u250_name.xpfm" -print -quit)
  fi
  if [[ ! -r "$platform" ]]; then
    printf 'U250 XO ready at %s/fpga_kernel.xo\n' "$work"
    printf 'Place %s in your home, then run: bash %q resume-u250\n' "$u250_package" "$root/campaign.sh"
    exit 3
  fi
fi
[[ -r "$platform" ]] || fail "Platform not found: $platform"
if [[ "$target" == u250-ddr && "$attempt" == resume-* ]]; then
  if [[ ! -f "$root/runs/u280-ddr/initial.exit" && ! -f "$root/runs/u55c-hbm/initial.exit" ]]; then
    printf 'Queued until a Vitis link slot is available.\n'
    until [[ -f "$root/runs/u280-ddr/initial.exit" || -f "$root/runs/u55c-hbm/initial.exit" ]]; do
      sleep 10
    done
  fi
fi
link="$work/link-$attempt"
mkdir "$link"
(
  set +u
  source "$vitis/settings64.sh"
  set -u
  cd "$link"
  "$vitis/bin/v++" --version
  platforminfo --platform "$platform" > "$work/platforminfo.txt"
  grep -Fq "Bus SP Tag: ${bank%%\[*}" "$work/platforminfo.txt" || fail "Platform does not advertise $bank"
  "$vitis/bin/v++" --link --target hw --platform "$platform" --config "$work/connectivity.cfg" \
    --kernel_frequency 100 --optimize 0 --vivado.synth.jobs 64 --vivado.impl.jobs 64 \
    --vivado.param general.maxThreads=8 --save-temps --temp_dir "$link/temp" \
    --log_dir "$link/logs" "${cache[@]}" -o "$work/fpga_kernel.xclbin" "$xo"
) | tee "$work/link.$attempt.log"

mapfile -t routed < <(find "$link/temp" -type f -path '*/impl_*/*' -name '*routed.dcp' | sort)
[[ ${#routed[@]} -eq 1 ]] || fail "Expected one routed checkpoint in $link/temp"
mkdir -p "$work/timing"
(
  set +u
  source "$vivado/settings64.sh"
  set -u
  cd "$work/timing"
  "$vivado/bin/vivado" -mode batch -source "$src/check_implementation.tcl" -tclargs "${routed[0]}" "$work/timing"
) | tee "$work/timing/check.log"
"$xclbinutil" --input "$work/fpga_kernel.xclbin" --info > "$work/xclbin-info.txt"
grep -Eiq "UUID \(IINTF\):[[:space:]]+$interface([[:space:]]|$)" "$work/xclbin-info.txt" \
  || fail "Unexpected shell interface UUID in $work/xclbin-info.txt"
python3 - "$work/xclbin-info.txt" "$target" <<'PY'
import re
import sys
from pathlib import Path

info = Path(sys.argv[1]).read_text()
clocks = [(r'(?:DATA_CLK|KERNEL_CLK)' if sys.argv[2] == 'u250-ddr' else 'DATA_CLK', 100)]
if sys.argv[2] == 'u55c-hbm':
    clocks.append(('hbm_aclk', 450))
for clock, frequency in clocks:
    pattern = rf'Name:\s+{clock}\s+Index:\s+\d+\s+Type:\s+\w+\s+Frequency:\s+{frequency} MHz'
    if not re.search(pattern, info):
        raise SystemExit(f'Unexpected linked frequency for {clock}')
PY
cp "$src"/{host.cpp,host-build.py,host-flags.json} "$work/"
cp "$root/source-revision.txt" "$work/"
sha256sum "$xo" > "$work/xo-sha256.txt"
(cd "$src" && sha256sum fpga_kernel.sv control.sv) > "$work/rtl-sha256.txt"
(
  cd "$work"
  files=(fpga_kernel.xclbin host.cpp host-build.py host-flags.json connectivity.cfg
         xclbin-info.txt platforminfo.txt rtl-sha256.txt source-revision.txt xo-sha256.txt)
  sha256sum "${files[@]}" > SHA256SUMS
  tar -czf "spaced-$target-2022.2-hacc.tar.gz" "${files[@]}" SHA256SUMS timing
)
printf 'HACC_BUNDLE: %s/spaced-%s-2022.2-hacc.tar.gz\n' "$work" "$target"
