# Experimental Bambu FPGA deployment (2024.2)

Use the [build guide](BUILD.md) for Vivado/Vitis artifacts and the
[Ferrandi-to-HACC workflow](HACC.md) to export a bundle and run it on the
reserved board. The [U55C probe comparison](hbm_reference/PROBE.md) has the
recorded Bambu, Ramulator, AMD VCS and hardware results.

## Ramulator timing with the deployed wrapper

Use the prepared RTL from the U55C image to run the single-port
`memory_probe_single` in Verilator. The test uses the same AXI-Lite registers
and reads the same wrapper counters as the board host. For the first comparison,
select `n=1`, repetition 0, and the exact YAML from the native Bambu run.

Run on Ferrandi with Verilator, GCC 13, and the
[Ramulator 2.1 installation](../README.md#build-on-linux-x86-64).
Set the paths below for the local environment. Keep the output directory
separate from the prepared build.

```bash
cd "$HOME/thesis/ramulator-examples"
prepared="$PWD/.fpga/bitstream-xfTkobFQ/probe-single"
export RAMULATOR2_DIR="$HOME/thesis/ramulator21/install"
export FPGA_VERILATOR=/opt/verilator/verilator-5.030/bin/verilator
export FPGA_VERILATOR_CXX=/usr/bin/g++-13
out=$(mktemp -d "$PWD/.fpga/probe-ramulator.XXXXXX")
python3 -B fpga/functional.py --prepared "$prepared" --output "$out" \
  --ramulator-config "$PWD/smoke/configs/hbm2_32ch.yaml" --clock-period-ns 10 --n 1
cat "$out/ramulator-results.jsonl" "$out/ramulator-axi.jsonl"
```

- `ramulator-results.jsonl` records the oracle and guard check, kernel and
  AXI-drain cycles, the input file, and the AXI request counts.
- `ramulator-axi.jsonl` records AXI handshakes plus the timing model's read
  acceptance, read callback and write acceptance. `axi_cycle` counts from
  testbench reset. Compare differences between AXI events within the same run.
- `ramulator-config.yaml` retains the exact input YAML. `ramulator-run.json`
  records its hash, the RTL and library hashes, the API version, the input AXI
  period and the write response policy.

With Ramulator 2.1 the bridge uses the External frontend and derives DRAM
ticks from the specified AXI period and the DRAM model's `tCK`. It accepts
native 2.1 YAML and legacy presets supported by Ferrandi's adapter. Select the
period that matches the native Bambu run or the hardware clock being compared.
The bridge carries fractional ticks between cycles. The model clock advances from testbench reset. The bridge
translates the simulated AXI buffer base back to the probe's logical address
(`0x40000000` for the first word). The testbench keeps the data and byte strobes
in a local slab, returns reads after the Ramulator callback, and queues an AXI
B response when Ramulator accepts the write. The drain counter therefore
measures AXI completion according to the wrapper's ABI. The address mapping,
latency of the physical U55C shell, and write visibility in HBM are separate
calibration tasks.

Omit `--ramulator-config` to use the default AXI RAM. Pass `--n 1` there as well
to run the same isolated input and control sequence.

## Supported adapters and case selection

The deployment adapters cover memory_probe_single, memory_probe_banked,
smoke_axi_1ch, t01_clock, t02_single_read, t03_read_after_write, t04_stream
and t06_byte_lanes. Deployment requires the generated interface to pass
preparation for the selected board. Other cases appear in the inventory
with their deployment status.

After a recursive clone, run from the repository root.

```bash
./fpga/run.sh inventory --output .fpga/inventory.json
./fpga/run.sh native --all-supported --output .fpga/native
python3 -B -m unittest discover -s fpga/tests -v
```

With no selectors, the FPGA driver selects the two calibration cases.
Use --tests for exact names or comma-separated globs and --all-supported
for all implemented adapters. Package and link each prepared DUT separately.

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

The host loads the selected xclbin. For emulation use the directory containing
the generated `emconfig.json`.

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
separate core/drain counters, response errors and quiescent reset.
Run the checks above with Verilator or the corresponding xsim control bench.

The supplied probe top wires `done_port = sig_done`; its library's
`MinimalAXI4Adapter` drives `M_DataRdy` from R/B handshakes or an internal saved
response. This alone is not a proof that top done drains all external writes.
Generated Ferrandi core/library identities must pass preparation and the
actual-DUT functional test before attributing a stronger guarantee to a build.
The wrapper always preserves the original core-done measurement and reports
memory-boundary completion separately. Neither is labeled DRAM-cell drain.
