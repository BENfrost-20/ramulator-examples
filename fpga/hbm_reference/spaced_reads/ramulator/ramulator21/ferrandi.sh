#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
probe=$(cd -- "$script_dir/.." && pwd -P)
repo=$(cd -- "$probe/../../../.." && pwd -P)
evidence="$repo/fpga/hbm_reference/evidence"
mode=${1:-}
case "$mode" in
    replay|bambu) ;;
    *) echo "Usage: bash ferrandi.sh replay|bambu [workspace]" >&2; exit 2 ;;
esac

thesis="$HOME/thesis"
work=$(realpath -m -- "${2:-$thesis/toolchain-ramulator21-dca0351}")
jobs=${JOBS:-12}
[[ "$jobs" =~ ^[1-9][0-9]*$ ]] || { echo 'JOBS must be a positive integer.' >&2; exit 2; }
[[ "$work$repo" != *[[:space:]]* ]] || {
    echo 'Use workspace and repository directories without whitespace.' >&2; exit 2;
}
case "$work/" in
    "$HOME/"*) ;;
    *) echo 'Choose a workspace below your home directory.' >&2; exit 2 ;;
esac

bambu_rev=dca0351c92ff287c070d482088858aadca5f6a4a
ramulator_rev=3fec8f1cbddf75f4005426fd206342096612d100
bambu_url=https://github.com/ferrandi/PandA-bambu.git
bambu_ref=upgrade/ramulator-2.1-platform-calibration
bambu_src="$work/PandA-bambu"
ram_path=ext/ramulator2-no-spdlog
ram_build="$work/ramulator-build"
ram_prefix="$work/ramulator-install"
bambu_prefix="$work/bambu-install"
logs="$work/logs"

for directory in "$thesis/tools/cmake-3.31.10-linux-x86_64/bin" "$thesis/toolchains/clang-13/bin" "$thesis/toolchains/clang-19/bin"; do
    if [[ -d "$directory" ]]; then export PATH="$directory:$PATH"; fi
done
cc=$(command -v gcc-13)
cxx=$(command -v g++-13)
cmake=$(command -v cmake)

python3_exe=
select_python() {
    local candidate
    candidate=$(command -v -- "$1") || return 1
    "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1 || return 1
    python3_exe=$candidate
}
if [[ -n "${PYTHON3:-}" ]]; then
    select_python "$PYTHON3" || {
        printf 'PYTHON3 must point to Python 3.10 or newer: %s\n' "$PYTHON3" >&2
        exit 2
    }
else
    for minor in 10 11 12 13 14 15; do
        if select_python "python3.$minor" || select_python "$HOME/.local/bin/python3.$minor"; then
            break
        fi
    done
    if [[ -z "$python3_exe" ]] && ! select_python python3; then
        echo 'Python 3.10+ is required. Set PYTHON3 to the absolute interpreter path.' >&2
        exit 2
    fi
fi
printf 'Python: %s (%s)\n' "$python3_exe" "$("$python3_exe" --version)"
launcher=()
if command -v ccache >/dev/null; then
    cache=$(command -v ccache)
    launcher=(-DCMAKE_C_COMPILER_LAUNCHER="$cache" -DCMAKE_CXX_COMPILER_LAUNCHER="$cache")
fi
mkdir -p -- "$logs"

if [[ ! -d "$bambu_src/.git" ]]; then
    reference=()
    if [[ -d "$thesis/PandA-bambu-ferrandi/.git" ]]; then
        reference=(--reference-if-able "$thesis/PandA-bambu-ferrandi" --dissociate)
    fi
    git clone --no-checkout --depth 1 --single-branch --branch "$bambu_ref" \
        "${reference[@]}" "$bambu_url" "$bambu_src"
    if ! git -C "$bambu_src" cat-file -e "$bambu_rev^{commit}" 2>/dev/null; then
        git -C "$bambu_src" fetch --depth 1 origin "$bambu_rev"
    fi
    git -C "$bambu_src" checkout --detach "$bambu_rev"
fi
[[ "$(git -C "$bambu_src" rev-parse HEAD)" == "$bambu_rev" ]] || {
    echo "Unexpected Bambu revision at $bambu_src." >&2; exit 2;
}

git -C "$bambu_src" submodule update --init --depth 1 -- "$ram_path"
[[ "$(git -C "$bambu_src/$ram_path" rev-parse HEAD)" == "$ramulator_rev" ]] || {
    echo "Unexpected Ramulator revision at $bambu_src/$ram_path." >&2; exit 2;
}
# Explicit thread linkage supports Linux systems with a separate libpthread.
"$cmake" -S "$bambu_src/$ram_path" -B "$ram_build" -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_CXX_COMPILER="$cxx" -DPython3_EXECUTABLE:FILEPATH="$python3_exe" \
    "${launcher[@]}" -DCMAKE_INSTALL_PREFIX="$ram_prefix" \
    -DCMAKE_SHARED_LINKER_FLAGS=-pthread -DCMAKE_EXE_LINKER_FLAGS=-pthread \
    -DRAMULATOR_PYTHON_BINDINGS=OFF -DYAML_CPP_BUILD_TESTS=OFF -DFMT_TEST=OFF \
    2>&1 | tee "$logs/ramulator-configure.log"
"$cmake" --build "$ram_build" --parallel "$jobs" 2>&1 | tee "$logs/ramulator-build.log"
"$cmake" --install "$ram_build" 2>&1 | tee "$logs/ramulator-install.log"
"$ram_prefix/bin/ramulator2" --help > "$logs/ramulator-help.log"
library=$(find "$ram_prefix" \( -type f -o -type l \) -name libramulator.so -print -quit)
test -n "$library"

if [[ "$mode" == bambu ]]; then
    git -C "$bambu_src" submodule update --init --recursive --jobs "$jobs" -- \
        etc/ac_math etc/ac_types ext/abseil/abseil-cpp ext/buddy ext/gcem ext/glaze \
        ext/mockturtle/mockturtle ext/pugixml
    boost=()
    if [[ -d "$thesis/toolchains/boost-1.83.0" ]]; then
        boost=(-DCMAKE_PREFIX_PATH="$thesis/toolchains/boost-1.83.0")
    fi
    "$cmake" -S "$bambu_src" -B "$work/bambu-build" -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_C_COMPILER="$cc" -DCMAKE_CXX_COMPILER="$cxx" "${launcher[@]}" \
        "${boost[@]}" -DPython3_EXECUTABLE:FILEPATH="$python3_exe" -DCMAKE_INSTALL_PREFIX="$bambu_prefix" -DBUILD_TESTING=OFF \
        -DPANDA_BUILD_EUCALYPTUS=OFF 2>&1 | tee "$logs/bambu-configure.log"
    "$cmake" --build "$work/bambu-build" --parallel "$jobs" 2>&1 | tee "$logs/bambu-build.log"
    "$cmake" --install "$work/bambu-build" 2>&1 | tee "$logs/bambu-install.log"
    export RAMULATOR2_DIR="$ram_prefix"
    source "$bambu_prefix/settings.sh"
    "$bambu_prefix/bin/bambu" --version | tee "$logs/bambu-version.log"
    printf 'Bambu: %s\nRamulator: %s\n' "$bambu_prefix" "$ram_prefix"
    exit
fi

if [[ -n "${FPGA_VERILATOR:-}" ]]; then
    verilator=$FPGA_VERILATOR
elif [[ -x /opt/verilator/verilator-5.052/bin/verilator ]]; then
    verilator=/opt/verilator/verilator-5.052/bin/verilator
else
    verilator=$(command -v verilator)
fi
out=$(mktemp -d "$work/u55c-replay.XXXXXX")
printf 'Replay output: %s\n' "$out"
{
    printf 'Bambu source revision: %s\nRamulator revision: %s\n' "$bambu_rev" "$ramulator_rev"
    "$verilator" --version
    "$cxx" --version
    sha256sum "$library"
    "$python3_exe" --version
    git -C "$repo" rev-parse HEAD
    sha256sum "$probe/"{abi.hpp,fpga_kernel.sv,control.sv,bench.cpp,hardware.csv,compare.py} \
        "$repo/fpga/host/"{functional_axi.hpp,ramulator_timing.hpp,buffers.hpp} "$script_dir/"{ferrandi.sh,compare_refresh.py} \
        "$script_dir/profiles/"*.yaml "$evidence/spaced_reads_u55c_ramulator_phase292.csv" \
        "$evidence/spaced_reads_u55c_ramulator_refresh.tsv"
} > "$out/provenance.txt"

"$verilator" --cc --exe --build -j "$jobs" --Mdir "$out/obj" --top-module fpga_kernel -Wno-fatal \
    -MAKEFLAGS "CXX=$cxx LINK=$cxx PYTHON3=$python3_exe" \
    -CFLAGS "-std=c++20 -DFPGA_WITH_RAMULATOR -I$repo/fpga/host -I$probe -I$ram_prefix/include" \
    -LDFLAGS "-L$(dirname -- "$library") -Wl,-rpath,$(dirname -- "$library") -Wl,--no-as-needed -lramulator -Wl,--as-needed" \
    "$probe/fpga_kernel.sv" "$probe/control.sv" "$probe/bench.cpp" \
    2>&1 | tee "$out/verilator-build.log"

mkdir -p "$out/ramulator20-reference/phase-292"
cp "$evidence/spaced_reads_u55c_ramulator_phase292.csv" "$out/ramulator20-reference/phase-292/latencies.csv"
cp "$evidence/spaced_reads_u55c_ramulator_refresh.tsv" "$out/ramulator20-refresh-all-phases.tsv"
for profile in bambu-2000 matched-rate-1800; do
    cp "$script_dir/profiles/$profile.yaml" "$out/$profile.yaml"
    for phase in 0 97 195 292; do
        run="$out/$profile/phase-$phase"
        mkdir -p "$run"
        (cd -- "$run" && "$out/obj/Vfpga_kernel" "$out/$profile.yaml" "$phase") \
            2>&1 | tee "$run/run.log"
    done
done
for profile in ramulator20-reference bambu-2000 matched-rate-1800; do
    printf '\n--- %s ---\n' "$profile"
    "$python3_exe" "$probe/compare.py" "$probe/hardware.csv" "$out/$profile" \
        | tee "$out/comparison-$profile.tsv"
done
"$python3_exe" "$script_dir/compare_refresh.py" "$out" | tee "$out/refresh-cadence.tsv"
printf '\nRESULTS: %s\n' "$out"
