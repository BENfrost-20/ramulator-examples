# Experimental Bambu FPGA deployment (2024.2)

This directory adds a focused deployment path. It does not change the shared
runner, recipes, source snapshots, precision, golden approvals or board registry.
Only the commands explicitly shown for host execution load/program a device.
Build commands never run the host.

## Actual delivery status

Eight native/oracle/packing checks pass (12 Python deployment tests also pass): `memory_probe_single`,
`memory_probe_banked`, `smoke_axi_1ch`, `t01_clock`, `t02_single_read`,
`t03_read_after_write`, `t04_stream`, `t06_byte_lanes`. The supplied probe RTL
matches the restricted interface checker, including two-bit banked IDs and
31-bit compacted addresses. Native and C++ syntax checks are not RTL simulation.
The suite adapters require verification against actual regenerated interfaces;
changed/missing ports fail rather than selecting a different architecture.

No new Bambu generation, RTL simulation, vendor package/XO, xclbin,
implementation timing closure, hw_emu or board test was performed in this
session. The development Mac has none of these tools. The server was inspected
read-only at the user's request: no build, script upload, license checkout test,
IP generation, programming or shell reflash was performed there.

All registered cases are listed by `inventory`; cases outside the eight are
**not yet implemented** in deployment, rather than declared incompatible.
Native/minimal-interface variants (including `t10_native_and_axi`) have no bridge
in this delivery. Floating point and structured MachSuite buffers need explicit
adapters/oracles before deployment. No performance equivalence is claimed.

The selected integrated toolchain is `ferrandi/PandA-bambu` branch
`feature/ramulator`, revision `d1975e817a77ac3fe046ccb3adb471e05224ec81`, whose
Git submodule pins `ferrandi/ramulator2` to
`9a8ed857455d041524043bc5fb45eb7f07e6a731`. The branch includes production
MDPI/RTL integration, standalone protocol/clock regressions and CI build rules.
`toolchain.json` records the examined files and revision selection evidence.
Ferrandi `main`/tag `2026.11` revision `cda4db2` is also accepted for independent
hardware generation; it is not selected for Ramulator co-simulation.
No Jesun build is substituted. The installed candidate observed on the server
is Jesun and does not establish a built Ferrandi installation.

The Ferrandi driver advances all backends from an external accelerator clock,
uses a fractional phase accumulator (not per-call integer truncation), and
reports writes complete on Ramulator acceptance. An AXI B in that co-simulation
therefore represents acceptance into the timing backend, not full device drain.
Do not compare that event with physical DRAM-cell visibility. HBM2 presets have
two pseudochannels per modeled channel; the branch's own 32-pseudochannel
regression uses 16 modeled channels. No existing preset/golden is changed here.

## Server observations (13 November 2026)

* The installed candidate Bambu reports revision `909639b4b77944d908ca5180ac9f81b3a48a966b`.
  CMake identifies source `soda-benchmarks/external/candidate-release`, whose
  remote is Jesun. It is deliberately rejected by the Ferrandi provenance gate.
* Vivado 2024.2: SW build 5239630; IP build 5239520.
* Vitis `v++` 2024.2: SW build 5239630; Vitis HLS 2024.2: 5238294.
  Vitis HLS is not used to synthesize any benchmark.
* Install prefixes: `/opt/Xilinx/{Vivado,Vitis,Vitis_HLS}/2024.2`, resolving
  through `/ssd/opt/Xilinx`. These tools were absent from the default SSH PATH.
* Platforms found: U280 `xilinx_u280_gen3x16_xdma_1_202211_1`, U55C
  `xilinx_u55c_gen3x16_xdma_3_202210_1`, with hw/hw_emu XSA files.
  U250 development platform was not found in `/opt/xilinx/platforms`.
  Presence is not evidence of 2024.2, installed shell or runtime compatibility.
* XRT `/opt/xilinx/xrt`: 2.14.354, branch 2022.2. Required experimental IP and
  xclbin APIs are present, including `get_ips/get_args/get_mems/get_index`.
  Compilation/runtime compatibility with 2024.2 remains unverified.
* Questa `/opt/mentor/questasim` and `/data2/opt/mentor/questasim` resolve to
  10.7c (2018.08), outside the 2024.2 supported release matrix.
* VCS directory `/data2/opt/synopsys/vcs/V-2023.12`. `vcs -ID` failed in its
  shell launcher; SP1 and a usable license were not established.
* `hbm_v1_0` and `ddr4_v2_2` IP metadata are installed. HBM model files
  `HBM_questa.vp`, `HBM_vcs.vp`, `HBM_nc.vp`, `HBM_xsim.sv` exist. Their
  timing coverage was not established; no proprietary model source is copied.
* A later metadata scan also found Vivado ML Enterprise **2025.03**, permanent,
  in `Xilinx.lic`; effective checkout/part entitlement remains untested.
* `Xilinx.24.lic` names Vivado ML Enterprise with version 2024.05 and permanent
  expiry. Vivado reports a 2024.11 tool-version limit: entitlement for this
  release is not proven. `lmstat` reported no SERVER lines (node-locked file);
  that is not itself proof of an unusable or usable license.

## Clean recursive checkout and selection

The hardware feature branch is committed first; the validation branch then
inherits that commit and adds only validation files. Consult the delivery report
for verified commit hashes. The original MachSuite branch and both remote main
branches remain unchanged. No push or PR is performed.

```bash
git clone --recursive git@github.com:BENfrost-20/ramulator-examples.git
cd ramulator-examples
git switch --detach 363d342
git switch -c feat/fpga-hardware
git apply /path/to/hardware.patch  # optional delivery patch, already committed on feature branch
./fpga/run.sh inventory --output .fpga/inventory.json
./fpga/run.sh native --all-supported --output .fpga/native
python3 -m unittest discover -s fpga/tests -v
```

No selectors defaults to the two calibration cases. `--tests` accepts exact names
or comma-separated globs, repeatable. `--all-supported` opts into all eight
adapter candidates, not all registered cases. Every unmatched/unsupported
requested case raises an error. Each expensive stage handles one prepared DUT;
there is no default all-bitstreams command.

## Generate, inspect, package and link

On an authorized build machine, configure the original `env.sh` for the installed
Ferrandi Bambu/Ramulator and source it. Source `fpga/env.example.sh` with local overrides.
Do not source a reference kit's environment blindly. `FPGA_BAMBU` selects the
Ferrandi Bambu executable; `FPGA_BAMBU_SOURCE` must identify the clean matching
Ferrandi checkout selected in `toolchain.json`, or use `FPGA_TOOLCHAIN_RECEIPT`
with installed binary/runtime hashes and build evidence. Generation checks source
revision plus a matching unambiguous abbreviated/full revision banner, or the
artifact receipt. It does not require the full SHA literally in `--version`. There is no Jesun fallback. Use that
installation's `settings.sh` to resolve CLANG13.
Hardware staging reads only the selected recipe source members and needs no
Ramulator installation, YAML or MDPI build. `CLOCK_PERIOD_NS` is retained in
both the actual command and generation receipt. The repository's case flags remain CLANG13. The kit's CLANG16 RTL is usable only
as an explicitly identified reference fixture; it cannot satisfy a CLANG13
board-generation receipt. Never substitute Vitis HLS.

```bash
./fpga/run.sh preflight --board xcu55c --period 10 --output .fpga/preflight.json
./fpga/run.sh generate --board xcu55c --tests memory_probe_banked --output .fpga/generated
# The generator prints the exact RTL directory; use it below.
./fpga/run.sh prepare --board xcu55c --tests memory_probe_banked \
  --rtl-dir .fpga/generated/memory_probe_banked/hls \
  --generation .fpga/generated/memory_probe_banked/generation.json \
  --output .fpga/prepared/probe-banked
python3 fpga/check_rtl.py --simulator verilator --bench completion --output .fpga/completion-test
python3 fpga/check_rtl.py --simulator xsim --bench control --output .fpga/control-test
# xsim is an alternative for the control bench, not a detailed HBM backend.
python3 fpga/functional.py --prepared .fpga/prepared/probe-banked
./fpga/run.sh package --prepared .fpga/prepared/probe-banked
./fpga/run.sh host --prepared .fpga/prepared/probe-banked
./fpga/run.sh link --prepared .fpga/prepared/probe-banked --target hw_emu
./fpga/run.sh link --prepared .fpga/prepared/probe-banked --target hw
```

Expected artifacts in the prepared directory: original/ + rtl/ copies,
`manifest.json`, source hashes, `abi.hpp`, `case.hpp`, `registers.tcl`,
`functional-results.jsonl` after a successful simulation, `fpga_kernel.xo` after
successful packaging, `host`, and `{hw,hw_emu}/fpga_kernel.xclbin` after linking.
Build logs/reports and routed checkpoints are retained below the ignored tree.
The linker reports and routed checkpoint must be checked; OOC target synthesis
is only a packaging check. Run `fpga/tcl/check_implementation.tcl` on the actual
routed target DCP and retain the reports. It checks setup/hold and unrouted nets;
review unconstrained paths and DRCs as well. A negative timing result is a failed
hardware implementation. No different-device OOC fallback is provided.

If Vivado diagnoses the known `MinimalAXI4Adapter` dynamic log2 problem, discard
the failed prepared directory and prepare a new one with
`--fix-adapter-log2`. It applies only to a precisely recognized adapter section,
records a diff and hashes, and never changes original RTL. This is opt-in; no
blanket transformation is performed. A transformed copy must pass the same
functional simulation and target synthesis as the copy used for comparison.
Only the selected top, Bambu synthesizable library, wrapper, control and drain
tracker are packaged. The functional responder and benches never enter the XO.
Additional generated dependencies require a reviewed explicit source manifest;
this small backend does not collect every `.v` from a build tree.

## Platform receipt and adding boards

`boards.json` remains the source of board names, Bambu devices, periods and
Ramulator defaults. `fpga/profiles/boards.json` supplies deployment-only data.
An incomplete future board raises an actionable error; non-AMD vendors cannot
inherit Vitis/HBM support. A new backend is needed for them.

For an additional AMD board, register it in the original registry, add vendor,
part, tool release, memory kind, explicit resource names, independent platform
environment variable and memory IP VLNV to the deployment profile. An external
`FPGA_PROFILE` JSON may hold site-specific entries. Inspect the development
platform with `platforminfo --platform "$FPGA_PLATFORM_XCU55C"`, confirm its
part, clocks, resource capacities, shell VBNV and compatible XRT release using
the platform's own documentation. Fill `receipt.example.json` with evidence and
SHA-256 of the actual xpfm and set `FPGA_PLATFORM_RECEIPT`. This receipt is an
explicit reviewed site configuration, not an automatically verified license or
shell detector. Preflight checks hashes, matching clocks, resources and fields.
For memory-reference work also supply IP configuration/XCI, native protocol,
width/ID limits, clocks/CDC, simulator release, encrypted libraries, initialization
and timing-fidelity evidence. A board entry does not supply these capabilities.

U250 resources must be real DDR4, U280/U55C resources real HBM, as confirmed from
the selected platform. BRAM/URAM is never used to replace external memory;
internal memories/caches of the core are not removed. Suite pointers occupy one
shared physical BO slab, avoiding independent-BO alias violations and keeping
writable inputs. Their pointer offsets are described by each adapter, rather
than inheriting probe addresses. General structured/aliasing layouts beyond
these small cases are not yet implemented. Each banked probe BO contains
byte-wise 256-byte stripes; the final stripe may be partial. RTL selection bit 8
and removal of that bit produce the 31-bit bank-local address; the wrapper then
relocates the compacted base to the full 64-bit BO address. Logical addresses,
compacted offsets and physical addresses are distinct.

## Host execution: deliberate later step

The commands below load an xclbin. They were not executed during this session.
For emulation run from the directory containing generated `emconfig.json`:

```bash
cd .fpga/prepared/probe-banked/hw_emu
XCL_EMULATION_MODE=hw_emu ../host fpga_kernel.xclbin 0 513 2 1800 hw-emu-results.jsonl
# On a matching physical board, deliberately:
cd ../hw
../host fpga_kernel.xclbin 0000:65:00.1 513 5 60 board-results.jsonl
```

Arguments are xclbin, device index/BDF, n, repetitions, timeout seconds, result
JSONL. Probe tests should include 0,1,63,64,65,127,128,129,512,513, repeated.
Other cases retain their original fixed dimensions (`n=8` smoke, `n=0` ignored
for micro). BO allocation reads linked xclbin connectivity and requires a single
unambiguous connected memory; HBM/DDR labels are never interpreted as topology
indices. Input/output guards, writable-input checks and the original C oracle
are checked every run. Polling also checks a generation number to reject stale
done. Device loading, DMA and polling wall time are not accelerator cycles.

On timeout the host keeps BOs pinned and remains alive. A timeout does not stop
the kernel. Recover/reset the accelerator with the administrator before
terminating that process or reusing the device/allocations. A register reset is
valid only with the external bus quiescent; aborting outstanding AXI traffic is
not implemented.

Counter convention: distance in kernel-clock rising edges from sampled
`start_core` at S to a new core-done edge at D, D-S. The 64-bit core snapshot
and separately drained snapshot are stable until the next accepted start.
Busy lasts through drain; register writes while busy receive SLVERR.
The tracker observes every accepted W beat: a partial W burst blocks drain even
when neither AW nor WLAST has arrived. AW/W order is unrestricted. Raw AR/AW/W
VALID waiting for READY is tracked separately from accepted traffic and also
blocks completion, as do pending R/B VALID responses. Reads of
low/high halves after completion are coherent. Drain means accepted ARs have
RLAST responses, no accepted W burst is incomplete, accepted AW/completed W
bursts have B responses, and no boundary channel has pending VALID;
it is not a claim that data has reached DRAM cells. Opaque internal caches need
their own completion/flush evidence before extending this flow.

## References checked

* [AMD 2024.2 user-managed RTL kernels, UG1700](https://docs.amd.com/r/2024.2-English/ug1700-vitis-accelerated-data-center/Creating-User-Managed-RTL-Kernels)
* [AMD 2024.2 XO packaging, UG1700](https://docs.amd.com/r/2024.2-English/ug1700-vitis-accelerated-data-center/Packaging-the-RTL-Code-as-a-Vitis-XO)
* [AMD 2024.2 kernel XML, UG1702](https://docs.amd.com/r/2024.2-English/ug1702-vitis-accelerated-reference/RTL-Kernel-XML-File)
* [AMD 2024.2 supported simulators, UG900](https://docs.amd.com/r/2024.2-English/ug900-vivado-logic-simulation/Supported-Simulators)
* [Official PandA-bambu](https://github.com/ferrandi/PandA-bambu)

PG276's online current edition can be newer than installed IP; do not treat its
current simulation restrictions as verified 2024.2 support. Use installed release
metadata and the matching archived guide. No post-implementation HBM simulation
support or full physical timing fidelity is promised here.

## Drain counterexample and RTL checks

The previous implementation counted AW, WLAST and B only. At a rising edge with
`WVALID=WREADY=1, WLAST=0` and no accepted AW, all those counters stayed zero and
it falsely reported drained. `partial_w` now records this state until a final
W handshake; completed W bursts remain outstanding until matched AW/B counts
balance. A last beat before AW still cannot look drained. Simultaneous request
and response edges increment each independent counter, preventing completion
from erasing new traffic. Pending VALID requests are not counted as accepted,
but explicitly prevent drain until accepted/completed or properly withdrawn.

`completion_tb.sv` instantiates the real tracker and the real AXI-Lite control.
It exhibits the old false-idle expression alongside the corrected tracker,
then checks W-before-AW bursts with backpressure, AW-before-W, delayed/stalled
B, read bursts, simultaneous new requests and responses, repeated starts,
separate core/drain counters, response errors and quiescent reset. The old
control-only bench remains a separate register/counter test. Both are **unrun**
in this session because no local RTL simulator exists; no server simulation
was authorized. The commands above fail if a simulator is absent.

The supplied probe top wires `done_port = sig_done`; its library's
`MinimalAXI4Adapter` drives `M_DataRdy` from R/B handshakes or an internal saved
response. This alone is not a proof that top done drains all external writes.
Generated Ferrandi core/library identities must pass preparation and the
actual-DUT functional test before attributing a stronger guarantee to a build.
The wrapper always preserves the original core-done measurement and reports
memory-boundary completion separately. Neither is labeled DRAM-cell drain.

Audit exception: the initial `vitis_hls -version` invocation automatically
updated `/data2/home/pelorosso/vitis_hls.log` at 15:35:44 on 13 November 2026.
This was an unintended write during the read-only audit. The file was left
intact; no further server tool execution, build, simulation, upload, installation,
configuration change or board programming followed. License/model status
continues to be based on read-only metadata, not a completed tool checkout.
