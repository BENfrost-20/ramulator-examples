# Bambu + Ramulator examples

Examples and longer benchmark suites for [Bambu](https://github.com/ferrandi/PandA-bambu)
with [Ramulator memory timing](https://github.com/ferrandi/ramulator2).

## Credits and provenance

- [@jesunsahariar](https://github.com/jesunsahariar) developed the original Bambu/Ramulator
  integration and benchmark scripts in
  [bambu-ramulator-release](https://github.com/jesunsahariar/bambu-ramulator-release).
- [@BENfrost-20](https://github.com/BENfrost-20) collected the standalone suites,
  runner, configurations, and recorded results in
  [tests_bambu_ramulator](https://github.com/BENfrost-20/tests_bambu_ramulator).
  This repository preserves that repository's Git history, starting from
  [`b55d3d5`](https://github.com/BENfrost-20/tests_bambu_ramulator/commit/b55d3d5).

Original source copyright and license notices remain with the respective files.
The imported benchmark projects retain their own licenses.

## Repository layout

Each suite has a `run.sh` containing its cases, compiler options and test
configuration. Run a suite directly or use `run_tests.sh` to execute several suites.

| Directory | Contents |
|---|---|
| `smoke/` | Vector-add channel variants, clock-ratio and memory diagnostics |
| `micro/` | Memory access patterns and reference checker |
| `openmp/` | Functional kernels and the original test list |
| `gapbs/` | Graph test list and pinned `sources/` submodule |
| `polybench/` | Eight kernels from a pinned source submodule, with generated kernel/testbench adapters |
| `machsuite/` | 19 official workloads from a pinned source submodule, with generated AXI/MDPI adapters |
| `results/` | Manually approved versioned golden data and collection/comparison scripts |
| `tools/` | Environment checks, input staging, local execution and golden comparison |
| [fpga/](fpga/README.md) | Bambu RTL preparation, FPGA builds, VCS reference and HACC deployment |
| [fpga/hardware/](fpga/hardware/README.md) | Reference cards, HACC nodes, and observed memory and clock configurations |
| [validation/](validation/README.md) | Experimental memory-model generation and trace analysis |

`run_tests.sh` runs up to `J` cases concurrently within each selected suite.
The same limit applies when running a suite directly. If `J` is unset or empty,
cases run one at a time. Each case has its own working directory, temporary
files and log. The runner finishes the remaining cases and suites after a test
fails, then compares with the latest approved golden collection. Failed cases
and cycle-count regressions produce a nonzero exit status.

`boards.json` defines the Bambu device, default clock and memory configuration
for each board. Standard memory presets come from the Bambu installation under
`share/panda/libmdpi/configs`.
Test-specific YAMLs live next to their owning tests: `smoke/configs/` contains
the recorded DDR5 diagnostic variant and a 32-channel HBM2 configuration (also
selected by the HBM board aliases), while `smoke/clock_ratio.yaml` configures the ratio variants.
`--config PATH` overrides the YAML for an execution.

## FPGA and HBM workflows

- [Build a bitstream](fpga/BUILD.md) with the build-only driver.
- [Deploy to HACC](fpga/HACC.md) with the portable hardware and host bundle.
- [Reproduce the measured U55C probe](fpga/hbm_reference/PROBE.md) with Bambu,
  Ramulator, AMD VCS and hardware AXI traces.
- [Configure a new memory-model experiment](validation/README.md) with the
  experimental reference generator and traffic analysis tools.

## Setup and execution

### Toolchain repositories

- **ramulator-examples** contains the benchmark recipes, FPGA probes and
  validation tools in this checkout. The upstream repository is
  [ferrandi/ramulator-examples](https://github.com/ferrandi/ramulator-examples).
  Bambu also pins a snapshot at `examples/ramulator-examples` for its own
  examples. Run the commands below from the standalone checkout you want to test.
- **PandA-bambu** contains the HLS compiler, generated simulation testbenches,
  MDPI memory driver, and platform configuration and transport calibration.
  Use [the pinned calibration branch revision](https://github.com/ferrandi/PandA-bambu/tree/dca0351c92ff287c070d482088858aadca5f6a4a).
- **ferrandi/ramulator2** supplies the DRAM models and `libramulator.so`.
  In the calibration branch, `ext/ramulator2-no-spdlog` points to
  [the Ferrandi Ramulator 2.1 revision](https://github.com/ferrandi/ramulator2/tree/3fec8f1cbddf75f4005426fd206342096612d100).
  The Bambu checkout fetches that source through Git submodules, and its
  preparation script builds Ramulator into its own installation prefix.
  The standalone simulator can also be built from this Ramulator commit.
  That build alone does not provide the Bambu compiler or MDPI driver.

The 2.0 data remain available for comparison. To reproduce those original
runs, use the [pre-upgrade checkout](https://github.com/BENfrost-20/ramulator-examples/tree/5b7579f2e260a5b332e6bbf90fa4c21ce272977d)
with the toolchain recorded by each experiment. The original Jesun repositories listed
under credits are source history. GAPBS, MachSuite and PolyBenchC are
benchmark source dependencies and are separate from the simulator.

### Ferrandi memory replay and results

Use the [U55C 1,000-read replay](fpga/hbm_reference/spaced_reads/ramulator/ramulator21/README.md)
to build the pinned library with an existing Ferrandi toolchain and compare at
1800 and 2000 MT/s against hardware and Ramulator 2.0. See the [Alveo memory latency report](fpga/hbm_reference/evidence/alveo-ramulator21-ferrandi-20261127/README.md)
for the four tested board and memory combinations. The setup accepts
`PYTHON3` to select an interpreter when the host default is older than 3.10.

### Build on Linux x86-64

Use the pinned pair from [the toolchain manifest](fpga/toolchain.json).
Install GCC 13 or newer for the Bambu build, Clang/LLVM 13 for
`I386_CLANG13`, and Verilator for co-simulation. The runner uses a host Clang
(trying Clang 19 first) plus Make, Git, Bash, Awk, `bc`, `envsubst`, `timeout`,
`objcopy`, `readelf` and `ldd`. Ramulator needs Python 3.10+ at build time
and fetches yaml-cpp and fmt during CMake configuration.

From the directory that will hold the Bambu source and Ramulator install:

```bash
git clone --branch upgrade/ramulator-2.1-platform-calibration \
  https://github.com/ferrandi/PandA-bambu.git PandA-bambu-ramulator21
bambu_src="$PWD/PandA-bambu-ramulator21"
ramulator_build="$PWD/ramulator21"
git -C "$bambu_src" checkout --detach dca0351c92ff287c070d482088858aadca5f6a4a
git -C "$bambu_src" submodule update --init --recursive
git -C "$bambu_src" ls-tree HEAD ext/ramulator2-no-spdlog
git -C "$bambu_src/ext/ramulator2-no-spdlog" rev-parse HEAD

# Ensure Clang/LLVM 13 is on PATH before configuring Bambu.
cmake -S "$bambu_src" -B "$bambu_src/build" -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_C_COMPILER=gcc-13 -DCMAKE_CXX_COMPILER=g++-13 \
  -DCMAKE_INSTALL_PREFIX="$bambu_src/install"
cmake --build "$bambu_src/build" --parallel 4
cmake --install "$bambu_src/build"

# The output directory must be new. The script installs the submodule pinned above.
CC=gcc-13 CXX=g++-13 bash \
  "$bambu_src/panda_regressions/hls/bambu_ramulator/prepare_ramulator.sh" "$ramulator_build"
export RAMULATOR2_DIR="$ramulator_build/install"
source "$bambu_src/install/settings.sh"
```

Run from the standalone `ramulator-examples` checkout. To persist the paths
for future shells, copy `env.example.sh` to `env.sh` and set both prefixes.

```sh
./smoke/run.sh --case smoke_axi_1ch --tag ramulator21 --no-compare
./smoke/run.sh --case diagnostic_ddr3 --tag ramulator21 --no-compare
./smoke/run.sh --case diagnostic_ddr5 --tag ramulator21 --no-compare
./smoke/run.sh --case diagnostic_hbm2 --tag ramulator21 --no-compare
```

With 2.1, Bambu derives DRAM ticks from the accelerator period and DRAM
`tCK`. Preset YAMLs are translated by the Ferrandi adapter. Custom 2.0
timing overrides such as the historical U55C 1800 MT/s and XCI-aligned DDR4
measurements require a native 2.1 YAML with resolved timing constraints for
a new 2.1 experiment. Reproduce those archived traces with their recorded
2.0 toolchain. Bambu's `--ramulator-profile=alveo-u55c` (also
`alveo-u250` or `alveo-u280`) selects a native board profile. To inspect
resolved configuration and calibration artifacts, use the
[pinned Bambu profile regression](https://github.com/ferrandi/PandA-bambu/blob/dca0351c92ff287c070d482088858aadca5f6a4a/panda_regressions/hls/bambu_ramulator/run_profiles.py).
Use `--no-compare` for initial 2.1 runs while establishing a new baseline.

GAPBS, PolyBench and MachSuite use pinned `sources/` submodules. For an existing checkout:

```sh
git submodule update --init --recursive gapbs/sources polybench/sources machsuite/sources
```

PolyBench and MachSuite generate their adapters automatically before execution.
The `smoke`, `micro` and `openmp` suites keep their local test sources.
`RAMULATOR2_DIR` points to the prefix containing
`include/ramulator/` and `lib/libramulator.so` (or `lib64/`).

The runner and each suite script accept `--board NAME`, `--config PATH`, `--tag LABEL`,
`--dry-run`, `--keep-work`, `--case NAME`, `--tests PATTERNS` and `--no-compare`.
For example:

```sh
./openmp/run.sh --case openmp_monothread_1ch --tag single-case
./smoke/run.sh --case diagnostic_ddr3 --tag memory-preset
./run_tests.sh --all --tag complete
./smoke/run.sh --case smoke_axi_1ch
./smoke/run.sh --case smoke_clock_ratio_1ch
```

`--case` selects one exact case within a suite; use `--suite NAME` with the
global runner. `--tests` selects names or patterns across suites. By default,
the global runner executes all suites.

Clock selection uses `CLOCK_PERIOD_NS` when set, then the case's clock setting,
then the selected board's default. For example:

```sh
CLOCK_PERIOD_NS=10 ./smoke/run.sh --case smoke_axi_1ch
```

PolyBench runs eight selected original kernels in three profiles:
`native` (shared minimal bus, 1/2/4 channels), `axi` (1/2/4 channels) and `axi_tb` (one channel,
with the utility compiled as part of the testbench). The two originally recorded
cases retain their names `polybench_gemm` and `polybench_atax`.

```sh
./polybench/run.sh --case polybench_trisolv_axi_tb_1ch
./polybench/run.sh --case polybench_gemm_native_2ch
```

MachSuite includes all 19 official workloads. Its launcher generates the AXI
kernels and MDPI support from the pinned sources before execution. Use
`./machsuite/run.sh --list` to list cases and `--tests 'machsuite_spmv_*'` to
select a family. The [suite README](machsuite/README.md) describes preparation,
functional checks and the dedicated backprop reference.

GAPBS keeps the original undirected graph. Its incoming-graph argument positions
are retained for compatibility; the loader only reads the outgoing graph files.
Long suites can take hours.

## Results: execute, compare, approve

The runner executes the tests. The result scripts compare or approve the saved
results.

```sh
./run_tests.sh --all --board xcu250 --tag current
# Or a selected suite / case:
./run_tests.sh --suite polybench --case polybench_trisolv_axi_tb_1ch
```

The runner prints a batch directory under `.runs/`. After all selected suites
finish, including failures, it automatically compares their results with the
**last manually approved** golden version. Independent `<suite>/run.sh` executions
also perform this comparison when used directly. Golden data is updated through
manual approval. Logs, input/configuration snapshots, metadata, per-case
JSON results and `comparison.json` remain local and ignored by Git.

On a host with Bambu and Ramulator installed, run the full benchmark suite with:

```sh
./run_tests.sh --all --no-compare
```

`--no-compare` makes the exit status depend on test execution and functional
checks. Saved results remain available for later manual comparison or approval.

Select a subset with comma-separated names or shell-style patterns. Quote the
patterns so the shell does not expand them. Repeat `--tests` to combine selections:

```sh
./run_tests.sh --all --tests 'smoke_*,polybench_trisolv_*'
./polybench/run.sh --tests 'polybench_gemm_*,polybench_atax_*'
# Set RUN_DIR to the batch directory printed by the runner.
RUN_DIR=.runs/batch_...
./results/golden.sh "$RUN_DIR" --tests 'smoke_*'
./results/compare.sh "$RUN_DIR" --tests 'polybench_*'
```

The runner skips suites with no selected cases. Golden collection and comparison
process the selected saved results.
Without `--tests`, each command processes its full normal selection. A golden or
comparison selection with no matching results is an error.

Set `RUN_DIR` to the printed batch or direct suite run directory. Inspect its
results, then explicitly approve its successful cases:

```sh
./results/golden.sh "$RUN_DIR"
# Repeat a comparison of the saved results:
./results/compare.sh "$RUN_DIR"
```

The manual collector adds missing configurations under the Bambu build used by
that run. Existing identical golden results are left unchanged. If any existing
golden differs, it reports the conflicting metrics and exits with an error
**before adding anything**. Failed or missing cases are reported and excluded; dry runs and incomplete batches cannot be approved.
Approval makes that version the reference for subsequent comparisons. Each
version contains the configurations explicitly approved for that build.

```text
results/
  latest.json
  bambu-<release>-<commit>-<build-fingerprint>/
    collection.json
    <test-name>/
      <board>-<configuration-hash>/
        golden.json
.runs/
  batch_<id>/
    batch.json
    comparison.json
    run_<id>/
      metadata.json
      summary.csv
      cases/<test-name>.json
      logs/
      config_snapshot/
```

The build fingerprint covers the Bambu binary and installed MDPI runtime, so
local changes remain distinguishable even if the version banner is unchanged.
The test configuration includes the board/device, effective clock and Bambu
flags, source/input hashes, exact YAML, Ramulator library fingerprint and
compiler/simulator versions. Paths to temporary directories are normalized.
Different boards or parameters create separate configurations within a version.
A changed test, toolchain or memory configuration is reported as `NEW`.

Automatic comparison reports `UNCHANGED`, `IMPROVEMENT` or `REGRESSION` from the
simulated cycle count, and `FAIL` or `NEW` where appropriate. Any increase in
cycles is a regression; failures and regressions produce a nonzero runner exit
status. Changed read/write counts are included in `comparison.json`. Host wall
time and timestamps are not golden metrics. With no approved collection, all
successful cases are `NEW`; execution still succeeds.

Golden JSON files belong in Git; commit them after manual review. Create the
initial golden collection from a reviewed run. Historical measurements remain
available in [@BENfrost-20's repository](https://github.com/BENfrost-20/tests_bambu_ramulator).
Preflight checks validate required tools and the installed 64-bit Ramulator
library.

Use `./run_tests.sh --list-boards` to inspect board profiles and
`./run_tests.sh --clean-work --dry-run` to preview cleanup of old local build
artifacts. Cleanup preserves the golden collection.

## Repository checks

The [Repository tests workflow](.github/workflows/tests.yml) runs on pushes
to `main` and on pull requests targeting `main`. It checks the benchmark runner,
golden results, generated benchmark adapters, FPGA build scripts and AXI
validation tools on a GitHub-hosted Ubuntu runner.

The optional benchmark job runs on a dedicated, isolated Linux x86-64
self-hosted runner with the label `bambu-ramulator`. Configure `BAMBU_HLS`,
`RAMULATOR2_DIR` and optionally `J` in the runner environment, then set the
repository Actions variable `BAMBU_RUNNER_ENABLED` to `true`. The job runs the
real Bambu/Ramulator smoke cases on pushes to `main`. To run every benchmark,
use **Run workflow** on `main` and select the full benchmark option.

To run the benchmark runner and golden-result tests locally:

```sh
python3 -m unittest discover -s tools/tests -v
```
