# Source the existing repository env.sh first for Bambu/Ramulator; no Vitis HLS use.
export PATH="/opt/Xilinx/Vivado/2024.2/bin:/opt/Xilinx/Vitis/2024.2/bin:$PATH"
export XILINX_XRT=/opt/xilinx/xrt
# Confirm platform/tool/shell/runtime compatibility before filling the receipt.
export FPGA_PLATFORM_XCU55C=/opt/xilinx/platforms/xilinx_u55c_gen3x16_xdma_3_202210_1/xilinx_u55c_gen3x16_xdma_3_202210_1.xpfm
# FPGA_PLATFORM_XCU280, FPGA_PLATFORM_XCU250 are independent overrides.
# export FPGA_PROFILE=/absolute/path/to/your-deployment-boards.json
# export FPGA_PLATFORM_RECEIPT=/absolute/path/to/verified-platform.json
# export FPGA_BAMBU=/absolute/path/to/ferrandi/install/bin/bambu
# export FPGA_BAMBU_SOURCE=/absolute/path/to/ferrandi/PandA-bambu
# export FPGA_QUESTA=/absolute/path/to/supported/questa/bin
# export FPGA_VCS=/absolute/path/to/supported/vcs/bin
