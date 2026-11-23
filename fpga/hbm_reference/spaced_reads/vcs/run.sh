#!/usr/bin/env bash
set -eo pipefail
here=$(cd -- "$(dirname -- "$0")" && pwd)
source /opt/Xilinx/Vivado/2024.2/settings64.sh
export VCS_HOME=/opt/synopsys/vcs/X-2025.06-SP2
export PATH="$VCS_HOME/bin:$PATH"
export VCS_TARGET_ARCH=linux64
unset VCS_ARCH_OVERRIDE
export SNPSLMD_LICENSE_FILE=${SNPSLMD_LICENSE_FILE:-2010@lmw-2d.polimi.it}
exec python3 -B "$here/run.py" "$@"
