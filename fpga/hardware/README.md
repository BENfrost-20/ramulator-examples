# Reference hardware and HACC nodes

Use these records to select a node, match the Vitis platform to its shell and
set up comparable memory experiments. Each record identifies the source of the
board specifications, node observations and application measurements.

| Board | HACC experiment node inspected | On-card memory | Experiment evidence |
| --- | --- | --- | --- |
| Alveo U250 (`xcu250`) | [`hacc-legacy-02`](hacc-legacy-02.md#alveo-u250) | Four DDR4-2400 banks, 16 GiB each | Shell and interface identified |
| Alveo U280 (`xcu280`) | `hacc-legacy-01` and [`hacc-legacy-02`](hacc-legacy-02.md#alveo-u280) | Two DDR4-2400 banks, 16 GiB each, and 8 GiB HBM2 | [1,000-read HBM probe replicated on both nodes](../hbm_reference/PROBE.md#u280-hbm-measurements-on-hacc) |
| Alveo U55C (`xcu55c`) | [`hacc-u55c-08`](hacc-u55c-08.md) | 16 GiB HBM2 | One-word probe measured on `HBM[0]` |
| Alveo U55C (`xcu55c`) | [`hacc-u55c-12`](hacc-u55c-12.md) | 16 GiB HBM2 | One-word probe reproduced on `HBM[0]` |

ETH lists both `hacc-legacy-01` and `hacc-legacy-02` as hosting a U250 and a
U280. Recheck PCI addresses and software versions on the node reserved for the
next run. Use the ETH VPN and the [HACC booking system](https://github.com/fpgasystems/hacc/blob/main/docs/booking-system.md)
for experiment-node access. The hardware inventory and address conventions
come from the [ETH HACC topology](https://github.com/fpgasystems/hacc/blob/main/docs/topology.md)
and [access guide](https://github.com/fpgasystems/hacc#accessing-hacc).

## Build and runtime configuration

The recorded U55C image was built on `ferrandi-1` with Vivado/Vitis 2024.2.
The [HACC deployment guide](../HACC.md) covers build, transfer and host
compilation. Its [site configuration example](../deploy.env.example) uses
`hacc-build-01.inf.ethz.ch` for staging. Use the experiment node's XRT version
when selecting or building the host executable.

The executable settings live in the [Bambu board registry](../../boards.json)
and the [FPGA deployment profiles](../profiles/boards.json). The Bambu goal
period, the Vitis requested and achieved accelerator clocks, and the shell's
memory interface clock are separate values. Keep the exact Ramulator YAML and
AMD model configuration with each simulation.

## Capture a new observation

On the reserved node, the following commands print the hostname and XRT
inventory, then the shell and memory reports for the selected user-function
PCI address. The memory report depends on the resident `xclbin`.
[ETH cluster access](https://github.com/fpgasystems/hacc#accessing-hacc) ·
[XRT examine reference](https://xilinx.github.io/XRT/2023.2/html/xbutil.html#xbutil-examine)

```bash
hostname -f
source /opt/hdev/cli/enable/xrt
xrt_tool=$(command -v xrt-smi || command -v xbutil)
"$xrt_tool" examine
read -r -p 'User-function BDF from the inventory: ' bdf
"$xrt_tool" examine -d "$bdf" -r platform
"$xrt_tool" examine -d "$bdf" -r memory
```

On the build host, set `xpfm` and `xclbin` to the absolute paths of the
selected files. The development platform report describes linkable memory
resources and clocks. The application image report gives its actual
connectivity and clock metadata.
[AMD platforminfo](https://docs.amd.com/r/2023.2-English/ug1393-vitis-application-acceleration/platforminfo-Utility) ·
[XRT xclbinutil](https://xilinx.github.io/XRT/2023.1/html/xclbintools.html)

```bash
platforminfo --platform "$xpfm"
xclbinutil --input "$xclbin" --info
sha256sum -- "$xpfm" "$xclbin"
```

Keep the observation date, node, board and BDF, OS, XRT build, shell VBNV
and UUIDs with the run evidence. Record the `.xpfm` and `.xclbin` hashes, the
kernel-port-to-bank mapping, actual clock domains and BO placement or address
offsets when available. For timing comparisons, also record the kernel/RTL
revision, input, repetition, resident-image or reprogramming state, and the
precise start and end events. Attach model/tool versions and configuration
hashes for the simulation runs being compared. Use the
[platform receipt example](../profiles/receipt.example.json) when registering a
development platform for the deployment flow.
