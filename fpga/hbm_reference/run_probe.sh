#!/usr/bin/env bash
# Launch the one-word probe from this source directory, with private run files.
set -eo pipefail
probe_source=$(cd -- "$(dirname -- "$0")" && pwd)
for arg in "$@"; do
  case "$arg" in
    -h|--help|--prepare-only) exec python3 -B "$probe_source/prepare_probe.py" "$@" ;;
  esac
done
if [[ "$#" -gt 0 ]]; then
  source /opt/Xilinx/Vivado/2024.2/settings64.sh
  export VCS_HOME=/opt/synopsys/vcs/X-2025.06-SP2
  export PATH="$VCS_HOME/bin:$PATH"
  export VCS_TARGET_ARCH=linux64
  unset VCS_ARCH_OVERRIDE
  export SNPSLMD_LICENSE_FILE=2010@lmw-2d.polimi.it
  hash -r
fi
exec python3 -B "$probe_source/prepare_probe.py" "$@"
