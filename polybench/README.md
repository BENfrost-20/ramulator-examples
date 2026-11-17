# PolyBench

`./run.sh` runs eight PolyBench/C kernels from the pinned `sources/` submodule.
It prepares kernel and testbench adapters automatically in `build/adapters/`.

From the repository root:

```sh
git submodule update --init polybench/sources
./polybench/run.sh --list
./polybench/run.sh --case polybench_trisolv_native_1ch
./polybench/run.sh --case polybench_trisolv_axi_tb_1ch
```

The 58 cases retain the existing names and configurations: `native` uses the
shared minimal bus with 1/2/4 channels; `axi` uses dedicated AXI interfaces with
1/2/4 channels; `axi_tb` uses one channel and compiles the utilities as testbench
code. The two original recorded cases remain `polybench_gemm` and `polybench_atax`.

## Sources and generation

`sources/` points to the original PolyBench/C 4.2.1 beta distribution on
[`ferrandi/PolyBenchC`](https://github.com/ferrandi/PolyBenchC/tree/d3a15bb1725afaaa33bcf3a4db6087ebf557c9b8),
commit `d3a15bb1725afaaa33bcf3a4db6087ebf557c9b8` on its `main` branch.
The source license and copyright notices are retained in the submodule and
in the generated files.

`prepare.py` generates each selected kernel and its testbench from the original
combined C source. It exports the kernel function and adds its declaration to
the generated header. Array interfaces use `m_axi` pragmas guarded by `USE_AXI`;
the runner enables them only for AXI profiles. The kernel bodies, initialization,
printing, allocation and cleanup remain unchanged. Shared utilities are used
directly from the submodule. Generated adapters are ignored by Git.

The generator checks the pinned source revision and rejects tracked source
modifications. To regenerate or verify the adapters:

```sh
python3 polybench/prepare.py
python3 polybench/prepare.py --check
python3 -m unittest discover -s polybench/tests -v
```

The tests compare the dumped outputs of every original kernel with both generated
profiles and verify staging for all 58 runner cases. The AXI integration follows
[@jesunsahariar's Bambu/Ramulator work](https://github.com/jesunsahariar/bambu-ramulator-release)
and [@BENfrost-20's test collection](https://github.com/BENfrost-20/tests_bambu_ramulator).

| Kernel | Directory in the source submodule |
|---|---|
| `gemm` | `linear-algebra/blas/gemm` |
| `atax` | `linear-algebra/kernels/atax` |
| `bicg` | `linear-algebra/kernels/bicg` |
| `mvt` | `linear-algebra/kernels/mvt` |
| `trisolv` | `linear-algebra/solvers/trisolv` |
| `jacobi-1d` | `stencils/jacobi-1d` |
| `jacobi-2d` | `stencils/jacobi-2d` |
| `floyd-warshall` | `medley/floyd-warshall` |
