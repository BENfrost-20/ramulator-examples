#!/usr/bin/env bash
# User-invoked driver; no SSH and no operation is started automatically.
set -eo pipefail
root="$HOME/thesis/hbm-reference-smoke"
cd "$root"
if [[ "$#" != 1 ]]; then
  echo "Usage: bash run_integration.sh prepare|export|compile|rebuild-testbench|simulate" >&2
  exit 2
fi
action="$1"
case "$action" in
  prepare)
    exec python3 "$root/prepare_integration.py" prepare
    ;;
  export)
    source /opt/Xilinx/Vivado/2024.2/settings64.sh
    export HBM_INTEGRATION_DIR
    HBM_INTEGRATION_DIR="$(cat "$root/integration-last-prepared.txt")"
    vivado -mode batch -source "$root/export_integration.tcl" \
      -log "$HBM_INTEGRATION_DIR/export.log" \
      -journal "$HBM_INTEGRATION_DIR/export.jou"
    exec python3 "$root/prepare_integration.py" verify-export
    ;;
  compile|rebuild-testbench|simulate)
    source /opt/Xilinx/Vivado/2024.2/settings64.sh
    export VCS_HOME=/opt/synopsys/vcs/X-2025.06-SP2
    export PATH="$VCS_HOME/bin:$PATH"
    export VCS_TARGET_ARCH=linux64
    unset VCS_ARCH_OVERRIDE
    export SNPSLMD_LICENSE_FILE=2010@lmw-2d.polimi.it
    hash -r
    exec python3 "$root/prepare_integration.py" "$action"
    ;;
  *)
    echo "Usage: bash run_integration.sh prepare|export|compile|rebuild-testbench|simulate" >&2
    exit 2
    ;;
esac
