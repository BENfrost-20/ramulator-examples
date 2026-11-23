# ETH HACC hacc-u55c-12

The 2026-11-20 series used the same traced U55C image as
[`hacc-u55c-08`](hacc-u55c-08.md). The preparation checked the target shell
`xilinx_u55c_gen3x16_xdma_base_3` and the runner checked the image's
SHA-256 before launching the probe. The image targets `HBM[0]` at a
100 MHz kernel clock. Each of the ten host invocations ran
`memory_probe_single` with n=1 and repetition 0.

The [recorded summary](../hbm_reference/evidence/probe_n1_u55c_12_repeat_20261120.tsv)
contains all ten observations. Every run measured 49 core and 50 drain
cycles, with a 26-cycle AR to R interval and a trace hash prefix matching
the previous reference trace. The
[cross-node comparison](../hbm_reference/PROBE.md#u55c-replication-on-hacc-u55c-12)
reports the observed range on each node.

The campaign's raw traces, logs, BDF and pre-run XRT inventory are retained
on HACC under a directory matching
`$HOME/hacc-probe-history/u55c-12-repeat.*`. The selected BDF, XRT version
and exact campaign directory are pending transcription into this record.
