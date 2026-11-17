# Build Bambu hardware with one command

`build.sh` runs generation, preparation, target-part OOC synthesis/XO packaging,
and Vitis hardware linking. It never programs a card, builds a host, or runs
Ramulator. A connected FPGA and installed deployment shell are not prerequisites
for this build-only entry point. Vendor tools, licenses, target part support and
a compatible development platform remain necessary. Vitis validates the actual
platform/tool combination when linking; an older platform is not assumed valid.

## Site configuration

Copy `build.env.example.sh` to ignored `build.env.sh`. Edit this file once for
tool paths, compiler installation, platform paths and resource defaults.
Command-line flags override environment values; existing environment values
override example defaults. `--env FILE` selects a different site configuration.
An empty setup-script setting disables sourcing that script, which is useful
when linking an existing XO on a machine without Bambu. Do not add license
credentials to the tracked example.

For the existing server installation, preserve the already verified toolchain
receipt in a stable ignored location:

```bash
mkdir -p .fpga/site
cp -n .fpga/bitstream-xfTkobFQ/toolchain-receipt.json .fpga/site/toolchain-receipt.json
cp -n fpga/build.env.example.sh fpga/build.env.sh
```

The receipt must still match the installed Bambu and runtime hashes. This driver
does not admit arbitrary compiler revisions or fabricate build evidence. It
retains the repository's provenance checks and original case recipes/frontend.
Source changes or a new compiler installation require reviewed metadata and a
new receipt. The accepted hardware revision already recorded in the current
checkout is independent of the pinned Ramulator mode.

## Commands

```bash
# Show settings without vendor execution or generated files.
./fpga/build.sh --case memory_probe_single --board xcu55c --period 10 --dry-run

# Complete hardware build. Default jobs=8 and threads=8.
./fpga/build.sh --case memory_probe_single --board xcu55c --period 10 \
  --synth-jobs 16 --impl-jobs 2 --threads 8 --output .fpga/probe-hw-001

# Reuse existing generated RTL; no Bambu invocation.
./fpga/build.sh \
  --generation .fpga/bitstream-xfTkobFQ/generated-clang13/memory_probe_single/generation.json \
  --output .fpga/probe-from-rtl

# Copy an existing prepared integration, excluding old vendor build trees.
./fpga/build.sh --prepared .fpga/bitstream-xfTkobFQ/probe-single \
  --output .fpga/probe-from-prepared

# Link a validated existing XO without repeating HLS or packaging.
./fpga/build.sh --xo .fpga/bitstream-xfTkobFQ/probe-single/fpga_kernel-fixed.xo \
  --board xcu55c --period 10 --output .fpga/probe-from-xo

# Stop after preparation or XO packaging.
./fpga/build.sh --stop-after prepare --output .fpga/probe-prepared
./fpga/build.sh --stop-after package --output .fpga/probe-xo

# Resume verified completed stages; change scheduling for a failed link retry.
./fpga/build.sh --resume --output .fpga/probe-hw-001 \
  --synth-jobs 16 --impl-jobs 2 --threads 8

# Override memory connectivity using an actual resource in the board profile.
./fpga/build.sh --memory 'm_axi_0=HBM[1]' --output .fpga/probe-bank1
```

Cases must be exact supported names, one per invocation. The driver reuses the
existing board registry and deployment profiles. It never silently substitutes
another case, board, part or memory kind. The current 64-bit pointer adapter is
limited to `memory_probe_single`; other changed interfaces fail explicitly.
Use `--no-fix-adapter-log2` to disable the narrowly recognized compatibility
transformation. `--prepared` reuses the supplied integration exactly; it does not
apply transformations to it. Use `--generation` to prepare a new transformed
copy. The `hw_emu` target is an optional artifact build only, without host
execution or emulation runtime setup; the default target is `hw`.
Known single-slab cases retain one shared memory resource across their masters;
the known banked probe uses the corresponding separate resources. An imported
multiport XO without preparation metadata requires explicit `--memory` mappings
for every master rather than guessing its bank/alias layout.

## Automatic tmux protection

By default, an invocation outside tmux creates a dedicated session and attaches
the current terminal. The build continues when the SSH client disconnects or
when you detach with Ctrl+B, then D. Inside an existing tmux session, automatic
mode runs directly and avoids nesting. An explicit `--session NAME` or
`--detach` creates a dedicated session even when called from inside tmux; it
does not nest an attached client.

```bash
# Automatic protection and an explicit session name.
./fpga/build.sh --session fpga-u55c --case memory_probe_single

# Start in the background and immediately return to the SSH prompt.
./fpga/build.sh --detach --session fpga-u55c --case memory_probe_single

# Reattach from another SSH connection.
tmux attach-session -t fpga-u55c

# Explicit direct execution, for example in a batch scheduler or CI.
./fpga/build.sh --no-tmux --case memory_probe_single
```

The launcher prints the session name and reattach command. Noninteractive
invocations start detached automatically. Existing session names are refused
instead of silently attaching to a different build. Completed dedicated panes
remain visible (`remain-on-exit` is set for that window only). The numeric build
exit code is saved under `.fpga/tmux/SESSION-XXXXXXXX/exit-code`; its exact path
is printed at launch. Old launch records are preserved when reusing a name
after closing its previous tmux session. A detached launcher
returning zero means the session started, not that the bitstream build passed.
Use `--no-tmux` when the caller needs the build's synchronous exit code.

The site settings are `FPGA_TMUX_MODE=auto|off|detached`, `FPGA_TMUX_BIN`,
`FPGA_TMUX_ROOT`, and optionally `FPGA_TMUX_SESSION`. Command-line flags take
precedence. A private launcher preserves the selected build/path/license
environment from the current client, even if the tmux server predates that
environment. Launcher files are owner-only and remain in the ignored build
tree. Config paths, working directory and individual argument boundaries are
preserved. Missing tmux is an actionable error; the script does not silently
start an unprotected long build. Help and dry-run bypass tmux entirely.

## Scheduling and cache

- `--jobs N` sets the common synthesis/implementation run limit.
- `--synth-jobs N` and `--impl-jobs N` override it independently, mapping to
  `--vivado.synth.jobs` and `--vivado.impl.jobs`.
  Site defaults can also use `FPGA_SYNTH_JOBS` and `FPGA_IMPL_JOBS`; an explicit
  `--jobs` overrides both environment defaults.
- `--threads N` sets `general.maxThreads` for packaging and through
  `--vivado.param` for linking. Vivado 2024.2 accepts 1..8. Each task has its own
  effective limit; requesting more jobs does not turn one routing task into
  a many-core operation. Multiple implementation jobs are useful only when
  independent implementation runs actually exist.
- The example uses a shared `.fpga/ip-cache/2024.2` directory through
  `--remote_ip_cache`. Unchanged IP synthesis results can be reused across
  builds. `--ip-cache DIR` overrides the path. `--no-ip-cache` explicitly forces
  Vitis to disable IP cache for the link. Cache hits and speedups depend on
  actual configurations; cached implementation/timing is not assumed.

The generation -> preparation -> packaging -> linking dependencies remain
sequential. Settings affect new tool invocations, not a running build. Start
with available CPU/RAM and other users in mind. For the inspected 128-CPU server,
16 synthesis jobs and 8 threads are an optional starting experiment, not a
guaranteed speedup. Do not start a second full build merely to apply these
settings to an existing running build. Cache and saved intermediate files use
disk space; this script never deletes another build or purges a cache.

## Outputs and restart behavior

Without `--output`, the driver makes a unique directory under `FPGA_BUILD_ROOT`.
An existing output directory is refused unless `--resume` is provided. A file
lock prevents simultaneous drivers from using the same output. Each failed
stage retry uses a new attempt directory/log. A failed Vitis link is restarted
from the saved XO and can reuse the shared IP cache; this is not a claim to
resume an arbitrary interrupted place-and-route step. Native Vitis
`--from_step`/`--reuse_impl` require the original project and are not guessed.

`build.json` records source/configuration/platform fingerprints, tool identities,
commands through logs, scheduling settings, completed-stage artifact hashes and
the final xclbin path. `--resume` checks completed hashes and refuses changed
source, RTL, platform or driver inputs. Reuse an explicit earlier artifact in a
new directory when intentionally changing the build inputs. Imported XO builds
record an unknown source case instead of inferring an algorithm from its name.

Success means the requested artifact was produced. It does not mean the design
was functionally simulated, board tested, or that target implementation timing
has been reviewed. Inspect Vitis timing/DRC reports and the routed target DCP;
the OOC report is not target timing closure. The existing
`fpga/tcl/check_implementation.tcl` remains available for that review.

The original `fpga/run.sh` interface is retained. Its platform/runtime receipt
requirements remain unchanged; use `build.sh` for the build-only workflow.

## Packaging fixes

`tcl/package.tcl` now renames the existing control memory map to
`S_AXI_CONTROL`, reacquires renamed objects, updates clock associations after
renaming, and emits a consistent kernel.xml directly. Fixed IP-level FREQ_HZ
is removed for the scalable Alveo clock; the requested frequency is passed to
Vitis. An OOC-only XDC constrains packaging synthesis without overriding the
platform's implementation clocks. Every packaging attempt uses a fresh project
and IP directory. `prepare.py` changes only the exact known log2 function,
preserving newer adapter constants and surrounding code. Originals, diffs and
hashes are kept by the existing preparation code.

## Local checks and limits

Run `python3 -m unittest discover -s fpga/tests -v`. The driver tests use clearly
labeled fake vendor/compiler tools to verify command wiring, artifact checks,
copy/reuse, failure propagation and resume behavior. They are not FPGA synthesis
or simulation. Tmux launcher tests use a stub and a local PTY to check attachment,
argument/environment preservation, failure status and nesting behavior; they do
not create sessions on the server. Existing deployment/native packing tests are
also retained.
The integrated Tcl corrections require the next authorized server packaging run
for vendor validation. No server modification/build was performed by the
assistant while preparing this patch.

References: [AMD 2024.2 Vivado options](https://docs.amd.com/r/2024.2-English/ug1702-vitis-accelerated-reference/vivado-Options),
[Vivado multithreading](https://docs.amd.com/r/2024.2-English/ug904-vivado-implementation/Multithreading-with-the-Vivado-Tools),
[Vitis IP cache](https://docs.amd.com/r/2024.2-English/ug1702-vitis-accelerated-reference/v-General-Options),
[kernel XML](https://docs.amd.com/r/2024.2-English/ug1702-vitis-accelerated-reference/RTL-Kernel-XML-File).
