# ETH HACC hacc-u55c-08

## Host and accelerator

This record describes the board used for the
[one-word probe](../hbm_reference/PROBE.md) and its
[AXI-traced hardware run](../hbm_reference/board_trace/README.md). The
host and shell were checked on 2026-11-20 with `xrt-smi examine` and the
management-function `interface_uuids` attribute.

| Field | Value and source |
| --- | --- |
| Node | `hacc-u55c-08` |
| SSH hostname | `hacc-u55c-08.inf.ethz.ch`, using the ETH HACC SSH naming convention |
| Host | Dell PowerEdge R7515, x86-64, 32 CPU cores, 63896 MB host memory reported by XRT, Dell BIOS 2.6.6 |
| OS and kernel | Ubuntu 22.04.5 LTS, Linux `6.8.0-149-generic`, glibc 2.35 |
| XRT and drivers | `2.19.194` (2025.1), XRT, XOCL and XCLMGMT at `7d8151e6ee73c6ec2e99501a58c9c2eca6cc68ce` |
| XRT environment | `source /opt/hdev/cli/enable/xrt` |
| PCI address | User `0000:85:00.1`, reported ready, management `0000:85:00.0` |
| Shell and Logic UUID | `xilinx_u55c_gen3x16_xdma_base_3`, `97088961-FEAE-DA91-52A2-1D9DFD63CCEF`, observed |
| Deployment platform | `xilinx_u55c_gen3x16_xdma_3_202210_1`, recorded in the traced image metadata |
| Interface UUID | `B7AC1ABE-1E3E-1CB6-86D5-A81232452676`, reported twice by node sysfs and matches the traced image and AMD guide |
| Observed platform status | JTAG ID `0x14b7d093`, DDR count and size zero, P2P disabled, P2P I/O space required 32 GB |
| AMD platform memory | 16 GiB HBM2 across 32 pseudo-channels, 512 MiB each |

The card specification and shell metadata come from the
[AMD U55C product data sheet](https://docs.amd.com/r/en-US/ds978-u55c/Product-Details),
[AMD U55C base_3 platform guide](https://docs.amd.com/r/en-US/ug1120-alveo-platforms/U55C-Gen3x16-XDMA-base_3-Platform)
and [HACC access guide](https://github.com/fpgasystems/hacc#accessing-hacc).

## Runtime snapshot

On 2026-11-20, XRT reported only DMA metrics in the memory view, with
zero bytes transferred. The application `xclbin` UUID, its memory topology
and runtime clock values were unavailable in this snapshot. During the next
scheduled run, capture the platform and memory reports after the intended
image is loaded and match the reported image UUID to the artifact. Follow
the [observation procedure](README.md#capture-a-new-observation).

## Recorded probe build and run

| Field | Value |
| --- | --- |
| Build node and tools | `ferrandi-1`, Vivado/Vitis 2024.2 |
| Kernel and case | `fpga_kernel_1`, `memory_probe_single`, one word, repetition 0 |
| Vitis connectivity | `fpga_kernel_1.m_axi_0` to `HBM[0]` |
| Accelerator clock for cycle counters | 100 MHz (10 ns), `DATA_CLK` in the traced image report, requested and achieved |
| HBM AXI clock in the traced image metadata | `hbm_aclk`, 450 MHz |
| Additional shell clock in the traced image metadata | `KERNEL_CLK`, 500 MHz |
| Traced `xclbin` UUID | `c8b048ac-3871-ec1c-5567-c55afca19706` |
| Initial matched physical result | 49 core cycles and 50 drain cycles, on both original and traced images |
| Ten-run series on 2026-11-20 | 49–76 core cycles and 50–77 drain cycles, with variation in AR to R. [Per-run results](../hbm_reference/evidence/probe_n1_u55c_repeat_20261120.tsv) |

The retained trace bundle `probe-board-trace.uqm1l1` contains the
`xclbin-info.txt` and `manifest.json` used for the image details above. The
probe counters advance on the 100 MHz `ap_clk`. The original and traced
image hashes, reprogramming and reuse observations, and the historical
63/64-cycle result are documented in the
[probe evidence](../hbm_reference/evidence/probe_n1.json). The
[board AXI trace](../hbm_reference/evidence/probe_n1_u55c_axi.jsonl) records the
kernel-side handshakes.

The default [Bambu board profile](../../boards.json) targets 3.33 ns and uses
the [shared HBM2 YAML](../../smoke/configs/hbm2_32ch.yaml). The recorded
four-way comparison uses a 10 ns kernel period. The additional
[U55C 1800 MT/s YAML](../../smoke/configs/hbm2_u55c_1800.yaml) is an
experimental modeling input. The resident-shell report and traced image
metadata leave the physical DRAM transfer rate and controller timings
unverified. Keep those values labeled as model parameters for the simulation.
Use the [probe comparison](../hbm_reference/PROBE.md) for the measured
configurations and counter definitions.
