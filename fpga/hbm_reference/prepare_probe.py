#!/usr/bin/env python3
"""Run the deployed one-word U55C probe against the standalone AMD HBM model."""

import argparse
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys

import prepare_integration as reference


HERE = Path(__file__).resolve().parent
TOP = "tb_hbm_probe"
RTL_SHA256 = {
    "control.sv": "19ad9b80776bf90413d6b3909df0dd83e6dce014e98cbcb1dbacb583b1a29f8f",
    "drain.sv": "a4b9bb2d9d54d161abb212d69c7d1e5a029d160e7fae07ed320710f1ffffc775",
    "fpga_kernel.sv": "25169be87833d7708da114368f5db1a690647301d956bb4b67b644fcd5fed988",
    "memory_probe.v": "4b9a7ff81870c0b8b82424f537fb587d58b51f7e436266f1c547626059db5a53",
    "panda_libtech.v": "dcb4a37edfb00045150326cf15377be9375601be1acc3c5b3ab88478249dbee0",
}
KERNEL_SLAB = 0x1200000000
HBM_SLAB = 0x01000000
GUARD = 256
INPUT = bytes.fromhex("03000000")
EXPECTED = (int.from_bytes(INPUT, "little") ^ 0x13579BDF).to_bytes(4, "little")
ID_FIELDS = {"arid", "awid", "rid", "bid"}
CONTROL_IN = {
    "awaddr": 8, "awvalid": 1, "wdata": 32, "wstrb": 4, "wvalid": 1, "bready": 1,
    "araddr": 8, "arvalid": 1, "rready": 1,
}
CONTROL_OUT = {
    "awready": 1, "wready": 1, "bresp": 2, "bvalid": 1,
    "arready": 1, "rdata": 32, "rresp": 2, "rvalid": 1,
}


def testbench():
    lines = [
        chr(96) + "timescale 1ps/1ps", "module " + TOP + ";",
        "  reg kernel_clk = 0, memory_clk = 0, ref_clk = 0, resetn = 0;",
        "  wire apb_complete, cattrip;",
        "  wire [5:0] hbm_rid, hbm_bid;",
        "  wire [31:0] write_parity, read_parity;",
        "  localparam [63:0] KERNEL_SLAB = 64'h%x, HBM_SLAB = 64'h%x;" % (KERNEL_SLAB, HBM_SLAB),
        "  localparam integer GUARD_BYTES = %d;" % GUARD,
        "  localparam [31:0] WORD_IN = 32'h%08x, WORD_OUT = 32'h%08x;"
        % (int.from_bytes(INPUT, "little"), int.from_bytes(EXPECTED, "little")),
    ]
    decl = reference.decl
    for field, width in dict(reference.MASTER_OUT, **reference.MASTER_IN).items():
        lines.append(decl("wire", width, "s_" + field + " [0:3]"))
        lines.append(decl("wire", 1 if field in ID_FIELDS else width, "probe_" + field))
    for field, width in reference.MASTER_OUT.items():
        idle = "1" if field in ("awburst", "arburst", "wlast") else (
            "2" if field in ("awsize", "arsize") else "0")
        lines.append(decl("reg", width, "ld_" + field + " = " + idle))
        lines.append("  assign s_%s[3] = ld_%s;" % (field, field))
        lines.append("  assign s_%s[1] = '0, s_%s[2] = '0;" % (field, field))
        value = "probe_" + field
        if field in ("araddr", "awaddr"):
            value += " - KERNEL_SLAB + HBM_SLAB"
        elif field in ID_FIELDS:
            value = "{5'b0, " + value + "}"
        lines.append("  assign s_%s[0] = %s;" % (field, value))
    for field in reference.MASTER_IN:
        select = "[0]" if field in ID_FIELDS else ""
        lines.append("  assign probe_%s = s_%s[0]%s;" % (field, field, select))
    for field, width in dict(reference.NATIVE_OUT, **reference.NATIVE_IN).items():
        lines.append(decl("wire", width, "m_" + field))
    for field, width in CONTROL_IN.items():
        lines.append(decl("reg", width, "ctl_" + field + " = 0"))
    for field, width in CONTROL_OUT.items():
        lines.append(decl("wire", width, "ctl_" + field))

    dut = [("ap_clk", "kernel_clk"), ("ap_rst_n", "resetn")]
    dut += [("s_axi_control_" + field, "ctl_" + field) for field in (*CONTROL_IN, *CONTROL_OUT)]
    dut += [("m_axi_0_" + field, "probe_" + field)
            for field in (*reference.MASTER_OUT, *reference.MASTER_IN)]
    # The deployed MinimalAXI4Adapter leaves USER and REGION undriven.
    dut += [("m_axi_0_" + field, "") for field in reference.OMITTED]
    lines.append(reference.instance("fpga_kernel", "dut", dut))
    lines.extend(reference.vendor_instances())
    lines.append((HERE / (TOP + ".sv")).read_text())
    lines.append(reference.TB_LOADER)
    lines.append("endmodule\n")
    return "\n".join(lines)


def prepare(prepared, vendor_run, out):
    manifest_path = prepared / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    abi = manifest["abi"]
    if (manifest["case"] != "memory_probe_single" or manifest["banks"] != 1
            or manifest["axi_ports"] != ["m_axi_0"] or manifest["rtl_sha256"] != RTL_SHA256
            or abi["version"] != 1 or abi["guard_bytes"] != GUARD
            or abi["registers"] != dict(COMMAND=0, GENERATION=4, N=16, BASE0=32,
                                        CORE_CYCLES=128, DRAIN_CYCLES=136)
            or abi["status"] != dict(BUSY=1, CORE_DONE=2, DRAINED=4, ERROR=8)):
        raise ValueError("Prepared manifest does not match the measured U55C probe and ABI")
    bridge = (reference.ROOT / "bridge-project/smoke_bridge.gen/sources_1/bd/smoke_bridge"
              / "hdl/smoke_bridge_wrapper.v")
    reference.check_ports(bridge, "smoke_bridge_wrapper", reference.expected_ports()[1])
    reference.verify_export(vendor_run)
    for name, digest in RTL_SHA256.items():
        if reference.sha(prepared / "rtl" / name) != digest:
            raise ValueError("Prepared RTL hash mismatch: " + name)

    out.mkdir()
    print("PROBE_RUN:", out, flush=True)
    (out / "rtl").mkdir()
    for name, digest in RTL_SHA256.items():
        target = out / "rtl" / name
        shutil.copyfile(prepared / "rtl" / name, target)
        if reference.sha(target) != digest:
            raise ValueError("Copied RTL hash mismatch: " + name)
    shutil.copyfile(manifest_path, out / "prepared-manifest.json")
    (out / "input-1-0.bin").write_bytes(INPUT)
    (out / "expected-1-0.bin").write_bytes(EXPECTED)
    tb = out / (TOP + ".sv")
    tb.write_text(testbench())
    (out / "simulate.do").write_text("run 1ms\nquit\n")
    receipt = {
        "mode": "vcs_amd_hbm", "host": socket.gethostname(),
        "case": "memory_probe_single", "n": 1, "repetition": 0,
        "rtl_sha256": RTL_SHA256, "prepared_path": str(prepared),
        "prepared_manifest_sha256": reference.sha(out / "prepared-manifest.json"),
        "input_sha256": reference.sha(out / "input-1-0.bin"),
        "testbench_sha256": reference.sha(tb), "bridge_wrapper_sha256": reference.sha(bridge),
        "vendor_run": str(vendor_run), "kernel_period_ps": 10000, "hbm_axi_period_ps": 2222,
        "kernel_data_address": hex(KERNEL_SLAB + GUARD), "hbm_data_address": hex(HBM_SLAB + GUARD),
        "loader_guard_bytes_each_side": GUARD, "loader_idle_ap_clk_cycles": 16,
    }
    settings = out / "vendor-config"
    settings.mkdir()
    for name, glob_root in (("hbm_reference.xci", reference.ROOT / "example/hbm_reference_ex"),
                            ("smoke_bridge.bd", reference.ROOT / "bridge-project/smoke_bridge.srcs")):
        receipt[name + "_sha256"] = {}
        for path in sorted(glob_root.rglob(name)):
            snapshot = settings / (str(len(receipt[name + "_sha256"])) + "-" + name)
            shutil.copyfile(path, snapshot)
            receipt[name + "_sha256"][str(path)] = reference.sha(snapshot)
    (out / "manifest.json").write_text(json.dumps(receipt, indent=2) + "\n")


def run_probe(out, vendor_run):
    build = reference.compile_vendor(out, vendor_run)
    work = out / "vcs"
    reference.command(["vlogan", "-full64", "-work", "xil_defaultlib", "-sverilog",
                       "+incdir+" + str(out / "rtl"), "-l", "kernel-compile.log",
                       *(out / "rtl" / name for name in RTL_SHA256), out / (TOP + ".sv")], work)
    reference.command(["vcs", "-full64", "-debug_acc", "-t", "ps", "-licqueue",
                       "-l", "elaborate.log", "xil_defaultlib." + TOP, "xil_defaultlib.glbl",
                       "-o", TOP + "_simv"], work)
    (out / "build.json").write_text(json.dumps(build, indent=2) + "\n")
    print("SIMULATING:", work / "simulate.log", flush=True)
    with (work / "simulator-stdout.log").open("w") as stdout:
        subprocess.run([work / (TOP + "_simv"), "-ucli", "-licqueue", "-l", "simulate.log",
                        "-do", out / "simulate.do"], cwd=work, stdout=stdout,
                       stderr=subprocess.STDOUT, check=True)

    result_path = work / "vcs-results.jsonl"
    if not result_path.is_file():
        raise ValueError("Missing PASS result; inspect " + str(work / "simulate.log"))
    result = json.loads(result_path.read_text())
    expected = dict(functional_status="pass", case="memory_probe_single", n=1,
                    repetition=0, axi_reads=1, axi_writes=1)
    if any(result.get(field) != value for field, value in expected.items()):
        raise ValueError("Invalid probe result: " + str(result))
    if not 0 < result["core_cycles"] < result["drain_cycles"]:
        raise ValueError("Invalid core/drain cycles: " + str(result))
    for filename in ("vcs-axi.jsonl", "vcs-hbm-axi.jsonl"):
        trace = (work / filename).read_text()
        events = [json.loads(line) for line in trace.splitlines()]
        by_channel = {event["event"]: event for event in events}
        if len(events) != 5 or set(by_channel) != {"AR", "AW", "B", "R", "W"}:
            raise ValueError("Expected one handshake per channel in " + filename)
        t = {channel: event["time_ps"] for channel, event in by_channel.items()}
        if t["AR"] > t["R"] or t["R"] > min(t["AW"], t["W"]) or max(t["AW"], t["W"]) > t["B"]:
            raise ValueError("Unexpected handshake ordering in " + filename)
        if filename == "vcs-axi.jsonl":
            cycle = {channel: event["axi_cycle"] for channel, event in by_channel.items()}
            result["ar_to_r_cycles"] = cycle["R"] - cycle["AR"]
            result["aw_w_to_b_cycles"] = cycle["B"] - max(cycle["AW"], cycle["W"])
        (out / filename).write_text(trace)
    (out / result_path.name).write_text(json.dumps(result, separators=(",", ":")) + "\n")
    print((out / result_path.name).read_text(), end="")
    print("FUNCTIONAL_PASS:", out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--vendor-run", type=Path,
                        default=reference.ROOT / "integration-runs/run_20261117_191951_121861")
    parser.add_argument("--output", type=Path, required=True, help="New run directory")
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    prepared, vendor_run, out = (path.resolve() for path in
                                 (args.prepared, args.vendor_run, args.output))
    for old_run in (prepared, vendor_run, reference.ROOT / "bridge-project",
                    reference.ROOT / "example"):
        if out == old_run or old_run in out.parents:
            parser.error("--output must be separate from the prepared build and vendor assets")
    prepare(prepared, vendor_run, out)
    if not args.prepare_only:
        run_probe(out, vendor_run)


if __name__ == "__main__":
    try:
        main()
    except (KeyError, ValueError, OSError, subprocess.CalledProcessError) as error:
        print("STOP:", error, file=sys.stderr)
        sys.exit(1)
