# Build on Ferrandi and run on HACC

Build the FPGA image on `ferrandi-1`. Transfer one archive through the Mac, then compile the small C++ host with the XRT installed on HACC. Stage the download and compile the host before booking an experiment node when the build node has the same XRT installation. Compile the host on the experiment node when it uses a different XRT installation.

See the [hardware and node reference](hardware/README.md) for observed HACC
shells, platform identifiers, memory maps and clocks.

## 1. Configure the site paths

On the Mac, copy `fpga/deploy.env.example` to `fpga/deploy.env` and edit the values. Use SSH aliases or `user@host`. Use absolute paths for the two remote artifact directories. The Ferrandi artifact directory must be the directory used for the export in step 2. The HACC artifact directory should be under your shared HACC home so that it is visible from both the build and experiment nodes.

```bash
cp fpga/deploy.env.example fpga/deploy.env
```

`fpga/deploy.env` is ignored by Git. The transfer script sources it as local shell configuration. Use `--config /path/to/deploy.env` or `FPGA_DEPLOY_CONFIG` to select a different file. Authenticate through SSH and the appropriate VPN.

## 2. Build and export on Ferrandi

Use the Bambu environment and platform receipt described in the [FPGA deployment guide](README.md). For the U55C smoke test on HACC, the tested hardware image was linked against `xilinx_u55c_gen3x16_xdma_3_202210_1`. Use the actual `.xpfm` and verified platform receipt for the destination board. The hardware generator also accepts the Ferrandi build at `622610fd` with the existing source or build receipt checks. The locally patched Ferrandi toolchain needs its verified build/install receipt. Make `xclbinutil` available on the build machine for export. Set `FPGA_XCLBINUTIL` to its full path if it is outside `PATH`.

From the Ferrandi checkout, set `archive_dir` to the path configured as `FPGA_FERRANDI_ARTIFACT_DIR` on the Mac. These commands use a unique local build directory and keep the output of each phase together. Run each phase after the previous one succeeds.

```bash
archive_dir="$PWD/.fpga/deploy"
mkdir -p .fpga
run=$(mktemp -d "$PWD/.fpga/hacc-u55c.XXXXXXXX")
export CLOCK_PERIOD_NS=10

./fpga/run.sh generate --board xcu55c --tests memory_probe_single \
  --output "$run/generated"

generation="$run/generated/memory_probe_single/generation.json"
rtl_dir=$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["rtl_dir"])' "$generation")
./fpga/run.sh prepare --board xcu55c --tests memory_probe_single \
  --rtl-dir "$rtl_dir" --generation "$generation" --fix-adapter-log2 \
  --output "$run/prepared"

./fpga/run.sh package --prepared "$run/prepared"
./fpga/run.sh link --prepared "$run/prepared" --target hw \
  --bundle "$archive_dir/${run##*/}.tar.gz"
```

`--fix-adapter-log2` applies the bounded-loop fix to the specific adapter layout used by this probe. Omit the option for a toolchain that does not need the fix. The 64-bit pointer and address support is scoped to the inspected single-port probe. The packaging flow associates the clock and AXI interfaces, names the control memory map consistently, and leaves the Alveo frequency selection to Vitis.

`--bundle` runs after a successful hardware link. The archive contains the `.xclbin`, host C++ sources, generated ABI and case headers, the oracle sources and a standalone `build.py`. It includes a SHA-256 list and an export manifest with the source revisions and fingerprints, board, memory connectivity, platform and interface UUID, and measured phase durations. `build.json` in the link directory records hardware build times and links the measurements to the specific image. Review routed timing, routing status and DRC reports before deploying a new design. The archive excludes generated Vivado work trees, the XO and the Linux host executable.

## 3. Transfer with one VPN at a time

Run from the Mac checkout. Replace the example archive name with the name printed by the build.

```bash
# With the Ferrandi VPN connected
./fpga/transfer.sh pull hacc-u55c.ABC12345.tar.gz

# After switching to the ETH VPN
./fpga/transfer.sh push hacc-u55c.ABC12345.tar.gz
```

`push` verifies the archive hash before making the upload visible in the configured HACC directory. The transfer commands refuse to replace an existing bundle.

## 4. Compile and run on HACC

Extract the archive into a new directory in the shared HACC home. Replace the example archive path with the configured `FPGA_HACC_ARTIFACT_DIR` and the artifact name.

```bash
artifact="$HOME/hacc-fpga/hacc-u55c.ABC12345.tar.gz"
run_dir=$(mktemp -d "$HOME/hacc-run.XXXXXXXX")
cd "$run_dir"
tar -xzf "$artifact"
sha256sum -c SHA256SUMS && python3 build.py
```

`build.py` uses `g++` and the local XRT headers and library. Set `XILINX_XRT` or pass `--xrt-root /path/to/xrt` when XRT lives outside `/opt/xilinx/xrt`. The host build duration is recorded in `host-build.json`.

During the booking, SSH into the exact reserved U55C node, enter the same `run_dir`, and use the PCIe address reported by `xrt-smi examine`. Compare the reported shell with the deployment platform and interface UUID in the manifest. For the documented U55C deployment platform, the corresponding shell is `xilinx_u55c_gen3x16_xdma_base_3` and the interface UUID is `b7ac1abe-1e3e-1cb6-86d5-a81232452676`.

```bash
source /opt/hdev/cli/enable/xrt
xrt-smi examine
read -r -p 'PCIe address of the reserved U55C: ' bdf
env -u XCL_EMULATION_MODE ./host fpga_kernel.xclbin "$bdf" 1 1 60 board-results.jsonl
```

The last command is the explicit hardware smoke test. It loads the application image, runs the probe once with one word, and checks the output and buffer guards. Expect `memory_probe_single PASS`. Other cases can have fixed input sizes. See the [host execution arguments](README.md#host-execution-deliberate-later-step). If a timeout leaves the host process running, arrange recovery with HACC support before terminating it or reusing the accelerator.

## Reuse a completed stage

| Change | Start here |
|---|---|
| Host source only | Run `bundle` against the existing hardware link, transfer the new archive, and rebuild the host. |
| HBM resource mapping | Run `link` again with the same prepared directory and XO, a fresh `--link-dir` and the new `--memory PORT=RESOURCE` assignments. |
| Packaging or RTL wrapper | Run `prepare` from the existing generation receipt and RTL, then package and link. |
| Kernel, Bambu options, or generated RTL | Start at `generate`. |

```bash
# Export a new host revision from an already linked hardware image
./fpga/run.sh bundle --prepared "$run/prepared" \
  --output "$archive_dir/${run##*/}-host-v2.tar.gz"

# Relink the same XO to another verified resource
./fpga/run.sh link --prepared "$run/prepared" --target hw \
  --link-dir "$run/hw-hbm1" --memory 'm_axi_0=HBM[1]' \
  --bundle "$archive_dir/${run##*/}-hbm1.tar.gz"
```

Use `bundle --link-dir` when exporting a link made with a custom link directory. Keep the generated RTL, `.xo`, build manifests and logs under `.fpga` on the build machine for reuse. Keep source code, build recipes and configuration examples in Git. Share a bundle by file transfer or through an authorized artifact location associated with the source revision.
