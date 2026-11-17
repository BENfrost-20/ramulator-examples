# MachSuite

The suite runs the 19 official [MachSuite](https://github.com/breagen/MachSuite)
workloads through the repository's Bambu/Ramulator runner.

## Setup and execution

From the repository root, initialize the pinned source submodule:

```sh
git submodule update --init machsuite/sources
./machsuite/run.sh --list
./machsuite/run.sh --case machsuite_gemm_blocked --no-compare
./machsuite/run.sh --no-compare
# The global runner also includes this suite:
./run_tests.sh --suite machsuite --no-compare
```

`run.sh` prepares the AXI kernels and MDPI test support automatically before
calling the shared runner. It accepts the same board, configuration, selection
and golden-comparison options as the other suites. The default recipes use
Clang 13, 64-bit pointers, Verilator and Ramulator. Board, clock and memory YAML
come from the existing board profiles and command-line overrides.

Each pointer parameter uses a dedicated AXI interface, enabled by
`MACHSUITE_USE_AXI`. The test support registers the full buffer sizes with MDPI.
The algorithm bodies, dimensions and arithmetic come from the official sources.
Backprop's `offset` macro is temporarily hidden while parsing the AXI pragmas
and then restored. For `md_grid`, optimization of the native reference function
is disabled under Clang to avoid its Clang 13 loop-flatten crash; HLS optimization
and the function body remain unchanged.

## Workloads

| Family | Case suffixes after `machsuite_` |
|---|---|
| AES, backprop, KMP | `aes`, `backprop`, `kmp` |
| BFS | `bfs_bulk`, `bfs_queue` |
| FFT | `fft_strided`, `fft_transpose` |
| Matrix multiplication | `gemm_blocked`, `gemm_ncubed` |
| Molecular dynamics | `md_grid`, `md_knn` |
| Sequence alignment | `nw` |
| Sorting | `merge`, `radix` |
| Sparse matrix/vector multiplication | `spmv_crs`, `spmv_ellpack` |
| Stencils | `stencil2d`, `stencil3d` |
| Viterbi | `viterbi` |

## Sources and generated files

- `sources/` is the official MachSuite Git submodule, pinned to
  [`6236e593012cb86b0d2f08d9fb9ba0411ff989b4`](https://github.com/breagen/MachSuite/tree/6236e593012cb86b0d2f08d9fb9ba0411ff989b4).
  The upstream license is in `sources/LICENSE`.
- `cases.py` describes the top functions, ports, buffer fields and runner recipes.
- `prepare.py` generates `build/adapters/<family>/<variant>/kernel.c` and
  `local_support.c`. These local build files are ignored by Git. The source
  submodule remains unchanged.
- `references/backprop/` contains the dedicated backprop reference and its
  provenance. Every other workload uses the official reference.

The preparation and checker logic is adapted from
[@BENfrost-20's MachSuite integration](https://github.com/BENfrost-20/ramulator-examples/tree/363d3422ee753f72d27e50f2b2c0f45ea06788f9/machsuite).
The original Bambu/Ramulator benchmark integration is credited to
[@jesunsahariar](https://github.com/jesunsahariar).

To regenerate or check the adapters explicitly:

```sh
python3 machsuite/prepare.py
python3 machsuite/prepare.py --check
```

The generator verifies the source revision and rejects local modifications to
the submodule. Change the pinned source and review the adapters together when
updating MachSuite.

## Functional checks

Like Bambu's classic MachSuite runner, the recipes use
`-DBAMBU_SKIP_VERIFICATION`: correctness is checked against `check.data` by
the benchmark checker rather than the automatic MDPI comparison with native C.
The floating-point checkers retain the official absolute tolerance of `1e-6`.

The support code retains the official input parsing and reference comparison.
It additionally rejects non-finite floating outputs, checks sorted arrays exactly
and validates BFS vertex distances with an independent host traversal. Stencil
outputs are compared exactly.

Run native checks and the staging/checker regressions with:

```sh
python3 machsuite/validate.py
python3 machsuite/validate.py --case machsuite_backprop --upstream-reference
python3 -m unittest discover -s machsuite/tests -v
```

The second command diagnoses the known backprop reference difference and can
return failure; see `references/backprop/README.md`. Native runs are functional
checks. Bambu/Ramulator execution uses `run.sh` and records the same logs,
configuration snapshots and results as the other suites. Approve new golden
results through the existing manual collection workflow after reviewing runs.
