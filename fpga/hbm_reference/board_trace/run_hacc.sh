#!/usr/bin/env bash
# Deliberately program the reserved board and measure the one-word probe.
set -eo pipefail

if [[ $# != 1 || ! "$1" =~ ^[[:xdigit:]]{4}:[[:xdigit:]]{2}:[[:xdigit:]]{2}\.[0-7]$ ]]; then
  echo 'Usage: bash run_hacc.sh PCI_BDF (for example, 0000:85:00.1)' >&2
  exit 2
fi
bdf="$1"
bundle=$(cd -- "$(dirname -- "$0")" && pwd)
cd "$bundle"
sha256sum -c SHA256SUMS
if ! command -v xrt-smi >/dev/null 2>&1; then
  printf '%s\n' 'Initialize XRT in the calling shell, then rerun: source /opt/hdev/cli/enable/xrt' >&2
  exit 2
fi
run=$(mktemp -d "$bundle/board-run.XXXXXX")
printf 'HACC evidence: %s\n' "$run"
hostname > "$run/hostname.txt"
printf '%s\n' "$bdf" > "$run/bdf.txt"
xrt-smi examine > "$run/xrt-smi.txt"
if [[ ! -x "$bundle/host" ]]; then
  python3 -B "$bundle/build.py"
fi
env -u XCL_EMULATION_MODE "$bundle/host" "$bundle/fpga_kernel.xclbin" "$bdf" 1 1 60 \
    "$run/board-results.jsonl" 2>&1 | tee "$run/host.log"
python3 -B "$bundle/compare_trace.py" "$run" | tee "$run/comparison.json"
cat "$run/board-axi.jsonl"
