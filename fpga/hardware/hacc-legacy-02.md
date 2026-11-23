# ETH HACC hacc-legacy-02

## Host observation

The observation on 2026-11-20 used `examine`, `examine -r platform`,
`examine -r memory`, and the management-function `interface_uuids` attribute.
Both cards reported `Ready` in the XRT inventory.

| Field | Observed value |
| --- | --- |
| Node | `hacc-legacy-02` |
| SSH hostname | `hacc-legacy-02.inf.ethz.ch` |
| Host | Dell PowerEdge R740, x86-64, 32 CPU cores, 385570 MB host memory reported by XRT |
| OS and kernel | Ubuntu 22.04.5 LTS, Linux `5.15.0-204-generic`, glibc 2.35 |
| XRT and drivers | `2.16.204` (2023.2), XRT, XOCL and XCLMGMT at `fa4c0045003fed0acea4593788dce5ef6d0b66ee` |
| XRT environment | `source /opt/hdev/cli/enable/xrt` |

## Alveo U250

| Field | Value and source |
| --- | --- |
| PCI address | User `0000:3b:00.1`, management `0000:3b:00.0`, observed |
| Shell | `xilinx_u250_gen3x16_xdma_shell_4_1`, observed |
| Shell Logic UUID | `12C8FAFB-0632-499D-B1C0-C6676271B8A6`, observed |
| Interface UUIDs | `807A580E-5F50-7D48-484D-26C2217AA787` and `A8880C23-11A2-A42B-5FB7-6899D385ACEE`, observed |
| Matching AMD deployment | `xilinx_u250_gen3x16_xdma_4_1_202210_1`, identified by the documented `807A580E…` interface |
| AMD platform memory | `DDR[0]`–`DDR[3]`, each 16 GiB of DDR4-2400 |
| Observed platform status | `DDR Size: 0 Bytes`, `DDR Count: 0`, `Mig Calibrated: false`, P2P disabled |
| Observed memory report | DMA counters only, with no application memory topology or bank capacities |

The Logic UUID above identifies the running shell partition. AMD's platform
guide publishes the base Logic UUID `F8DAC62E-49D9-B0AA-E9FC-6F260D9D0DFB`
for the 4_1 deployment. Preserve the partition-interface list when matching the
`.xpfm` and application image. The node's `examine` snapshot leaves DDR4
application access unverified.
[AMD U250 4_1 deployment](https://docs.amd.com/r/en-US/ug1120-alveo-platforms/U250-Gen3x16-XDMA-4_1-Platform) ·
[AMD U250 DDR4 specification](https://docs.amd.com/r/en-US/ds962-u200-u250/FPGA-Resource-Information)

The [Bambu board profile](../../boards.json) defaults to `xcu250`, a 5 ns goal
and the installed `xcu250_ddr4_2400R.yaml`. Use the installed preset's contents
and hash for a reproduction. The [FPGA deployment profile](../profiles/boards.json)
expects DDR resources and uses `FPGA_PLATFORM_XCU250` for the development
platform path. A linked DDR4 hardware probe still needs functional validation
on this node.

## Alveo U280

| Field | Value and source |
| --- | --- |
| PCI address | User `0000:af:00.1`, management `0000:af:00.0`, observed |
| Shell | `xilinx_u280_gen3x16_xdma_base_1`, observed |
| Logic UUID | `283BAB8F-654D-8674-968F-4DA57F7FA5D7`, matches AMD documentation |
| Interface UUID | `FB2B2C5A-19ED-6359-3FEA-95F51FBC8EB9`, reported twice by sysfs and matches AMD documentation |
| Matching AMD deployment | `xilinx_u280_gen3x16_xdma_1_202211_1` |
| AMD platform memory | `DDR[0]` and `DDR[1]`, each 16 GiB of DDR4-2400, plus `HBM[0]`–`HBM[31]`, 256 MiB per pseudo-channel |
| Observed platform status | `DDR Size: 0 Bytes`, `DDR Count: 0`, `Mig Calibrated: true`, P2P disabled |
| Observed shell clock report | `DATA_CLK` 300 MHz, `KERNEL_CLK` 500 MHz, `hbm_aclk` 450 MHz |
| Resident image during inspection | Slot 0, `xclbin` UUID `4d3530c2-7b9e-c638-cf52-0cec236984ca` |

The resident image reported all 32 HBM tags and a capacity of 256 MiB each.
Base addresses run from `0x0` through `0x1f0000000` in `0x10000000` steps.
`HBM[0]` is tagged `MEM_HBM` and the other HBM entries are tagged `MEM_DRAM`
in the type column. The bank names and capacities identify the HBM entries.
The listed HBM temperature was 29 °C. The same image lists `bank0`,
`bank1`, `PLRAM[0]`–`PLRAM[5]` and `HOST[0]` with zero capacity in the
report. DDR4 application access remains unverified. The observed clocks
describe the installed shell and resident image at inspection time.
[AMD U280 platform and memory map](https://docs.amd.com/r/en-US/ug1120-alveo-platforms/U280-Gen3x16-XDMA-base_1-Platform) ·
[XRT memory report](https://xilinx.github.io/XRT/2023.2/html/xbutil.html#xbutil-examine)

The [Bambu board profile](../../boards.json) targets a 4 ns period and defaults
to the shared [HBM2 YAML](../../smoke/configs/hbm2_32ch.yaml). The
[FPGA deployment profile](../profiles/boards.json) allows HBM resources by
default. A paired DDR4/HBM experiment on this U280 should use the same
kernel RTL and achieved accelerator frequency, with explicit bank mapping
per image. It needs a reviewed DDR deployment profile and a DDR4 probe linked
to `DDR[0]` or `DDR[1]`. The [one-channel DDR4 YAML](../../smoke/configs/ddr4_1ch.yaml)
is available for diagnostics. Calibration should use the measured path and
exact configuration of the DDR4 experiment.

The 1,000-read probe built with Vivado/Vitis 2022.2 ran on the U280
at `0000:af:00.1` with XRT 2.16.204, a linked 100 MHz kernel clock,
and `HBM[0]`. Three acquisitions each measured a median of 26
cycles. The same image ran on `hacc-legacy-01`.
[U280 HBM measurements and traces](../hbm_reference/PROBE.md#u280-hbm-measurements-on-hacc)
