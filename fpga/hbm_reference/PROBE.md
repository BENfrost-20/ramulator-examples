# One-word U55C probe with the AMD HBM behavioral model

This VCS test runs memory_probe_single with n=1 and repetition 0. It verifies
the five RTL hashes against those recorded for the XO used on the U55C. It
writes the 64-bit base, N and COMMAND via AXI-Lite and reads the wrapper's
64-bit CORE_CYCLES and DRAIN_CYCLES registers. The input is the little-endian
word 0x00000003. The oracle expects 0x13579bdc and 256 bytes of 0xa5 on each
side. The loader writes the guarded 516-byte region and verifies it after
drain, outside the timed interval. It idles for 16 kernel cycles before the
launch sequence. The board host transfers and checks its entire 64 KiB slab,
so memory preconditioning differs.

The probe uses S_A of the validated SmartConnect bridge and the loader uses
S_LOAD. S_B and S_C are idle. The bench measures the kernel side at 100 MHz
and uses the reference HBM AXI period of 2222 ps. The probe address is
0x1200000100 on the kernel side and 0x01000100 in the AMD model, with the
same translation across the guarded region. The bridge adapts the 1-bit AXI
IDs to 6 bits. The HBM model sees the aligned 256-bit beat and original byte
lanes. The deployed MinimalAXI4Adapter leaves USER and REGION undriven, and
the reference bridge omits them.

## Run on Ferrandi 1

Run from the repository root. For the standalone source bundle, use its
path to run_probe.sh in place of the repository path below.

    (
      set -eu
      repo="$HOME/thesis/ramulator-examples"
      prepared="$repo/.fpga/bitstream-xfTkobFQ/probe-single"
      work=$(mktemp -d "$repo/.fpga/probe-vcs.XXXXXX")
      printf 'VCS output directory: %s\n' "$work/run"
      bash "$repo/fpga/hbm_reference/run_probe.sh" --prepared "$prepared" --output "$work/run"
      cat "$work/run/vcs-results.jsonl" \
          "$work/run/vcs-axi.jsonl" \
          "$work/run/vcs-hbm-axi.jsonl"
    )

By default, the driver reads the exports from the passing vector-add run at
~/thesis/hbm-reference-smoke/integration-runs/run_20261117_191951_121861.
Use --vendor-run for another export of the same bridge and HBM
configuration. The driver compiles a private vendor library set using the
existing Vivado base libraries. The original exports, prepared build, source
projects and results are reused as read-only inputs. A fresh output directory
is required for each attempt.

The run records the input, oracle, RTL hashes, testbench and vendor settings
in its output directory. A partial run retains its build and simulation logs
under vcs/. FUNCTIONAL_PASS requires the correct word and guard readback,
the expected AXI traffic on both sides and coherent wrapper counters.

## Native Bambu runs on Ferrandi 1

From the repository root, use the same source, input, compiler and 10 ns
clock target for each native mode.

    bash fpga/hbm_reference/run_bambu_native.sh
    bash fpga/hbm_reference/run_bambu_native.sh 15
    bash fpga/hbm_reference/run_bambu_native.sh --ramulator-config smoke/configs/hbm2_32ch.yaml
    bash fpga/hbm_reference/run_bambu_native.sh --ramulator-config smoke/configs/hbm2_u55c_1800.yaml

The argument 15 sets both memory delays to 15 cycles. Ramulator runs retain
a private copy of the selected YAML and preserve its modeled channel count.
All modes save the native output XML and simulation log under .fpga.
For the separate same-wrapper Ramulator experiment, see the
[FPGA guide](../README.md#ramulator-timing-with-the-deployed-wrapper).

## Compare the runs

All runs passed with n=1, repetition 0, and input word 3. Native Bambu
counts its own testbench interval. The wrapper counters and AXI intervals
use rising kernel clock edges.

| Run | Native Bambu cycles | Wrapper core/drain |
|---|---:|---:|
| Bambu with default memory delays | 9 | |
| Bambu with 15-cycle read and write delays | 34 | |
| Bambu + Ramulator, HBM2 2 Gbps profile | 13 | |
| Bambu + Ramulator, experimental U55C 1800 MT/s profile | 12 | |
| Verilator wrapper + Ramulator, HBM2 2 Gbps profile | | 11/12 |
| VCS + AMD HBM | | 73/74 |
| Physical U55C, matched original and traced runs | | 49/50 |

The native MDPI read callback takes four kernel cycles using the 2 Gbps
profile and three using the experimental 1800 MT/s profile. The two profiles
also differ in clock ratio and geometry. The native runs measure their combined
effect.

For VCS versus the traced U55C, AR to R takes 37 versus 26 cycles. The
interval from R to the later of AW/W takes 2 versus 5 cycles. The later
of AW/W to B takes 31 versus 15 cycles. Those intervals account for the
24-cycle difference. The earlier physical measurement of 63/64 was recorded
in a separate reservation. Consecutive runs without reprogramming still
measured 49/50 on the later reservation.

[Recorded measurements](evidence/probe_n1.json),
[physical AXI trace](evidence/probe_n1_u55c_axi.jsonl) and
[U55C trace build and deployment](board_trace/README.md).
