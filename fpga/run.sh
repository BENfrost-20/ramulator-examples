#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$root${PYTHONPATH:+:$PYTHONPATH}"
exec python3 "$root/fpga/run.py" "$@"
