#!/usr/bin/env bash
set -eo pipefail
bdf=${1:?Pass the reserved U280 user-function PCI BDF}
[[ "$bdf" =~ ^[[:xdigit:]]{4}:[[:xdigit:]]{2}:[[:xdigit:]]{2}[.]1$ ]]
cd -- "$(dirname -- "$0")"
sha256sum -c SHA256SUMS
export XILINX_XRT=/opt/xilinx/xrt
export PATH="$XILINX_XRT/bin:$PATH"
export LD_LIBRARY_PATH="$XILINX_XRT/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
xrt_tool=$(command -v xrt-smi || command -v xbutil)
"$xrt_tool" examine -d "$bdf" -r platform | tee platform-observed.txt
grep -Fiq 'xilinx_u280_gen3x16_xdma_base_1' platform-observed.txt
mgmt="${bdf%.*}.0"
cat "/sys/bus/pci/devices/$mgmt/interface_uuids" > interface-uuids.txt
grep -Fiq 'fb2b2c5a19ed63593fea95f51fbc8eb9' < <(tr -d '-' < interface-uuids.txt)
hostname -f | tee node.txt
python3 -B host-build.py
env -u XCL_EMULATION_MODE ./host fpga_kernel.xclbin "$bdf" reads | tee host.log
python3 -B summarize.py reads | tee summary.tsv
