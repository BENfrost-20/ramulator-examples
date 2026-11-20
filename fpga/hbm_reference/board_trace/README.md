# U55C AXI trace on HACC

This experiment records the missing kernel-side AXI timestamps for
memory_probe_single, n=1, repetition 0, input bytes 03 00 00 00. The recorder
uses the rising ap_clk edge which samples START as cycle zero. It captures
the first VALID and the first VALID && READY handshake on AR, R, AW, W and B,
and the wrapper's DONE and DRAIN edges. It also records the AR/AW addresses,
IDs, WSTRB and response status. The host checks the oracle and all guard bytes
before publishing the result.

The source package stages a fresh copy of the measured FPGA wrapper and checks
all five baseline RTL SHA-256 values. The core, Bambu library and drain RTL
are copied verbatim. The wrapper adds a passive recorder and readback registers
from 0x90 through 0xe4. The original control offsets and counter conditions
remain intact. The phase and placement of the new image can still differ from
the baseline. The host requires a trace signature and rejects an incomplete,
duplicated, overflowing or inconsistent snapshot.

## Build on Ferrandi 1

From the repository root on Ferrandi 1, run in a tmux session.

    repo="$PWD"
    bash fpga/hbm_reference/board_trace/build_trace.sh "$repo"

For a standalone source bundle, substitute the path to the extracted
build_trace.sh. Use that same path for the resume command below.

The script uses the existing Bambu-generated RTL, Vivado/Vitis 2024.2 and the
same Vitis platform, 100 MHz kernel request and HBM[0] connectivity used by the
previous U55C image. It stages and packages an XO, links a new xclbin, runs the
routed setup/hold and routing checks, and verifies the new xclbin's interface
UUID and reported clocks against the baseline. It prints HACC_TRACE_BUNDLE
with an absolute path on success. No FPGA is programmed on Ferrandi.

If the link succeeded and checkpoint discovery failed, identify the final
routed checkpoint in the saved Vitis work tree and resume the checks and
archive export using the build directory printed on the first line:

    bash fpga/hbm_reference/board_trace/build_trace.sh --finish "$build_dir" "$repo" "$routed_checkpoint"

The bundle contains the linked xclbin, host source and oracle, input RTL hashes,
connectivity, implementation reports, reference VCS trace and checksums.
Transfer it through the Mac using the Ferrandi network first, then upload it
to shared HACC storage using the HACC network. Keep the old xclbin and its
result directory for comparison.

## Run on HACC

Extract the traced bundle into a new directory in the shared HACC home.
Set artifact to the absolute path of the archive uploaded from Ferrandi.

    run_dir=$(mktemp -d "$HOME/hacc-axi-trace.XXXXXX")
    tar -xzf "$artifact" -C "$run_dir"
    cd "$run_dir"
    sha256sum -c SHA256SUMS

On the reserved U55C node, enter the same run_dir. Source XRT, run
xrt-smi examine, and compare the shell and BDF with the reservation and the
bundle manifest. The expected shell is xilinx_u55c_gen3x16_xdma_base_3.
Set bdf to the PCI address of that reserved U55C.

    source /opt/hdev/cli/enable/xrt
    xrt-smi examine
    bash run_hacc.sh "$bdf"

The script builds the staged C++ host if necessary and deliberately loads the
traced image on that device. You can compile it ahead of the reservation with
python3 -B build.py on a host with the same XRT installation. The run writes
board-results.jsonl, board-axi.jsonl, input-1-0.bin, comparison.json, the
host log and node information under a fresh board-run directory.

## Interpret the result

The original_u55c_counters and instrumented_matches_original fields in
comparison.json refer to the historical 63/64 observation. The
[matched original and traced images](../evidence/probe_n1.json) later
reproduced 49/50 on HACC. Read vcs_minus_board_intervals_cycles to compare
the new trace with VCS. Positive values mean VCS was slower in that
interval. The intervals cover START to AR, AR to R, R to the later of AW/W,
that edge to B, B to DONE and DONE to DRAIN. They sum to the wrapper difference.
The board's VALID-to-handshake distances identify interface stalls.

Use alternating runs to check whether the original and traced images have
the same wrapper totals on the reservation. The interval comparison
describes the traced run. A kernel-side trace measures the
path through the shell and HBM together. Splitting those contributions on real
hardware also requires observation at the HBM-side interface.

Local verification used the real probe RTL with a synthetic AXI responder.
Original and traced wrapper counters matched, including a deliberately
staggered AW/W acceptance. AXI-Lite readback was checked against the
independently observed pins. The host decoder and comparison were exercised
with those captured events. Build probe-board-trace.uqm1l1 passed the
routed checks on Ferrandi and the probe passed on hacc-u55c-08. The HACC
runner uses XRT initialized in the calling shell.
