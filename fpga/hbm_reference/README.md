# Three-master Bambu vector-add with AMD HBM and VCS

This source checkpoint preserves the functionally passing smoke reference from
17 November 2026. It uses the same vector_add RTL as the Bambu-Ramulator baseline:
three AXI4 masters, 32-bit data, 64-bit addresses and 6-bit IDs. SmartConnect
connects these plus an idle-during-measurement loader to one AXI3 HBM interface
with 256-bit data and 34-bit addresses.

This is a standalone behavioral VCS reference, separate from the older FPGA
deployment/probe helpers in the parent directory. It is not a board deployment
or a validated performance-equivalence result.

## Included files

- prepare_integration.py: validates baseline input/RTL contracts, generates the
  testbench, compiles both exports, rebuilds the current testbench and checks PASS.
- run_integration.sh: loads the recorded Vivado/VCS environment and dispatches steps.
- export_integration.tcl: exports both projects with explicit simulation tops.
- build_bridge.tcl: creates the repaired bridge configuration from scratch.
- fix_bridge.tcl: updates workspaces created with the earlier USER-bearing bridge.
- create_hbm.tcl: initial project/IP creation (formerly inspect_hbm.tcl).
- configure_hbm.tcl: enables SAXI_00 and generates the AMD example project.
- compile_base_libraries.tcl and export_example_vcs.tcl: original setup helpers.
- config/hbm_reference.xci: configuration-only snapshot of the actual HBM IP.
- config/case.json: clocks, addresses, source hashes and input contract.
- config/software-versions.json: tool versions/revisions, not software packages.
- config/bambu-boost-compat.patch: the existing local Bambu CMake requirement change.
- evidence/smoke_axi_1ch.txt: selected actual result lines and known-warning counts.
- tests/: source-only orchestration regressions, with no vendor build invocation.

No compiled files, generated DUT RTL, vendor RTL/encrypted models, project
caches, simulator executables, libraries, full logs or tool installations are
tracked. Existing case inputs are reused from smoke/ in this repository.

## Recorded functional result

Both launches passed the C=A+B oracle, input-preservation checks, guard words and
16-read/8-write traffic counts. Start-to-done and AXI-response completion were
601/601 cycles and 634/634 cycles at 10 ns per kernel cycle (6.01 and 6.34 us).
Initialization, loader writes and checking reads are outside these measurements.

The explicit case-specific adapter converts one 4-byte access to one aligned
32-byte HBM beat. It retains SmartConnect WDATA/WSTRB and returns the complete
read line for word selection. Native IDs are zero and checked. USER and omitted
sidebands are asserted for this exact DUT. This is not a generic burst or MMIO
adapter and does not add another registered pipeline stage.

Repeated tCHmax and IEEE1500 warnings also occur in the original AMD example;
their causes are unresolved. The Ramulator baseline uses separate memory-model
instances per active port, different address mapping, clock scaling and write
completion behavior. The 84-cycle baseline is therefore not yet comparable as an
equivalent memory system. No performance ratio or board timing claim is made.

## Existing validated workspace

The checkpoint deliberately retains the working server layout:

    ~/thesis/hbm-reference-smoke/
    ~/thesis/ramulator-main/.runs/run_20261117_164805_hbm-comparison-baseline/

The baseline must contain its retained RTL and config_snapshot. The existing HBM
workspace contains the generated projects, vendor exports and precompiled base
libraries. These are local prerequisites and are not in Git.

To deploy source updates into that workspace, explicitly copy the source scripts
there. Do not copy build products into the repository. From the repository root:

    reference_source="$PWD/fpga/hbm_reference"
    reference_work="$HOME/thesis/hbm-reference-smoke"
    cp "$reference_source/prepare_integration.py" "$reference_work/"
    cp "$reference_source/run_integration.sh" "$reference_work/"
    cp "$reference_source/export_integration.tcl" "$reference_work/"

Then run each required step separately from the workspace:

    cd "$HOME/thesis/hbm-reference-smoke"
    bash run_integration.sh prepare
    bash run_integration.sh export
    bash run_integration.sh compile
    bash run_integration.sh simulate

For corrections to an already compiled run, reuse it:

    bash run_integration.sh rebuild-testbench
    bash run_integration.sh simulate

Stop on the first failure. Rebuild updates the current testbench/binary and uses
the compiled vendor libraries; simulation overwrites its current log and invalidates
old results. The final functional markers are HBM_BAMBU_TEST_PASSED and FUNCTIONAL_PASS.
Simulator exit code alone is insufficient.

## Initial vendor setup

On a separate licensed machine/workspace, use Vivado 2024.2 and the recorded
versions. The setup Tcl helpers assume the current directory is the external
HBM workspace. Initial ordering is create_hbm.tcl, configure_hbm.tcl, base-library
compilation, example export and bridge creation. The configuration-only XCI
records the actual IP settings for inspection/restoration.

The bootstrap bridge generator has been corrected to describe the validated
USER-free configuration and avoid assigning derived master properties. The
existing project was validated through fix_bridge.tcl. A completely fresh vendor
rebuild of this packaged checkpoint was not performed during the Git save.

Never rerun project-creation helpers over the validated workspace. Reuse the
existing compiled base libraries. The runtime scripts retain the working local
tool and license-server defaults; review these process-environment settings for
another installation. No license file or credential is included.

## Source checks

    python3 -B -m unittest discover -s fpga/hbm_reference/tests -v
    bash -n fpga/hbm_reference/run_integration.sh

These checks do not execute Vivado, VCS, a simulator, or a hardware build.
