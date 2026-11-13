# Experimental memory validation

This branch inherits the hardware commits. `fpga/` is identical to the hardware
branch; validation-specific files live here. No shared runner, recipe, source
snapshot or golden approval is changed. No server build/simulation or tool
installation was performed. Source generation and native/Python tests are not
RTL simulation, IP generation, implementation timing closure or board testing.

## Selected Ferrandi integration and provenance

Use **ferrandi/PandA-bambu `feature/ramulator` at
`d1975e817a77ac3fe046ccb3adb471e05224ec81`**, whose Git tree pins
**ferrandi/ramulator2 `9a8ed857455d041524043bc5fb45eb7f07e6a731`** under
`ext/ramulator2-no-spdlog`. The integration was found by auditing public branches,
tags, the full feature tree, `.gitmodules`, MDPI driver/build rules, the dedicated
CI workflow, and its production RTL/protocol/clock regressions. It was not
inferred from one identifier in `main`. See `fpga/toolchain.json` for source hashes.
The branch's CI uses CLANG13, Verilator, a C++20 MDPI host and the standard
Ramulator install layout; current Bambu itself requires GCC >=13/C++23.

The server's installed candidate Bambu identifies `909639b4b` and its source
remote is Jesun. It is not used as a substitute. A built Ferrandi installation
was not established. Hardware generation can independently use the reviewed
Ferrandi `main`/`2026.11` revision `cda4db2`; only the Ramulator mode requires
the integration branch. No Vitis HLS algorithm synthesis is used.

`src/Parameter.cpp` constructs `Version: <package> - Revision <revision_hash>`
with an optional branch suffix. The checker accepts a 7–40-character revision
when Git resolves it unambiguously to the clean selected source, recording the
binary SHA-256. A hash-checked source/build/install receipt is an alternative
that needs no source checkout at deployment runtime. Remote URL alone is never
binary-build proof. Receipt artifact hashes are checked under the installation
prefix; incomplete evidence is reported rather than fabricated. The host
executable itself does not require a source checkout.

On a **separately authorized build machine**, obtain/build the selected toolchain
using its documented prerequisites and CI settings. For the dependency, the
selected Ferrandi branch provides:

```bash
# In the pinned recursive Ferrandi checkout; performs a build/install, so this
# was NOT run on the read-only server.
bash panda_regressions/hls/bambu_ramulator/prepare_ramulator.sh /absolute/fresh/ramulator-build
source /absolute/ferrandi-bambu-install/settings.sh
export FPGA_BAMBU=/absolute/ferrandi-bambu-install/bin/bambu
export FPGA_BAMBU_SOURCE=/absolute/pinned/Ferrandi-PandA-bambu
export RAMULATOR2_DIR=/absolute/fresh/ramulator-build/install
```

Record the actual built library hash and build/log evidence using
`profiles/ramulator-receipt.example.json`; set `FPGA_RAMULATOR_RECEIPT`.
For a packaged Bambu installation set `FPGA_TOOLCHAIN_RECEIPT` instead of
`FPGA_BAMBU_SOURCE`, following `fpga/profiles/toolchain-receipt.example.json`.
No script silently resets/checks out a dependency or installs tools.

## Five distinct execution modes

1. **Bambu + Ferrandi Ramulator co-simulation**: existing commands remain
   `./smoke/run.sh --case smoke_axi_1ch --board xcu55c --no-compare` and
   `./micro/run.sh --tests 't01_clock,t02_single_read' --board xcu55c --no-compare`.
   The focused experimental driver additionally fingerprints the Ferrandi
   installation and supports calibration n without changing suite recipes:

   ```bash
   python3 validation/ramulator.py --tests memory_probe_single --n 513 \
     --board xcu55c --config validation/profiles/hbm2_experimental.yaml \
     --output .fpga/ramulator-513
   python3 validation/ramulator.py --tests memory_probe_single --n 0 \
     --board xcu55c --config validation/profiles/hbm2_experimental.yaml \
     --output .fpga/ramulator-0
   ```

   Calibration XML inputs call the same C kernel; the included unused standalone
   main is renamed in a staging wrapper. No benchmark algorithm/source snapshot
   is edited. Fixed suite dimensions cannot be overridden with calibration n.
   The n=0 result may legitimately report zero traffic. This driver was not run
   locally: Ferrandi binaries/library, Linux and Verilator are unavailable.

2. **Functional wrapper/DUT RTL with simple AXI RAM**:
   `python3 fpga/functional.py --prepared .fpga/prepared/probe-single`.
   This uses deterministic backpressure and a bounded single-beat 32-bit memory
   responder. It tests >4-GiB relocation, guards, repeats, reset, byte strobes,
   oracle values and wrapper completion. It is not an HBM/DDR timing model.
   `python3 fpga/check_rtl.py --bench completion --simulator verilator` runs the
   actual tracker/control integration counterexample bench separately.
   Both RTL tests are prepared but unrun here.

3. **Vitis hw_emu**: follow `fpga/README.md` package/link/host commands with
   target `hw_emu`. Accurate kernel RTL does not establish accurate platform
   memory timing. A waveform/debug switch cannot improve model fidelity.

4. **Vendor-memory reference**: use the concrete generator below, initially for
   `memory_probe_single` and the HBM backend. An IP traffic-generator example
   remains a separate availability smoke, not execution of the probe.

5. **Physical board**: the hardware host deliberately loads the xclbin only
   when manually invoked later. No board programming or measurement occurred.

## Concrete generated HBM reference slice

`build_reference.py` replaces the old unexplained pre-integrated-project
prerequisite for the initial slice. It emits:

* `build_reference.tcl`: a new Vivado 2024.2 project and block design using a
  configured one-port HBM XCI. It copies the selected XCI's USER parameters,
  rejects a locked/incompatible IP rather than upgrading it, verifies native
  AXI3 protocol/address/data/ID widths, and connects explicit AMD width, clock
  and protocol converters. All remaining controller inputs must be bound.
* `reference_tb.sv`: the prepared Bambu DUT/control wrapper, a mutually exclusive
  loader/DUT AXI ownership mux, an explicit 64-bit-to-native address aperture,
  clock generators, reset synchronizers per domain, synchronized readiness,
  AXI input loading and output/guard checking. It uses n=0,65,513 with two
  repetitions by default. Reconfigure these small calibration values explicitly.
* `axi_trace.sv` and `bind_monitors.sv`: passive `VALID && READY` measurement at
  the original wrapper boundary, before conversion/CDC. The probe's native
  core-done and wrapper AXI-completion counters remain distinct.
* A manifest of the source-generation status, selected model, sizes, clocks,
  preparation hash, observation boundary and standalone/platform differences.

The conversion path is **32-bit AXI4 -> width conversion -> asynchronous AXI4
CDC -> AXI4-to-AXI3 conversion -> configured 256-bit native HBM port**. The
loader and DUT never own the bus concurrently. Ownership changes only between
completed loading, DUT memory completion and output checking. Nonzero dropped
user/region semantics and addresses above the explicit aperture fail the bench;
they are not silently wrapped. The native model interface is checked after
IP creation instead of being assumed from a board name.

Clocks, capacity and the HBM initialization contract in
`profiles/hbm-reference.example.json` must be filled from the **actual configured
2024.2 model**. Zero clocks/capacity intentionally fail. The named pins were
observed in installed IP metadata; which pins are enabled, the port attributes,
autonomous APB configuration, readiness semantics and clock values depend on
output generation for the selected XCI. The implemented initialization backend
requires evidence that the configured IP performs its autonomous sequence while
external APB requests remain idle, then waits for configured `apb_complete`
outputs. It never starts after an arbitrary fixed delay. If that configuration
requires an external APB sequencer, this backend rejects it; that sequencer must
be implemented from the matching generated example/guide.

This is an **implemented generator, not a vendor-validated complete flow**.
Essential unresolved input: a reviewed 2024.2 one-port controller XCI and its
actual generated port/init products. Only metadata was read on the server;
authorization did not permit generating those products there. The installed
Vitis platform archive exposes an HMSS/memory-subsystem XCI, which is not proof
that an interchangeable standalone one-port HBM XCI exists. No undocumented
HMSS-to-HBM settings, device timing, address mapping or controller policy is
invented. The generated block design/bench must be elaborated and exercised on
an authorized machine before this path can be called working/validated.

```bash
# Fill site-model.json from the example and verified configured IP metadata.
python3 validation/build_reference.py \
  --prepared .fpga/prepared/probe-single --model /absolute/site-model.json \
  --output .fpga/vendor-reference
# On an authorized machine, actually generate IP, validate BD and export:
python3 validation/build_reference.py \
  --prepared .fpga/prepared/probe-single --model /absolute/site-model.json \
  --output .fpga/vendor-built --build
python3 validation/run_export.py --export .fpga/vendor-built/export --simulator questa
```

`--build` verifies the selected simulator release, compiled library map, XCI
fingerprint and board-generated RTL receipt before vendor invocation. It does
not program a board. `run_export.py` executes exactly one vendor-generated
launcher with a bounded process group. Expected later artifacts include the
BD wrapper/output products, IP-status/configuration reports, exported simulator
launcher, `vendor-results.jsonl` and per-port traces in the simulation working
directory. A generated launcher or a successful IP traffic-generator example
is not a completed benchmark simulation.

The first selected third-party backend is **Questa 2024.1 SE**; VCS
**V-2023.12-SP1** is explicitly selectable via the same model configuration and
`--simulator vcs`. The server has Questa **10.7c** and VCS **V-2023.12** metadata;
a supported patched release and a usable simulator license were not established.
`FPGA_QUESTA`/`FPGA_VCS` select simulator binary directories. xsim is available
for supported functional checks, and is not selected for this HBM reference.

Build encrypted AMD libraries deliberately, once per supported tool/simulator
combination, on a writable authorized machine (this can be expensive):

```bash
vivado -mode batch -source validation/tcl/compile_libraries.tcl \
  -tclargs questa /absolute/questa-2024.1/bin /absolute/vivado2024.2-questa-libraries
```

The older `vendor.py ip-example` and `vendor.py export` remain useful for
availability smoke tests and previously reviewed integrated projects. They are
not the central benchmark-integration implementation.

## Clocks, policies, topology and model limits

The pinned Ferrandi MDPI driver sets standalone Ramulator's integer scheduler
ratio to one and advances it through an external clock with a long-double phase
accumulator. `MemorySystem.clock_ratio` means DRAM ticks per accelerator cycle,
including fractional values, with no artificial cap of six. Its writes complete
on Ramulator request acceptance; reads complete by callback and preserve data
snapshots. This differs from interpreting a vendor B response as controller
write completion, and neither event proves arrival at DRAM cells.

The examined HBM2 organization is 128 bits per pseudochannel with a prefetch of
2, giving **32-byte physical transaction granularity**. A 32-bit AXI access does
not become a 4-byte DRAM transaction. Address mapping removes transaction-offset
bits; splitting/coalescing and queue behavior must also be aligned at the
production RTL/MDPI boundary. The reference profile is experimental, separate
from approved presets, with one modeled channel/two pseudochannels. The
upstream HBM regression uses 16 channels/two pseudochannels for 32 logical ports.
Neither is assumed to match U55C HBM2e or an undocumented AMD address map.

The generic controller's request-buffer source defaults to max_size=32 but its
`enqueue` condition is `size() <= max_size`, so effective admission at that point
can reach 33; preserve/report the source behavior rather than claim an exact
32-entry vendor queue match. FRFCFS/OpenRow/AllBank and HBM2_2Gbps exist in the
selected source, but vendor policy/equivalence remains unverified. The standalone
subsystem differs from the Vitis-linked shell's interconnect/settings. No fixed
SmartConnect/CDC latency is subtracted. Short runs cannot characterize refresh
or steady-state behavior. Detailed model latency, bank/row behavior, refresh,
queues and omissions require the matching archived guide and configured model
before a timing-reference claim. No post-implementation HBM support is promised.

## Metrics and reports

The passive monitor associates R responses by ID in per-ID request order and W
beats with global AW order, handling W before AW. It checks burst lengths,
WLAST/RLAST, byte strobes, pending VALID, incomplete traces and B completion. It
counts accepted requests/completed responses/bytes, backpressure and SLVERR/
DECERR. Read latencies run from accepted AR to accepted first/final R beat;
write latencies include AW-to-B and first/last-W-to-B, in observed clock cycles.
It does not infer first-VALID latency from a handshake-only trace. Whole traces
must not be mislabeled as per-repetition metrics without measurement windows.

```bash
python3 validation/report.py collect --manifest .fpga/prepared/probe-single/manifest.json \
  --results /absolute/simulation/vendor-results.jsonl --mode vendor_memory_reference \
  --model /absolute/site-model.json --trace /absolute/simulation/trace-0.jsonl \
  --output .fpga/vendor-records.json
python3 validation/report.py report --records .fpga/vendor-records.json \
  --output .fpga/comparison
python3 -m unittest discover -s validation/tests -v
```

Collectors retain source/RTL/input/configuration/tool/model fingerprints and
raw traffic; unknown fingerprints remain unknown. Automatic collection does
not assert topology/timing/queue alignment. The report refuses performance
ratios for missing/mismatched inputs, RTL, clocks, measurement boundaries,
unverified alignment, hw_emu/simple-RAM performance references, or unknown
vendor fidelity. It reports actual differences without tuning or a predetermined
error range. No measured cross-mode or single/banked speedup exists yet.

## Actual observations and blockers

Local: eight native algorithm/oracle/packing checks, 12 deployment tests,
14 validation tests and 27 existing tests passed. Python/source-generation
checks passed. The original CLI help works; original dry-run commands reach
preflight and fail due to absent Linux/Bambu/Verilator/Ramulator prerequisites.
No original command semantics or golden behavior changed. Control/tracker and
actual-DUT RTL benches were prepared **but not run**. No XO, bitstream, hw_emu,
vendor benchmark simulation, timing closure or board measurement is claimed.

Server: Vivado/Vitis/Vitis HLS 2024.2; U280/U55C platform candidates; no U250
platform found in the inspected platform directory; XRT 2.14.354 (2022.2), whose
compatibility with the chosen 2024.2 platform needs verification. HBM/DDR IP and
HBM Questa/VCS encrypted model files exist. A later scan found Vivado ML
Enterprise version **2025.03**, permanent, in `Xilinx.lic`, in addition to older
files; effective license checkout/part access remains untested. No supported
Questa/VCS release/license has been established. Platform shell compatibility,
configured standalone XCI/model products, initialization, memory clocks,
capacities and model fidelity remain prerequisites.

Audit exception: the initial `vitis_hls -version` command automatically updated
`/data2/home/pelorosso/vitis_hls.log` (15:35:44 on 13 November 2026). This was an
unintended write during the read-only audit; it was not removed or altered
further. No build, simulation, upload, installation, configuration change or
board programming was performed. Subsequent inspection used file metadata.
Automatic review also refused full `env.sh` and proprietary-model excerpts;
those files were not exported and are not prerequisites of this delivery.
