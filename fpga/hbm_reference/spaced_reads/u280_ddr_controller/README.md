# U280 DDR4 controller validation

This campaign extends the 1,000-read probe from `ramulator-examples` at the revision in
`src/source-revision.txt`. It tests row locality with a single AXI read in flight.

## Controller address mapping

The successful Ferrandi U280 DDR link is under
`$HOME/thesis/ramulator-examples/.fpga/u280-source.D5TZxl/.fpga/spaced-u280-hbm.0Qo0j9/campaign-2022.2/runs/u280-ddr/link-retry-20261124-112051`.
Its `bd_b35e_ddr4_mem00_0.xci` configures an ECC RDIMM with 72 physical bits,
64 payload bits, a 512-bit AXI data port, a 34-bit AXI address, one rank and
four bank groups of four banks. See [the controller receipt](controller-reference.tsv)
for parameters and the XCI and generated decoder hashes.

The linked `ulp.hwh` assigns kernel port `m_axi_0` the DDR4_MEM00 range
`0x1000000000–0x13ffffffff`. The existing image reports the same used
memory segment as `bank0`, topology index 32. Let `d` be the kernel AXI
byte address minus `0x1000000000`. The controller AXI shim converts byte
addresses to 64-bit payload-word addresses. For these aligned reads the
low three bits of the resulting BL8 column are zero. With
`ROW_COLUMN_BANK_INTLV`, the DDR4 branch in `ddr4_v2_2_ui_cmd.sv`
around line 402 gives the following fields.

| Field | Generated UI address | Controller byte address |
| --- | --- | --- |
| Rank | Constant 0 | Constant 0 |
| Row [16:0] | app_addr [30:14] | d[33:17] |
| Bank address [1:0] | app_addr [7:6] | d[10:9] |
| Bank group [1:0] | app_addr [4:3] | d[7:6] |
| Column [9:0] | app_addr [13:8], [5], [2:0] | d[16:11], d[8], d[5:3] |
| Byte lane | | d[2:0] |

The AXI byte-to-word conversion is also documented in [AMD PG150 AXI addressing](https://docs.amd.com/r/en-US/pg150-ultrascale-memory-ip/AXI-Addressing).

## Stimulus

The host allocates one 512 KiB BO in the topology bank connected to `base0`
and chooses A by rounding the returned BO address up to the next 256 KiB
boundary (an already aligned address is kept). It checks the aperture and
the BO bounds and records the original BO address and A in `placement.tsv`.

| Mode | B | Coordinates changed relative to A |
| --- | --- | --- |
| `same-row` | A XOR 0x100 | Column 0 → 8, same physical bank and row |
| `same-bank` | A XOR 0x20000 | Row LSB 0 → 1, same physical bank and column |
| `different-bank` | A XOR 0x200 | BA 0 → 1, same bank group, row and column |

Each test issues A, B, A, B for 1,000 reads at 100 MHz. Both targets use
the same RTL, 4-byte single-beat reads, ID 0 and the same seeded sequence
of 8–71 cycle programmed gaps after each R handshake. The first request
uses a 50-cycle programmed gap. The shorter inter-read gaps give the
controller more opportunities to reuse open rows during a refresh interval.
RREADY is high throughout the response state, so AR-to-RVALID and AR-to-R use the same end cycle. The A and B data
sentinels differ and every response is checked. HACC initializes the same
BO before each run and rotates mode order across three repetitions.
The summaries exclude the first access of each run and report p50, p95,
p99, maximum and the p50 difference from `same-row` in kernel cycles.

Ramulator decodes the HACC anchor and addresses using the table above, then
repacks the coordinates for `RoBaRaCoCh`. It uses the XCI-aligned DDR4-2400
configuration and 12 DRAM ticks per kernel cycle. The simulator validates
the actual AR sequence and the coordinates of all issued RD commands.
Each simulation also logs ACT, PRE, PREA and REFab when issued. The four
offsets span one nominal refresh period. Hardware refresh phase is
uncontrolled, and the host DMA can affect the initial open rows. The
three tests measure row locality and retention under the chosen gaps.
A flat hardware p50 is compatible with rows closing between accesses.
The single-read workload exercises service time and row state.

## Ferrandi build

On the Mac with the Ferrandi VPN active, set `source_bundle` to the
downloaded source archive and upload it.

```bash
ferrandi=pelorosso@10.79.23.200
scp "$source_bundle" "$ferrandi:u280-ddr-controller-ferrandi.tar.gz"
ssh "$ferrandi"
```

On Ferrandi, extract into a fresh directory and launch the build in tmux.
The package and link take place in a new directory. The script checks
routing and timing, interface UUID, kernel frequency, DDR[0] connectivity
and the controller XCI/RTL before printing `HACC_BUNDLE:`.

```bash
work=$(mktemp -d "$HOME/u280-ddr-controller.XXXXXX")
tar -xzf "$HOME/u280-ddr-controller-ferrandi.tar.gz" -C "$work"
printf '%s\n' "$work"
tmux new-session -s u280-ddr-controller -c "$work"
bash build-ferrandi.sh
```

## HACC acquisition

On the Mac, set `ferrandi_bundle` to the absolute path printed after
`HACC_BUNDLE:`. Download with the Ferrandi VPN, then switch to the ETH VPN
before staging it in the HACC shared home.

```bash
scp "$ferrandi:$ferrandi_bundle" ./u280-ddr-controller-hacc.tar.gz
scp ./u280-ddr-controller-hacc.tar.gz \
  lpelorosso@hacc-build-01.inf.ethz.ch:u280-ddr-controller-hacc.tar.gz
```

On the reserved legacy U280 node, use a login Bash shell. Discover the BDF
from the current inventory. The previous U280 on legacy-01 used
`0000:af:00.1`.

```bash
export PATH="/opt/xilinx/xrt/bin:$PATH"
xrt_tool=$(command -v xrt-smi || command -v xbutil)
"$xrt_tool" examine
read -r -p 'U280 user-function BDF from the inventory: ' bdf
work=$(mktemp -d "$HOME/hacc-u280-ddr-controller.XXXXXX")
tar -xzf "$HOME/u280-ddr-controller-hacc.tar.gz" -C "$work"
cd "$work"
bash run-hacc.sh "$bdf"
anchor=$(awk -F '\t' 'NR==2 {print $2}' reads/placement.tsv)
printf 'Ferrandi simulation anchor: %s\n' "$anchor"
```

The run leaves the platform report, interface UUIDs, host log, placement, nine latency CSVs
and `summary.tsv` in the acquisition directory.

## Ferrandi Ramulator replay

Return to the source directory created before the build and pass the
anchor printed on HACC.

```bash
read -r -p 'Paste the HACC anchor: ' anchor
bash simulate-ferrandi.sh "$anchor"
```

Expect twelve passing runs, covering three address patterns and four
refresh offsets. Each phase has a `summary.tsv`. Each mode directory also
contains `latencies.csv`, `ramulator-axi.jsonl`, `dram-commands.csv` and
`commands-summary.txt`.
For a pre-hardware smoke run, use `0x1000000000` as an aligned example
anchor and rerun with the measured anchor for the comparison.

## Local smoke run

The [local results](local-smoke.tsv) use anchor `0x1000500000`, Verilator
5.030 and a local build of Ramulator-no-spdlog at `d1723a4` with a Clang
compatibility change in its temporary source tree. Each of the 12 runs
passed the AXI single-request and command-coordinate checks. The p50
was 3 cycles for same-row and different-bank and 6 cycles for same-bank
across all four offsets. The simulated conflict case issued 940–941 PRE
commands. The Ferrandi build and HACC acquisition are the deployment
and measurement steps above.
