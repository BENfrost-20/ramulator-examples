# One-word U55C probe with the AMD HBM behavioral model

This VCS test runs memory_probe_single with n=1 and repetition 0. It verifies
the five RTL hashes against those recorded for the XO used on the U55C. It
writes the 64-bit base, N and COMMAND via AXI-Lite and reads the wrapper's
64-bit CORE_CYCLES and DRAIN_CYCLES registers. The input is the little-endian
word 0x00000003. The oracle expects 0x13579bdc and 256 bytes of 0xa5 on each
side. The loader writes the guarded 516-byte region and verifies it after
drain, outside the timed interval. It idles for 16 kernel cycles before the
launch sequence. The board host transfers and checks its entire 64 KiB slab,
so memory preconditioning differs.

The probe uses S_A of the validated SmartConnect bridge and the loader uses
S_LOAD. S_B and S_C are idle. The bench measures the kernel side at 100 MHz
and uses the reference HBM AXI period of 2222 ps. The probe address is
0x1200000100 on the kernel side and 0x01000100 in the AMD model, with the
same translation across the guarded region. The bridge adapts the 1-bit AXI
IDs to 6 bits. The HBM model sees the aligned 256-bit beat and original byte
lanes. The deployed MinimalAXI4Adapter leaves USER and REGION undriven, and
the reference bridge omits them.

## Run on Ferrandi 1

Run from the repository root. For the standalone source bundle, use its
path to run_probe.sh in place of the repository path below.

    (
      set -eu
      repo="$HOME/thesis/ramulator-examples"
      prepared="$repo/.fpga/bitstream-xfTkobFQ/probe-single"
      work=$(mktemp -d "$repo/.fpga/probe-vcs.XXXXXX")
      printf 'VCS output directory: %s\n' "$work/run"
      bash "$repo/fpga/hbm_reference/run_probe.sh" --prepared "$prepared" --output "$work/run"
      cat "$work/run/vcs-results.jsonl" \
          "$work/run/vcs-axi.jsonl" \
          "$work/run/vcs-hbm-axi.jsonl"
    )

By default, the driver reads the exports from the passing vector-add run at
~/thesis/hbm-reference-smoke/integration-runs/run_20261117_191951_121861.
Use --vendor-run for another export of the same bridge and HBM
configuration. The driver compiles a private vendor library set using the
existing Vivado base libraries. The original exports, prepared build, source
projects and results are reused as read-only inputs. A fresh output directory
is required for each attempt.

The run records the input, oracle, RTL hashes, testbench and vendor settings
in its output directory. A partial run retains its build and simulation logs
under vcs/. FUNCTIONAL_PASS requires the correct word and guard readback,
the expected AXI traffic on both sides and coherent wrapper counters.

## Native Bambu runs on Ferrandi 1

From the repository root, use the same source, input, compiler and 10 ns
clock target for each native mode.

    bash fpga/hbm_reference/run_bambu_native.sh
    bash fpga/hbm_reference/run_bambu_native.sh 15
    bash fpga/hbm_reference/run_bambu_native.sh --ramulator-config smoke/configs/hbm2_32ch.yaml
    bash fpga/hbm_reference/run_bambu_native.sh --ramulator-config fpga/hbm_reference/spaced_reads/ramulator/ramulator21/profiles/matched-rate-1800.yaml

The argument 15 sets both memory delays to 15 cycles. Ramulator runs retain
a private copy of the selected YAML and preserve its modeled channel count.
All modes save the native output XML and simulation log under .fpga.
For the separate same-wrapper Ramulator experiment, see the
[FPGA guide](../README.md#ramulator-timing-with-the-deployed-wrapper).

## Compare the runs

All runs passed with n=1, repetition 0, and input word 3. Native Bambu
counts its own testbench interval. The wrapper counters and AXI intervals
use rising kernel clock edges.

| Run | Native Bambu cycles | Wrapper core/drain |
|---|---:|---:|
| Bambu with default memory delays | 9 | |
| Bambu with 15-cycle read and write delays | 34 | |
| Bambu + Ramulator, HBM2 2 Gbps profile | 13 | |
| Bambu + Ramulator, experimental U55C 1800 MT/s profile | 12 | |
| Verilator wrapper + Ramulator, HBM2 2 Gbps profile | | 11/12 |
| Verilator wrapper + Ramulator, experimental U55C 1800 MT/s profile | | 10/11 |
| VCS + AMD HBM | | 73/74 |
| Physical U55C, matched original and traced runs | | 49/50 |

The native MDPI read callback takes four kernel cycles using the 2 Gbps
profile and three using the experimental 1800 MT/s profile. The two profiles
also differ in clock ratio and geometry. The native runs measure their combined
effect.

A same-binary replay on Ferrandi changed only the YAML from the 2 Gbps
profile to the U55C 1800 MT/s profile. Both runs submitted address
`0x40000000` and took 19 DRAM ticks from acceptance to callback.
At five and nine DRAM ticks per kernel cycle, the AXI read took five
and four kernel cycles, respectively. AW/W to B stayed at one cycle.
The gap to the 49/50-cycle hardware reference increased from 38 to 39
cycles. This replay leaves the AXI path and write-response modeling as
separate issues.

For VCS versus the traced U55C, AR to R takes 37 versus 26 cycles. The
interval from R to the later of AW/W takes 2 versus 5 cycles. The later
of AW/W to B takes 31 versus 15 cycles. Those intervals account for the
24-cycle difference. The earlier physical measurement of 63/64 was recorded
in a separate reservation. Consecutive runs without reprogramming still
measured 49/50 on the later reservation.

[Recorded measurements](evidence/probe_n1.json),
[physical AXI trace](evidence/probe_n1_u55c_axi.jsonl) and
[U55C trace build and deployment](board_trace/README.md).

### U55C repeated runs on 2026-11-20

On `hacc-u55c-08` (`0000:85:00.1`), ten consecutive host invocations ran
the same traced image from `probe-board-trace.uqm1l1`. Each invocation
ran `memory_probe_single` with n=1 and repetition 0 at a 100 MHz kernel
clock. The [ten-run summary](evidence/probe_n1_u55c_repeat_20261120.tsv)
preserves each result and the first 12 hexadecimal digits of the
SHA-256 of its AXI trace.

Seven runs reproduced 49 core and 50 drain cycles. Their trace hash
prefix matches the [previous AXI trace](evidence/probe_n1_u55c_axi.jsonl).
Runs 6–8 measured 76/77, 75/76 and 67/68 cycles. AR to R took 53, 52
and 44 cycles in those runs, compared with 26 in the other seven.
The increase in AR to R accounts for the entire increase in both
wrapper counters. The later AW/W to B interval stayed at 15 cycles
and the W VALID-to-handshake interval stayed at 3 cycles.

The first XRT load call took 6935.8 ms. The other calls took 15.0–16.5 ms
and included both timing outcomes. XRT load time is outside the wrapper
counters. The measurements locate the variation between the kernel-side
read address and response handshakes. Its cause within the shell and
memory path remains open. The VCS reference is 73/74 cycles, within
the observed range of 49–76 core and 50–77 drain cycles. The historical
63/64 result remains a separate observation.

The read-channel events in runs 5–9 separate the time to first valid
data from the wait for the kernel to accept it. All five requests used
kernel-side AXI address `0x100` and ID 0.

| Run | AR to RVALID (cycles) | RVALID to R (cycles) |
| ---: | ---: | ---: |
| 5 | 26 | 0 |
| 6 | 53 | 0 |
| 7 | 52 | 0 |
| 8 | 44 | 0 |
| 9 | 26 | 0 |

Each response was accepted on the cycle when it became valid. The
additional 18–27 cycles accrued before RVALID at the kernel interface.
The trace covers the path through the shell and HBM together. Its
timestamps leave refresh and other internal sources of delay unresolved.

The run folder on HACC is
`$HOME/hacc-probe-history/u55c-08-repeat.elKUUu`. It holds the full per-run
traces, host logs and comparison reports. The preceding HACC runs were
archived there as `previous-runs.tar.gz`, with a checksum and file index.

### U55C replication on hacc-u55c-12

On 2026-11-20 the same traced `xclbin`, bank mapping, clock and one-word
probe were run ten times on `hacc-u55c-12`. Each trace's SHA-256 prefix
matched the [previous reference trace](evidence/probe_n1_u55c_axi.jsonl).
The first XRT load call took 7199.7 ms and the following nine took
14.6–18.5 ms. The FPGA counters stayed at 49 core and 50 drain cycles.

| HACC node | Runs at 49/50 | Core cycle range | AR to R cycle range | Later AW/W to B cycles | W VALID-to-handshake cycles |
| --- | ---: | ---: | ---: | ---: | ---: |
| `hacc-u55c-08` | 7/10 | 49–76 | 26–53 | 15 | 3 |
| `hacc-u55c-12` | 10/10 | 49 | 26 | 15 | 3 |

The 49/50 case was reproduced on both nodes. The three longer reads were
observed on `hacc-u55c-08`. These ten-run series leave the frequency and
cause of longer reads on each node open.
[U55C-08 summary](evidence/probe_n1_u55c_repeat_20261120.tsv) ·
[U55C-12 summary](evidence/probe_n1_u55c_12_repeat_20261120.tsv) ·
[U55C-12 node record](../hardware/hacc-u55c-12.md)

## Spaced HBM reads on hacc-u55c-08

A separate image issued 1,000 single-beat reads at one address in HBM[0],
with one read outstanding and variable gaps. The 100 MHz kernel recorded
each AR and R timestamp. The response channel was ready throughout each
read response, and RVALID and R share a timestamp for all samples.
[Per-read timestamps](evidence/spaced_reads_u55c_08.csv)

Folding AR timestamps modulo 390 kernel cycles (3.9 µs) places all 93
reads above 26 cycles in phases 262–299. There were 94 requests in that
window and 906 outside it. Slow responses became valid in phases 325–329.
The 3.9 µs recurrence matches the base HBM refresh interval documented
by AMD. This is evidence of a periodic service delay in this acquisition.
Attribution to refresh requires visibility into controller activity or
a controlled comparison that changes its refresh schedule.
[AMD HBM refresh timing](https://docs.amd.com/r/en-US/pg276-axi-hbm/Raw-Throughput-Evaluation)

## Spaced reads in Ramulator 2.1

Use the [Ferrandi replay](spaced_reads/ramulator/ramulator21/README.md)
for the current U55C experiment. It runs the same 1,000-read RTL against
the native 1800 and 2000 MT/s profiles and compares against the recorded
hardware and Ramulator 2.0 traces. The [27 November 2026 Ferrandi archive](evidence/u55c-ramulator21-ferrandi-20261127/README.md) contains the raw reads,
effective profiles, diagnostics and English comparison figures.

## Historical Ferrandi Ramulator 2.0 results

The same read generator ran in Verilator against the Ferrandi Ramulator
library with the 1800 MT/s U55C profile, `AllBank` and nominal tREFI of
3.9 µs. Each of four initial offsets (0, 97, 195 and 292 kernel cycles)
completed 1,000 reads. The observed quantiles were identical across
the four offsets.

| Target | p50 | p90 | p95 | p99 | Maximum |
| --- | ---: | ---: | ---: | ---: | ---: |
| HACC U55C hardware | 26 | 26 | 47 | 59 | 66 |
| Ferrandi Ramulator | 3 | 3 | 3 | 3 | 4 |

Adding 23 cycles to align the medians leaves hardware-minus-model
residuals of 21 cycles at p95 and 33 cycles at p99, and a maximum
empirical CDF gap of 10.7 percentage points. These are results for the
original library and configuration.

In the pinned Ferrandi source, the AllBank manager requests the size of
the rank level and schedules maintenance inside a loop over those ranks.
HBM2 has pseudochannels in its organization and the lookup for rank
returns -1. The loop therefore issues no refresh requests on that source
path, even with AllBank selected in YAML. A follow-up build needs to emit
and trace REFab on the addressed channel before using these runs to
calibrate refresh-related latency.
[Ferrandi refresh implementation](https://github.com/ferrandi/ramulator2/blob/9a8ed857455d041524043bc5fb45eb7f07e6a731/src/dram_controller/impl/refresh/all_bank_refresh.cpp)

The follow-up build enabled channel-scoped HBM2 refresh and recorded
issued REFab commands. Each phase again completed 1,000 reads. Channel 0
issued 1,502–1,503 refresh commands per phase. The [follow-up comparison](evidence/spaced_reads_u55c_ramulator_refresh.tsv)
records the command counts and quantiles. With refresh enabled, all
four runs had a median of 4 cycles, p95 of 21–24, p99 of 36–37 and a
maximum of 38. Adding 22 cycles to align the medians leaves 1–4 cycles
of hardware-minus-model residual at p95, 0–1 at p99 and 6 at the maximum.
The maximum empirical CDF gap stays at 10.7 percentage points in every
phase. These runs reproduce a long read-latency tail. The remaining
distribution gap and the cause of the median offset need separate
investigation.

The follow-up results were reported from
`$HOME/hbm-refresh-check.QDlw6Q/spaced-ramulator.Cpi261` on Ferrandi 1.
The archived table reproduces the reported quantiles, alignment results
and REFab counts. The per-read simulator outputs and command logs remain
in the run directory.

The phase-292 [per-read latency CSV](evidence/spaced_reads_u55c_ramulator_phase292.csv)
and [channel 0 REFab ticks](evidence/spaced_reads_u55c_ramulator_phase292_refab.tsv)
were recovered from the Ferrandi output (Verilator 5.052). The
simulation has 97 reads above its 4-cycle median. The REFab timestamps
track an interval of 3,511 DRAM ticks (390.11 kernel cycles at a 9:1
clock ratio). For the phase overlay, each series was folded using its
own period, the first phase of the long-latency window was aligned
horizontally, and 22 cycles were added to the simulated latencies.
The 10.7-point empirical CDF gap in this series occurs at 24 cycles.
Hardware has 107 reads at 24 cycles and the aligned model starts at
25 cycles.

## Spaced-read replication on hacc-u55c-12

On 2026-11-23, three acquisitions of 1,000 reads each ran on
`hacc-u55c-12` (user PCI BDF `0000:81:00.1`) using the original
`hbm-spaced-hacc.tar.gz` bundle. The probe measures AR handshake to
read response at 100 MHz with the kernel AXI port mapped to HBM[0].

| Node and run | p50 | p95 | p99 | Maximum | Samples above p50 |
| --- | ---: | ---: | ---: | ---: | ---: |
| hacc-u55c-08 reference | 26 | 47 | 59 | 66 | 93 / 1,000 |
| hacc-u55c-12 run 1 | 26 | 46 | 59 | 66 | 93 / 1,000 |
| hacc-u55c-12 run 2 | 26 | 47 | 59 | 66 | 94 / 1,000 |
| hacc-u55c-12 run 3 | 26 | 49 | 60 | 66 | 116 / 1,000 |

Latencies are in kernel cycles. The 26-cycle median exceeds the
4-cycle median of the refresh-enabled Ramulator reference (phase 292)
by 22 cycles (220 ns) on both measured boards. The fraction of reads
above the median ranged from 9.3% to 11.6% on hacc-u55c-12.

The [summary TSV](evidence/spaced_reads_u55c_12_summary_20261123.tsv)
transcribes the HACC terminal output. Each archived CSV contains
1,000 reads and reproduces the corresponding reported statistics.
[Run 1](evidence/spaced_reads_u55c_12_run1_20261123.csv) ·
[Run 2](evidence/spaced_reads_u55c_12_run2_20261123.csv) ·
[Run 3](evidence/spaced_reads_u55c_12_run3_20261123.csv)

## Build and run the U280 HBM probe

The U280 build synthesizes the same 1,000-read RTL for the U280 part
with Vivado and Vitis 2022.2. The link uses a 100 MHz kernel clock,
`xilinx_u280_gen3x16_xdma_1_202211_1`, and `HBM[0]` for
`fpga_kernel_1.m_axi_0`.

On Ferrandi 1, start or attach to a tmux session:

    tmux new-session -A -s spaced-u280-hbm

From inside the session:

    cd "$HOME/thesis/ramulator-examples"
    bash fpga/hbm_reference/spaced_reads/u55c/build.sh u280

Detach with Ctrl+B, then D. Reattach with
`tmux attach -t spaced-u280-hbm`. The build writes under
`.fpga/spaced-u280-hbm.*` and prints `HACC_BUNDLE:` after the
routed timing checks and the image interface UUID and kernel clock
checks pass. Transfer the reported `hbm-spaced-u280-hacc.tar.gz`
to the shared HACC home using the [deployment guide](../HACC.md).

On the reserved legacy HACC node, check the current U280 user-function
BDF and its shell before loading the image:

    source /opt/hdev/cli/enable/xrt
    xrt_tool=$(command -v xrt-smi || command -v xbutil)
    "$xrt_tool" examine
    read -r -p 'U280 user-function PCI BDF: ' bdf
    "$xrt_tool" examine -d "$bdf" -r platform

For the `xilinx_u280_gen3x16_xdma_base_1` shell, unpack and run the bundle:

    run_dir=$(mktemp -d "$HOME/hacc-u280-spaced.XXXXXX")
    cd "$run_dir"
    tar -xzf "$HOME/hbm-spaced-u280-hacc.tar.gz" &&
      sha256sum -c SHA256SUMS &&
      python3 -B host-build.py &&
      env -u XCL_EMULATION_MODE ./host fpga_kernel.xclbin "$bdf" reads-1.csv

The host checks all responses and prints `PASS 1000 AXI reads`.
The U55C reference measured 26 cycles in hardware and 4 in its
Ramulator model. The U280-specific comparison follows below.

### U280 HBM measurements on HACC

The same U280 image ran three 1,000-read acquisitions on each of
`hacc-legacy-01` and `hacc-legacy-02`. The linked image reports a
100 MHz kernel clock and a 450 MHz `hbm_aclk`. Each run accessed
`HBM[0]`. The `fpga_kernel.xclbin` SHA-256 recorded in the bundle is
`c470796422cdff1c68f92fd39c7894138fb64aa63fe39fac6b3044d58040f11c`.
Latencies are in kernel cycles.

| Node | Run | p50 | p95 | p99 | Maximum | Samples above p50 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| hacc-legacy-01 | [1](evidence/spaced_reads_u280_hbm_legacy01_run1.csv) | 26 | 35 | 51 | 57 | 74 / 1,000 |
| hacc-legacy-01 | [2](evidence/spaced_reads_u280_hbm_legacy01_run2.csv) | 26 | 39 | 52 | 57 | 93 / 1,000 |
| hacc-legacy-01 | [3](evidence/spaced_reads_u280_hbm_legacy01_run3.csv) | 26 | 41 | 52 | 57 | 101 / 1,000 |
| hacc-legacy-02 | [1](evidence/spaced_reads_u280_hbm_legacy02_run1.csv) | 26 | 40 | 52 | 57 | 100 / 1,000 |
| hacc-legacy-02 | [2](evidence/spaced_reads_u280_hbm_legacy02_run2.csv) | 26 | 38 | 52 | 57 | 80 / 1,000 |
| hacc-legacy-02 | [3](evidence/spaced_reads_u280_hbm_legacy02_run3.csv) | 26 | 39 | 52 | 57 | 82 / 1,000 |

Pooling the six U280 runs and four U55C hardware runs gives p50 of 26
cycles on both boards. The U280 p95/p99 is 39/52 cycles, compared
with 47/59 on the U55C. The observed maxima are 57 and 66 cycles,
respectively. The U280 image was built with Vivado/Vitis 2022.2
and the U55C images with 2024.2.
[Hardware latency distributions](evidence/figures/confronto-latenze-u280-u55c-hbm.png)

### U280 Ramulator comparison

All six hardware acquisitions measured a median of 26 kernel cycles.
Each of the four simulated phases measured 4 cycles. The median gap is
22 cycles (220 ns at 100 MHz). Across the pooled samples the hardware
p95/p99/maximum were 39/52/57 cycles. After adding 22 cycles the model
gave 32/48/51. The simulations issued 1,499–1,500 channel-0 REFab commands
per phase with the [U280 configuration](spaced_reads/ramulator/hbm2_u280_1800.yaml).

[Latency distributions](evidence/figures/u280-distribuzione-latenze.png) ·
[Aligned latency tail](evidence/figures/u280-coda-latenze.png) ·
[Per-run comparisons](evidence/spaced_reads_u280_ramulator_comparison.txt)

### Matched 2022.2 bitstream builds

The [tmux launcher](spaced_reads/campaign-2022.2/campaign.sh) builds U280
DDR[0], U250 DDR[0] and U55C HBM[0] with a 100 MHz kernel. To reproduce
the launch layout, set `campaign` to a fresh directory directly under
the successful U280 HBM build. From the repository root run:

```bash
mkdir -p "$campaign/src"
src=fpga/hbm_reference/spaced_reads
cp "$src/campaign-2022.2/campaign.sh" "$campaign/"
cp "$src/u55c/"{fpga_kernel.sv,control.sv,registers.tcl,package.tcl,check_implementation.tcl,host.cpp,host-build.py,host-flags.json} "$campaign/src/"
git rev-parse HEAD > "$campaign/source-revision.txt"
bash "$campaign/campaign.sh" start
```

The original campaign used RTL from revision 365c5c6. U280 reuses the HBM
kernel XO and IP cache and runs a new DDR link. Each target writes its
own logs and routed timing checks before creating a HACC bundle.

### U280 DDR4 Ramulator comparison

The Vivado 2022.2 `DDR[0]` XCI defines the
[DDR4 profile](spaced_reads/ramulator/u280_ddr4_2022_2.yaml), with a
single rank of 8 Gbit ×4 devices, DDR4-2400, `nRFC=421` and
`nREFI=9363`. The generic Ramulator scheduler and address mapper are
approximations of the hardware controller.

The four simulation traces contain 1,000 reads each:
[phase 0](evidence/spaced_reads_u280_ddr_ramulator_xci_phase0.csv),
[phase 97](evidence/spaced_reads_u280_ddr_ramulator_xci_phase97.csv),
[phase 195](evidence/spaced_reads_u280_ddr_ramulator_xci_phase195.csv)
and [phase 292](evidence/spaced_reads_u280_ddr_ramulator_xci_phase292.csv).
The three hardware runs on `hacc-legacy-01` gave a median of 28 kernel
cycles. Each simulated phase gave 5 cycles, for a gap of 23 cycles
(230 ns at 100 MHz). The [aligned latency figure](evidence/figures/u280-ddr-hw-vs-ramulator-plus23.png)
overlays hardware and Ramulator after adding 23 cycles to the simulated
latencies. The pooled p99 is 62 cycles in hardware and 52 in the aligned model.

### U250 DDR4 Ramulator comparison

The U250 DDR[0] bitstream used a fixed 100 MHz kernel clock. Three
hardware captures on `hacc-legacy-02` and four simulated phases contain
1,000 reads each. The [U250 XCI profile](spaced_reads/ramulator/u250_ddr4_2022_2.yaml)
uses the same DRAM geometry and timing values as the U280 DDR4 profile.
The comparison pools samples within each series. Values are kernel cycles.

| Series | p50 | p90 | p95 | p99 | Maximum |
| --- | ---: | ---: | ---: | ---: | ---: |
| U250 hardware | 28 | 30 | 34 | 63 | 72 |
| Ramulator | 5 | 5 | 5 | 29 | 41 |
| Ramulator +23 cycles | 28 | 28 | 28 | 52 | 64 |

[Aligned latency figure](evidence/figures/u250-ddr-hw-vs-ramulator-plus23.png) ·
[Per-run comparison](evidence/spaced_reads_u250_ddr_ramulator_comparison.tsv)

[U250 replay and diagnostic sources](spaced_reads/ramulator/u250_ddr_diagnostics/README.md)
and [diagnostic evidence](evidence/u250-ddr-diagnostics/README.md) record
the command trace and refresh-interval sensitivity runs.

### Additional U280 HBM runs on legacy-01

Three additional 2022.2 acquisitions on 2026-11-24 are available
[run 1](evidence/spaced_reads_u280_hbm_legacy01_run1_20261124.csv),
[run 2](evidence/spaced_reads_u280_hbm_legacy01_run2_20261124.csv) and
[run 3](evidence/spaced_reads_u280_hbm_legacy01_run3_20261124.csv).

### U280 DDR4 row locality

The [probe sources](spaced_reads/u280_ddr_controller/README.md) implement
three matched address patterns with one outstanding AXI read. The
[local Ramulator CSVs](evidence/u280-ddr-row-locality/README.md) record
four refresh offsets per pattern. The corresponding HACC run is pending.

## Spaced reads in VCS with the AMD HBM model

The same spaced-read RTL completed the 100-read smoke run and the
1,000-read measurement in VCS X-2025.06-SP2 with the AMD HBM model and
the previously validated SmartConnect bridge. The smoke run took
727.50 seconds of wall time. Both completed CSVs and the comparison
were reported under `$HOME/hbm-spaced-vcs.TZTRqn/run` on Ferrandi 1.

| Series | p50 | p90 | p95 | p99 | Maximum |
| --- | ---: | ---: | ---: | ---: | ---: |
| U55C hardware | 26 | 26 | 47 | 59 | 66 |
| VCS + AMD HBM | 38 | 56 | 66 | 75 | 78 |
| VCS latency minus 12 cycles | 26 | 44 | 54 | 63 | 66 |

Quantiles are in kernel cycles. After aligning the medians, VCS
exceeds the hardware by 18 cycles at p90, 7 at p95 and 4 at p99.

The [1,000-read VCS trace](evidence/spaced_reads_u55c_vcs.csv) shows 204
reads above its 38-cycle median, against 93 above the 26-cycle median on
hardware and 97 above the 4-cycle median in Ramulator phase 292. Fitting
the phase concentration of the VCS requests above the median gives
approximately 194.89 kernel cycles (1.949 µs). Hardware and the corrected
Ramulator run have a slow window roughly every 390 kernel cycles
(3.9 µs). Two simulated VCS windows therefore fit within one hardware
period. Both simulations have RVALID and R on the same cycle for every
request.

The reference XCI enables temperature compensation of the refresh
interval via `USER_MC0_REF_TEMP_COMP` and the bench leaves
`DRAM_0_STAT_TEMP` unobserved. AMD documents a base 3.9 µs period and a
1.95 µs period with temperature compensation in the higher temperature
range. The VCS cadence is consistent with the shorter regime. The AMD
model's refresh configuration and simulated temperature need a
controlled check to establish the cause.
[AMD refresh timing](https://docs.amd.com/r/en-US/pg276-axi-hbm/Raw-Throughput-Evaluation) ·
[Refresh compensation option](https://docs.amd.com/r/en-US/pg276-axi-hbm/Reorder-Refresh-and-Power-Savings-Options-Tab)
