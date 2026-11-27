# Experimental memory validation tools

This directory builds configurable reference benches and analyzes AXI traffic.
Use the [recorded single-port comparison](../fpga/hbm_reference/PROBE.md) to
reproduce the measured U55C probe. Use the generator here to explore a
different configured AMD memory model or a range of calibration sizes.

## Native Ramulator calibration with receipts

The experimental calibration runner uses the Ferrandi integration pinned in
[toolchain.json](../fpga/toolchain.json). For a compatible installation set
FPGA_BAMBU and FPGA_BAMBU_SOURCE or supply FPGA_TOOLCHAIN_RECEIPT using the
[FPGA guide](../fpga/README.md). Set RAMULATOR2_DIR to the installed library
prefix for the pinned 2.1 build and FPGA_RAMULATOR_RECEIPT to its
[build receipt](profiles/ramulator-receipt.example.json). Use the upstream
preparation script's `provenance.json` and build logs as build evidence, and
record the SHA-256 of the installed `libramulator.so` selected for the run.

Run from the repository root.

```bash
python3 validation/ramulator.py --tests memory_probe_single --n 513 \
  --board xcu55c --config validation/profiles/hbm2_experimental.yaml \
  --output .fpga/ramulator-513
python3 validation/ramulator.py --tests memory_probe_single --n 0 \
  --board xcu55c --config validation/profiles/hbm2_experimental.yaml \
  --output .fpga/ramulator-0
```

The runner fingerprints the installed toolchain and generates inputs from the
same C probe. Use n for calibration cases. A zero-length probe can complete
without memory traffic. The runner writes experimental results under .fpga.

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

This generator's simulator checks accept Questa 2024.1 SE or VCS
V-2023.12-SP1. Select the simulator in the model configuration and with the
corresponding command option. FPGA_QUESTA and FPGA_VCS select binary
directories. The recorded standalone VCS probe has its own simulator
settings in the [HBM reference](../fpga/hbm_reference/PROBE.md).

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
error range. See the recorded probe for the measured single-port comparison.

## Validation scope

The source tests cover the generated reference bench, AXI monitor and report
checks. A new vendor-memory reference also requires a reviewed XCI,
initialization sequence, simulator and compiled libraries for that exact
configuration. Preserve the raw trace, manifests and reports for each run
before comparing it with physical hardware.
