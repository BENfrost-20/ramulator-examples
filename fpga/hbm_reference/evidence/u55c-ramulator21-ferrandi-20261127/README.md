# U55C HBM2 replay on Ferrandi · 27 November 2026

The probe issued 1,000 four-byte single-beat reads to a fixed address with one
request outstanding. Latency is measured from the kernel-side AXI AR handshake
to R at 100 MHz. RVALID and R coincide for every archived read. The hardware
reference is the [U55C-08 acquisition on HBM[0]](../spaced_reads_u55c_08.csv).

The Ramulator 2.0 and 2.1 runs used identical `fpga_kernel.sv` and `control.sv`
as verified by SHA-256. Each used warm-up lengths of 0, 97, 195 and 292 kernel
cycles. The warm-up lengths identify replay runs. The absolute phase inside the
DRAM refresh period can differ between simulator versions.

| Series | Source and configuration |
| --- | --- |
| Ramulator 2.0 | Ferrandi run `$HOME/hbm-refresh-check.QDlw6Q/spaced-ramulator.Cpi261`. Version `9a8ed85` with the recorded channel-scoped HBM2 refresh patch, at 1800 MT/s. The [phase 292 CSV](../spaced_reads_u55c_ramulator_phase292.csv) already tracked in Git is byte-identical to the server copy. |
| Ramulator 2.1 | Ferrandi run `$HOME/thesis/toolchain-ramulator21-dca0351/u55c-replay.3ywbP9`. Ramulator `3fec8f1cbddf75f4005426fd206342096612d100`, examples commit `bc18348b9710347d136cc466c3b7d65d2516a411`, Verilator 5.052, GCC 13.1 and Python 3.11.18. The HBM2 controller refreshes at pseudochannel scope. |
| Ramulator 2.1 profiles | `matched-rate-1800` is the experimental 1800 MT/s profile. It uses the 2.1 timing constraints adapted to that rate. `bambu-2000` is the 2000 MT/s Bambu U55C profile with command recording. |

The fixed RTL replay links directly to Ramulator. Bambu MDPI transport
calibration is outside this experiment. These measurements compare complete
model configurations. They do not isolate the effects of the simulator
revision, timing parameters, or refresh scope.

## Results

| Series, warm-up 292 | P50 | P90 | P95 | P99 | Maximum | Median shift used for alignment |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| U55C hardware | 26 | 26 | 47 | 59 | 66 | — |
| Ramulator 2.0, 1800 MT/s | 4 | 4 | 24 | 37 | 38 | +22 |
| Ramulator 2.1, 1800 MT/s | 5 | 6 | 23 | 38 | 41 | +21 |
| Ramulator 2.1, 2000 MT/s | 5 | 7 | 24 | 38 | 41 | +21 |

Values are kernel cycles. The maximum empirical cumulative distribution gap
after median alignment is 10.7 percentage points for 2.0 at each warm-up,
2.5–3.2 for 2.1 at 1800 MT/s, and 2.3–3.2 for 2.1 at 2000 MT/s.
The P99 residual is identical for all model configurations at each warm-up.
The P95 residual at 1800 MT/s in phase 292 increases from one to three cycles.
The unshifted median still differs from hardware by 21 cycles with 2.1.
All eight 2.1 runs logged 1,000 read commands on channel 0, pseudochannel 0.
The median refresh interval there was about 3.9 µs for both data rates.

## Archive and figures

- The versioned subdirectories retain original CSVs, effective YAMLs and
  server summaries. `ramulator-2.1/provenance.txt` identifies the pinned
  dependency and fingerprints the library and replay inputs.
- `diagnostics.tar.gz` contains the original AXI traces and phase logs for
  both versions, the 2.0 build log and all 2.1 per-channel command traces.
  The 2.1 Verilator build log is archived separately. The 12,000 simulated
  read latencies were cross-checked against the AXI events.
- The three figures are available as PNG and SVG. Run `python3 plot.py`
  with Matplotlib from this directory. The script validates the original
  CSVs against the server summaries and regenerates the figures.
- Run `sha256sum -c SHA256SUMS` from this directory to verify the archive.

[Latency distributions](figures/u55c-latency-cdf.svg) ·
[Latency quantiles](figures/u55c-latency-quantiles.svg) ·
[Warm-up sensitivity](figures/u55c-warm-up-sensitivity.svg)
