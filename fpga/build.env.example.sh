# Copy to fpga/build.env.sh. This file is sourced by fpga/build.sh.
# Precedence: command-line flags > existing environment > these defaults.
# Paths are site settings; this file contains no license credentials.
ferrandi_toolchain="$HOME/thesis/toolchain-ramulator21-dca0351"
if [[ -n "${FPGA_BAMBU_SOURCE:-}" && "$FPGA_BAMBU_SOURCE" != "$ferrandi_toolchain/PandA-bambu" ]]; then
    ferrandi_bambu_install="$FPGA_BAMBU_SOURCE/install"
else
    export FPGA_BAMBU_SOURCE="$ferrandi_toolchain/PandA-bambu"
    ferrandi_bambu_install="$ferrandi_toolchain/bambu-install"
fi
export FPGA_BAMBU="${FPGA_BAMBU:-$ferrandi_bambu_install/bin/bambu}"
export FPGA_BAMBU_SETTINGS="${FPGA_BAMBU_SETTINGS-$ferrandi_bambu_install/settings.sh}"
export FPGA_CLANG_BIN="${FPGA_CLANG_BIN:-$HOME/thesis/toolchains/clang-13/bin}"
export FPGA_VIVADO_SETTINGS="${FPGA_VIVADO_SETTINGS-/opt/Xilinx/Vivado/2024.2/settings64.sh}"
export FPGA_VITIS_SETTINGS="${FPGA_VITIS_SETTINGS-/opt/Xilinx/Vitis/2024.2/settings64.sh}"
export FPGA_VIVADO="${FPGA_VIVADO:-/opt/Xilinx/Vivado/2024.2/bin/vivado}"
export FPGA_VPP="${FPGA_VPP:-/opt/Xilinx/Vitis/2024.2/bin/v++}"
export FPGA_TOOLCHAIN_RECEIPT="${FPGA_TOOLCHAIN_RECEIPT:-$FPGA_REPO_ROOT/.fpga/site/toolchain-receipt.json}"
export FPGA_BOARD="${FPGA_BOARD:-xcu55c}"
export FPGA_CASE="${FPGA_CASE:-memory_probe_single}"
export FPGA_PERIOD_NS="${FPGA_PERIOD_NS:-10}"
export FPGA_JOBS="${FPGA_JOBS:-8}"
export FPGA_SYNTH_JOBS="${FPGA_SYNTH_JOBS:-$FPGA_JOBS}"
export FPGA_IMPL_JOBS="${FPGA_IMPL_JOBS:-$FPGA_JOBS}"
export FPGA_THREADS="${FPGA_THREADS:-8}"
export FPGA_IP_CACHE="${FPGA_IP_CACHE:-$FPGA_REPO_ROOT/.fpga/ip-cache/2024.2}"
export FPGA_FIX_ADAPTER_LOG2="${FPGA_FIX_ADAPTER_LOG2:-1}"
export FPGA_BUILD_ROOT="${FPGA_BUILD_ROOT:-$FPGA_REPO_ROOT/.fpga/builds}"
export FPGA_TMUX_MODE="${FPGA_TMUX_MODE:-auto}"
export FPGA_TMUX_BIN="${FPGA_TMUX_BIN:-tmux}"
export FPGA_TMUX_ROOT="${FPGA_TMUX_ROOT:-$FPGA_REPO_ROOT/.fpga/tmux}"
export FPGA_PLATFORM_XCU55C="${FPGA_PLATFORM_XCU55C:-/opt/xilinx/platforms/xilinx_u55c_gen3x16_xdma_3_202210_1/xilinx_u55c_gen3x16_xdma_3_202210_1.xpfm}"
# Set independent platform variables when using other registered boards.
# export FPGA_PLATFORM_XCU280=/absolute/path/to/u280.xpfm
# export FPGA_PLATFORM_XCU250=/absolute/path/to/u250.xpfm
# export FPGA_PROFILE=/absolute/path/to/deployment-profiles.json
# export FPGA_MEMORY_MAPS='m_axi_0=HBM[1]'
