#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "$0")" && pwd)
src="$root/src"
vivado=/opt/Xilinx/Vivado/2022.2
vitis=/opt/Xilinx/Vitis/2022.2
xclbinutil=/opt/xilinx/xrt/bin/xclbinutil
platform=xilinx_u280_gen3x16_xdma_1_202211_1
xpfm="/opt/xilinx/platforms/$platform/$platform.xpfm"
work=$(mktemp -d "$PWD/u280-ddr-controller-build.XXXXXX")
printf 'Build directory: %s\n' "$work"
cd "$work"
mkdir link timing
printf 'set rtl_files [list {%s/fpga_kernel.sv} {%s/control.sv}]\n' "$src" "$src" > sources.tcl
cp "$src/registers.tcl" .
printf '[connectivity]\nnk=fpga_kernel:1:fpga_kernel_1\nsp=fpga_kernel_1.m_axi_0:DDR[0]\n' > connectivity.cfg

(
  set +u
  source "$vivado/settings64.sh"
  set -u
  "$vivado/bin/vivado" -mode batch -source "$src/package.tcl" -tclargs "$work" xcu280-fsvh2892-2L-e 10 8 2022.2
) 2>&1 | tee package.log
(
  set +u
  source "$vitis/settings64.sh"
  set -u
  platforminfo --platform "$xpfm" > platforminfo.txt
  "$vitis/bin/v++" --link --target hw --platform "$xpfm" --config connectivity.cfg \
    --kernel_frequency 100 --optimize 0 --save-temps --temp_dir "$work/link/temp" --log_dir "$work/link/logs" \
    --vivado.synth.jobs "${SYNTH_JOBS:-8}" --vivado.impl.jobs "${IMPL_JOBS:-1}" \
    --vivado.param general.maxThreads=8 -o fpga_kernel.xclbin fpga_kernel.xo
) 2>&1 | tee link.log

mapfile -t routed < <(find "$work/link/temp" -type f -path '*/impl_*/*' -name '*routed.dcp' | sort)
[[ ${#routed[@]} == 1 ]]
(
  set +u
  source "$vivado/settings64.sh"
  set -u
  cd timing
  "$vivado/bin/vivado" -mode batch -source "$src/check_implementation.tcl" -tclargs "${routed[0]}" "$work/timing"
) 2>&1 | tee timing/check.log
"$xclbinutil" --input fpga_kernel.xclbin --info > xclbin-info.txt
grep -Eiq 'UUID \(IINTF\):[[:space:]]+fb2b2c5a19ed63593fea95f51fbc8eb9([[:space:]]|$)' xclbin-info.txt
grep -Eq 'Name:[[:space:]]+DATA_CLK[[:space:]]+Index:[[:space:]]+[0-9]+[[:space:]]+Type:[[:space:]]+[^ ]+[[:space:]]+Frequency:[[:space:]]+100 MHz' < <(tr '\n' ' ' < xclbin-info.txt)
grep -Fq 'fpga_kernel_1.m_axi_0:DDR[0]' xclbin-info.txt
xci=$(find "$work/link/temp" -type f -name '*_ddr4_mem00_0.xci' -print -quit)
test -n "$xci"
python3 "$root/check-controller.py" "$xci" > controller.tsv
cp "$src"/{host.cpp,host-build.py,host-flags.json,ddr_address.hpp,source-revision.txt} .
cp "$root"/{run-hacc.sh,summarize.py} .
(cd "$src" && sha256sum fpga_kernel.sv control.sv) > rtl-sha256.txt
files=(fpga_kernel.xclbin host.cpp host-build.py host-flags.json ddr_address.hpp
       run-hacc.sh summarize.py connectivity.cfg xclbin-info.txt platforminfo.txt
       rtl-sha256.txt source-revision.txt controller.tsv)
sha256sum "${files[@]}" > SHA256SUMS
tar -czf u280-ddr-controller-hacc.tar.gz "${files[@]}" SHA256SUMS timing
printf 'HACC_BUNDLE: %s/u280-ddr-controller-hacc.tar.gz\n' "$work"
