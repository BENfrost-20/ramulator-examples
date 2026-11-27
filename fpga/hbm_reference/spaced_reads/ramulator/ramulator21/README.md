# Ferrandi U55C replay with Ramulator 2.1

The build uses Git, CMake, Make, GCC/G++ 13 or newer, and Python 3.10+.
Verilator and a C++20 compiler run the replay. Bambu additionally uses Boost
headers, zlib and the Clang/LLVM 13 HLS frontend. Ccache is optional.
The script uses the existing Ferrandi tools below `~/thesis` when available
and downloads the pinned CMake dependencies as needed.

Run from the repository root on Ferrandi:

```sh
runner=fpga/hbm_reference/spaced_reads/ramulator/ramulator21/ferrandi.sh
JOBS=12 bash "$runner" replay
JOBS=12 bash "$runner" bambu
```

The first command builds only the pinned Ramulator C++ library and replays the
existing U55C RTL using Verilator. The second command completes the matching Bambu
installation using the same workspace. Its Ramulator build is incremental.
Each replay gets separate output. Execute the two commands sequentially.
The default workspace is `~/thesis/toolchain-ramulator21-dca0351`.
Set `FPGA_VERILATOR` to a specific Verilator binary if needed. The script uses the
existing GCC 13, Clang, CMake, Boost and ccache installations when available.
If the system Python is older than 3.10, set `PYTHON3=/absolute/path/to/python3.11`
before running the commands. That interpreter is used by CMake, Verilator and
the comparison scripts. A new Python can be installed in your home directory
with [uv](https://docs.astral.sh/uv/guides/install-python/).
The source clone can borrow objects from the old Bambu repository and dissociates
from it before building. The old prefixes and VCS environment remain available.

To activate the installed pair in a new shell:

```sh
toolchain="$HOME/thesis/toolchain-ramulator21-dca0351"
source "$toolchain/bambu-install/settings.sh"
export RAMULATOR2_DIR="$toolchain/ramulator-install"
bambu --version
"$RAMULATOR2_DIR/bin/ramulator2" --help
```

## Workload and comparison

The RTL and hardware reference come from `ramulator-examples@5b7579f`.
The probe performs 1,000 four-byte single-beat reads at one address at
100 MHz, with one read outstanding. The benchmark checks request counts, the
readback and control status, and AXI timestamps. It uses phases 0, 97, 195 and
292, as in the historical run. The previous refresh-enabled Ramulator 2.0
comparison is included as a four-phase TSV plus the 1,000-read phase-292 CSV.
The recorded hardware is the U55C-08 HBM[0] reference.

- `bambu-2000` uses the 2000 MT/s U55C board template from Bambu
  `dca0351c92ff287c070d482088858aadca5f6a4a`, with command tracing.
- `matched-rate-1800` uses the same geometry, controller, mapper and refresh
  policy at the historical 1800 MT/s data rate. It is an experimental timing
  profile. The generator scales the 2.1 preset's minimum timings, uses a
  conservative turnaround assumption, and rebuilds the derived constraints
  using the pinned Ramulator DRAM definitions. The 2.0 profile used different
  command timing values and channel-scoped refresh. Ramulator 2.1 defaults
  to pseudochannel-scoped HBM2 refresh.
- `comparison-*.tsv` gives raw latencies and the maximum empirical CDF
  difference after alignment by the median. `refresh-cadence.tsv` gives the
  measured refresh cadence on the pseudochannel serving the 1,000 reads.
- The fixed RTL isolates the DRAM model at the probe's AXI boundary. The
  replay bypasses Bambu MDPI transport calibration. The median gap against
  hardware remains an independent measurement.

`make_profiles.py` documents the configuration generation and requires
PyYAML and the pinned simulator's Python source tree only for regeneration.
The replay uses the supplied YAML files directly.
