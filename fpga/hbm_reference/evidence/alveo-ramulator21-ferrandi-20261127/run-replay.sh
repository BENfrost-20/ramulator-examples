#!/usr/bin/env bash
set -euo pipefail

if [[ $# != 1 ]]; then
    echo "Usage: bash run-replay.sh U55C_REPLAY_DIRECTORY" >&2
    exit 2
fi
src=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
cd "$src"
u55c=$(cd -- "$1" && pwd -P)
binary="$u55c/obj/Vfpga_kernel"
test -x "$binary"
test -s "$u55c/refresh-cadence.tsv"
library=$(env -u LD_LIBRARY_PATH -u LD_PRELOAD ldd "$binary" |
    awk '$1 == "libramulator.so.2" && $2 == "=>" && $3 ~ /^\// { print $3 }')
test -f "$library"
sha256sum "$binary" "$library" run-replay.sh profiles/*.yaml > replay-inputs.sha256
cp "$u55c/provenance.txt" reused-u55c-provenance.txt
for profile in u280-hbm2-matched-1800 u280-hbm2-bambu-2000 ddr4-xci-matched-2400 u250-ddr4-bambu-2400; do
    for phase in 0 97 195 292; do
        run="$src/runs/$profile/phase-$phase"
        mkdir -p "$(dirname -- "$run")"
        mkdir "$run"
        (
            cd "$run"
            env -u LD_LIBRARY_PATH -u LD_PRELOAD "$binary" "$src/profiles/$profile.yaml" "$phase"
        ) 2>&1 | tee "$run/run.log"
    done
done
printf 'RESULTS: %s\n' "$src"
