# U55C HBM2 replay on Ferrandi · 27 November 2026

The probe issued 1,000 four-byte single-beat reads to a fixed address with one
request outstanding. Latency is measured from the kernel-side AXI AR handshake
to R at 100 MHz. RVALID and R coincide for every archived read. The hardware
reference is the [U55C-08 acquisition on HBM[0]](../spaced_reads_u55c_08.csv).

The Ramulator 2.0 and 2.1 runs used identical `fpga_kernel.sv` and `control.sv`
as verified by SHA-256.

## Warm-up

After reset and AXI-Lite setup, the testbench waits 0, 97, 195 or 292 extra
kernel cycles before starting the probe. The DRAM model keeps ticking during
this idle period. Varying the wait moves the first measured read relative
to the roughly 3.9 µs refresh schedule. The wait is outside the read
latency measurement. Warm-up 0 starts the probe immediately after setup.
The same wait length can have a different absolute refresh phase in each
simulator configuration.

| Series | Source and configuration |
| --- | --- |
| Ramulator 2.0 | Ferrandi run `$HOME/hbm-refresh-check.QDlw6Q/spaced-ramulator.Cpi261`. Version `9a8ed85` with the recorded channel-scoped HBM2 refresh patch, at 1800 MT/s. The [phase 292 CSV](../spaced_reads_u55c_ramulator_phase292.csv) already tracked in Git is byte-identical to the server copy. |
| Ramulator 2.1 | Ferrandi run `$HOME/thesis/toolchain-ramulator21-dca0351/u55c-replay.3ywbP9`. Ramulator `3fec8f1cbddf75f4005426fd206342096612d100`, examples commit `bc18348b9710347d136cc466c3b7d65d2516a411`, Verilator 5.052, GCC 13.1 and Python 3.11.18. The HBM2 controller refreshes at pseudochannel scope. |
| Ramulator 2.1 profiles | `matched-rate-1800` is the experimental 1800 MT/s profile. It uses the 2.1 timing constraints adapted to that rate. `bambu-2000` is the 2000 MT/s Bambu U55C profile with command recording. |

The fixed RTL replay links directly to Ramulator. Bambu MDPI transport
calibration is outside this experiment. These measurements compare complete
model configurations. They do not isolate the effects of the simulator
revision, timing parameters, or refresh scope.

## Evidence files

- The effective Ramulator 2.1 profiles are the
  [1800 MT/s profile](../../spaced_reads/ramulator/ramulator21/profiles/matched-rate-1800.yaml)
  and the [2000 MT/s profile](../../spaced_reads/ramulator/ramulator21/profiles/bambu-2000.yaml).
  Their original hashes are recorded in the
  [Ferrandi manifest](ramulator-2.1/provenance.txt).
- The versioned directories contain the original latency CSVs. The
  [2.0 phase-292 CSV](../spaced_reads_u55c_ramulator_phase292.csv) is shared
  with the historical evidence. The [refresh cadence](ramulator-2.1/refresh-cadence.tsv)
  records the command counts and intervals from the eight 2.1 replays.
- `diagnostics.tar.gz` contains both versions' AXI traces and phase logs,
  plus the 2.0 build log and the 2.1 per-channel command traces.
  `ramulator-2.1/verilator-build.log.gz` captures the 2.1 Verilator build.
  Run `sha256sum -c SHA256SUMS` from this directory to verify the archive.

Comparative statistics, interpretation and all figures are in the
[Alveo memory latency report](../alveo-ramulator21-ferrandi-20261127/README.md).
