#!/usr/bin/env python3
"""Stage a trace-only variant of the verified single-port U55C probe."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile


SOURCES = Path(__file__).resolve().parent
RTL = {
    "control.sv": "19ad9b80776bf90413d6b3909df0dd83e6dce014e98cbcb1dbacb583b1a29f8f",
    "drain.sv": "a4b9bb2d9d54d161abb212d69c7d1e5a029d160e7fae07ed320710f1ffffc775",
    "fpga_kernel.sv": "25169be87833d7708da114368f5db1a690647301d956bb4b67b644fcd5fed988",
    "memory_probe.v": "4b9a7ff81870c0b8b82424f537fb587d58b51f7e436266f1c547626059db5a53",
    "panda_libtech.v": "dcb4a37edfb00045150326cf15377be9375601be1acc3c5b3ab88478249dbee0",
}
XCLBIN = "3e9d5cea87e165df2f7f42b40be6890ce729870a2e240a7be66d6ea6822e5e1e"
HOST = "d4385bb746bde7903699c15234cdab704f3b54590920371cf8310314a6ddb4d3"
REGISTERS = {
    "ID": 0x90, "SEEN": 0x94, "FLAGS": 0x98,
    **{name: 0xa0 + 4 * index for index, name in enumerate(
        ("START", "AR", "R", "AW", "W", "B", "DONE", "DRAIN",
         "AR_VALID", "AW_VALID", "W_VALID", "R_VALID", "B_VALID"))},
    "ARADDR_LO": 0xd4, "ARADDR_HI": 0xd8, "AWADDR_LO": 0xdc, "AWADDR_HI": 0xe0,
    "ATTRIBUTES": 0xe4,
}
AXI_SIGNALS = (
    "arvalid arready rvalid rready awvalid awready wvalid wready bvalid bready "
    "araddr awaddr arid rid awid bid rlast wlast wstrb rresp bresp"
).split()


def digest(path):
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError("Expected one source insertion point: " + old.strip())
    return source.replace(old, new, 1)


def instrument_control(text):
    text = replace_once(text, "output reg [63:0] core_cycles, output reg [63:0] drain_cycles",
                        "output reg [63:0] core_cycles, output reg [63:0] drain_cycles,\n"
                        " output wire trace_done_sample, trace_drain_sample,\n"
                        " input wire trace_mmio_valid, input wire [31:0] trace_mmio_data")
    text = replace_once(text, "   if(active && !core_done && done_core && !done_previous) begin",
                        "   if(trace_done_sample) begin")
    text = replace_once(text, "   if(active && core_done && drained) begin",
                        "   if(trace_drain_sample) begin")
    text = replace_once(text, " reg [63:0] elapsed;\n",
                        " reg [63:0] elapsed;\n"
                        " assign trace_done_sample=active && !core_done && done_core && !done_previous;\n"
                        " assign trace_drain_sample=active && core_done && drained;\n")
    return replace_once(text, "     default: begin\n      if(s_axi_control_araddr>=8'h20",
                        "     default: begin\n"
                        "      if(trace_mmio_valid) s_axi_control_rdata<=trace_mmio_data;\n"
                        "      else if(s_axi_control_araddr>=8'h20")


def instrument_wrapper(text):
    text = replace_once(text, "wire [0:0] drained,errors;\n",
                        "wire [0:0] drained,errors;\n"
                        "wire trace_done_sample, trace_drain_sample, trace_mmio_valid;\n"
                        "wire [31:0] trace_mmio_data;\n")
    text = replace_once(text, ".core_cycles(), .drain_cycles());",
                        ".core_cycles(), .drain_cycles(), "
                        ".trace_done_sample(trace_done_sample), .trace_drain_sample(trace_drain_sample), "
                        ".trace_mmio_valid(trace_mmio_valid), .trace_mmio_data(trace_mmio_data));")
    ports = [
        ("clk", "ap_clk"), ("resetn", "ap_rst_n"), ("start", "start_core"),
        ("done_sample", "trace_done_sample"), ("drain_sample", "trace_drain_sample"),
        ("mmio_addr", "s_axi_control_araddr"), ("mmio_valid", "trace_mmio_valid"),
        ("mmio_data", "trace_mmio_data"),
    ]
    ports += [(field, "m_axi_0_" + field) for field in AXI_SIGNALS]
    instance = "fpga_probe_trace trace_recorder(\n" + ",\n".join(
        f" .{port}({net})" for port, net in ports
    ) + "\n);\n"
    return replace_once(text, "\nendmodule", "\n" + instance + "endmodule")


def instrument_host(text):
    text = replace_once(text, '#include "abi.hpp"', '#include "abi.hpp"\n#include "probe_trace.hpp"')
    text = replace_once(text, "argc>3?std::stoul(argv[3]):case_n",
                        "argc>3?std::stoul(argv[3]):1")
    text = replace_once(text, "argc>4?std::stoul(argv[4]):2",
                        "argc>4?std::stoul(argv[4]):1")
    text = replace_once(text, "  validate_n(n);", """  validate_n(n);
  if(n!=1 || reps!=1) throw std::runtime_error("Trace host requires N=1 and REPETITIONS=1");""")
    text = replace_once(text, '  xrt::ip ip(device,uuid,"fpga_kernel:{fpga_kernel_1}");',
                        '''  xrt::ip ip(device,uuid,"fpga_kernel:{fpga_kernel_1}");
  if(ip.read_register(probe_trace::signature_register)!=probe_trace::signature)
   throw std::runtime_error("The loaded image has no compatible AXI trace recorder");''')
    text = replace_once(text, "  for(unsigned rep=0;rep<reps;++rep) {",
                        '''  std::ofstream trace_file(result_directory/"board-axi.jsonl");
  if(!trace_file) throw std::runtime_error("Cannot open board-axi.jsonl");
  for(unsigned rep=0;rep<reps;++rep) {''')
    text = replace_once(text, '   file<<"{\\"mode\\":\\""<<(std::getenv("XCL_EMULATION_MODE")',
                        '''   const auto output_seconds=std::chrono::duration<double>(
       std::chrono::steady_clock::now()-output_begin).count();
   const auto data_address=bos[base_register_bank[0]]->address()+abi::GUARD;
   const auto trace=probe_trace::read_snapshot(
       [&](unsigned offset) { return ip.read_register(offset); }, core, drain, data_address);
   if(ip.read_register(abi::GENERATION)!=previous+1)
    throw std::runtime_error("Kernel generation changed during trace readout");
   probe_trace::write_events(trace_file, trace, rep);
   file<<"{\\"mode\\":\\""<<(std::getenv("XCL_EMULATION_MODE")''')
    return replace_once(text,
                        "std::chrono::duration<double>(std::chrono::steady_clock::now()-output_begin).count()",
                        "output_seconds")


def prepare(repo, prepared, out):
    from fpga.catalog import registry
    from fpga.hostgen import write as hostgen
    from fpga.prepare import ABI, make_abi_header

    info = json.loads((prepared / "manifest.json").read_text())
    gen = info["generation"]
    if (info["case"] != "memory_probe_single" or info["axi_ports"] != ["m_axi_0"]
            or info["banks"] != 1 or info["abi"] != ABI or info["rtl_sha256"] != RTL
            or gen["case"] != info["case"] or gen["board"] != "xcu55c" or gen["period_ns"] != 10):
        raise ValueError("Prepared design does not match the measured U55C probe")
    for name, expected in RTL.items():
        if digest(prepared / "rtl" / name) != expected:
            raise ValueError("Prepared RTL hash mismatch: " + name)
    source_host = repo / "fpga/host"
    if digest(source_host / "host.cpp") != HOST:
        raise ValueError("Host source differs from the verified U55C host")
    if any(c in str(out) for c in "{}\n\r"):
        raise ValueError("Unsupported Tcl source path")

    out.mkdir()
    rtl = out / "rtl"
    rtl.mkdir()
    for name in RTL:
        source = prepared / "rtl" / name
        target = rtl / name
        shutil.copyfile(source, target)
        if digest(target) != RTL[name]:
            raise ValueError("Copied RTL hash mismatch: " + name)
    wrapper, control = rtl / "fpga_kernel.sv", rtl / "control.sv"
    wrapper.write_text(instrument_wrapper(wrapper.read_text()))
    control.write_text(instrument_control(control.read_text()))
    shutil.copyfile(SOURCES / "probe_trace.sv", rtl / "probe_trace.sv")
    (out / "sources.tcl").write_text("set rtl_files [list " + " ".join(
        "{" + str(path) + "}" for path in sorted(rtl.iterdir())
    ) + "]\n")
    register_tcl = (prepared / "registers.tcl").read_text()
    for name, offset in REGISTERS.items():
        register_tcl += (f"\nset reg [ipx::add_register TRACE_{name} $ab]\n"
                         f"set_property address_offset {offset} $reg\n"
                         "set_property size 32 $reg\n")
    (out / "registers.tcl").write_text(register_tcl)
    host = out / "host"
    host.mkdir()
    make_abi_header(host)
    hostgen(registry()[info["case"]], info, host, require_source_hashes=True)
    for name in ("build.py", "buffers.hpp"):
        shutil.copyfile(source_host / name, host / name)
    (host / "host.cpp").write_text(instrument_host((source_host / "host.cpp").read_text()))
    shutil.copyfile(SOURCES / "probe_trace.hpp", host / "probe_trace.hpp")
    shutil.copyfile(prepared / "manifest.json", out / "baseline-prepared.json")
    manifest = {
        "case": info["case"], "n": 1, "board": gen["board"], "memory": {"m_axi_0": "HBM[0]"},
        "kernel_clock_mhz": 100, "hbm_axi_clock_mhz": 450, "trace_layout": "AXI1",
        "registers": REGISTERS, "baseline_rtl_sha256": RTL,
        "prepared_rtl_sha256": {p.name: digest(p) for p in sorted(rtl.iterdir())},
        "baseline_manifest_sha256": digest(out / "baseline-prepared.json"),
        "timing_origin": "rising ap_clk sampling START at cycle zero",
    }
    (out / "trace-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("TRACE_PREPARED:", out)


def bundle(out, linked, timing, baseline, result, xclbinutil):
    from fpga.deploy import xclbin_metadata
    from fpga.run import kernel_metadata

    xclbin = linked / "fpga_kernel.xclbin"
    if digest(baseline) != XCLBIN:
        raise ValueError("Baseline xclbin differs from the image measured on the U55C")
    kernel_metadata(out / "fpga_kernel.xo", ["m_axi_0"])
    original = xclbin_metadata(baseline, xclbinutil)
    image = xclbin_metadata(xclbin, xclbinutil)
    for name in ("platform_vbnv", "interface_uuid"):
        if image[name] != original[name]:
            raise ValueError("Instrumented xclbin platform or interface differs from baseline")
    info = (linked / "xclbin-info.txt").read_text()
    if (not re.search(r"Name:\s+hbm_aclk\s+Index:\s+\d+\s+Type:\s+SYSTEM\s+Frequency:\s+450 MHz", info)
            or not re.search(r"Name:\s+ulp_ucs_aclk_kernel_00\s+Type:\s+SCALABLE\s+"
                             r"Default Freq:\s+\d+ MHz\s+Requested Freq:\s+100 MHz\s+"
                             r"Achieved Freq:\s+100 MHz", info)):
        raise ValueError("Instrumented xclbin reports different kernel/HBM clocks")
    expected_mapping = 'sp=fpga_kernel_1.m_axi_0:HBM[0]'
    if expected_mapping not in (linked / "connectivity.cfg").read_text().splitlines():
        raise ValueError("Expected HBM[0] mapping")
    timing_names = ("route-status.rpt", "implementation-timing.rpt", "implementation-drc.rpt")
    for name in timing_names:
        if not (timing / name).stat().st_size:
            raise ValueError("Missing routed check output: " + name)

    sources = {p.relative_to(out / "host").as_posix(): p
               for p in sorted((out / "host").rglob("*")) if p.is_file()}
    sources.update({
        name: SOURCES / name for name in ("compare_trace.py", "run_hacc.sh",
                                        "vcs-reference-results.jsonl", "vcs-reference-axi.jsonl")
    })
    sources.update({f"timing/{name}": timing / name for name in timing_names})
    sources.update({name: linked / name for name in ("xclbin-info.txt", "connectivity.cfg")})
    sources.update({"fpga_kernel.xclbin": xclbin, "baseline-prepared.json": out / "baseline-prepared.json"})
    manifest = json.loads((out / "trace-manifest.json").read_text())
    manifest.update(xclbin=image, xclbin_sha256=digest(xclbin),
                    baseline_xclbin_sha256=XCLBIN, baseline_xclbin=original,
                    timing_status="Routed setup, hold and connectivity checks completed on Ferrandi")
    manifest_path = out / "deployment-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    sources["manifest.json"] = manifest_path
    checksum = out / "SHA256SUMS"
    checksum.write_text("".join(f"{digest(path)}  {name}\n" for name, path in sorted(sources.items())))
    with tempfile.TemporaryDirectory(prefix=".trace-export-", dir=result.parent) as temp:
        candidate = Path(temp) / "bundle.tar.gz"
        with tarfile.open(candidate, "x:gz") as archive:
            for name, path in sorted(sources.items()):
                archive.add(path, arcname=name)
            archive.add(checksum, arcname=checksum.name)
        os.link(candidate, result)
    print("HACC_TRACE_BUNDLE:", result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    actions = parser.add_subparsers(dest="action", required=True)
    stage = actions.add_parser("prepare")
    stage.add_argument("--prepared", required=True, type=Path)
    stage.add_argument("--output", required=True, type=Path)
    stage.add_argument("--baseline", type=Path)
    export = actions.add_parser("bundle")
    for name in ("prepared", "linked", "timing", "baseline", "output"):
        export.add_argument("--" + name, required=True, type=Path)
    export.add_argument("--xclbinutil", required=True)
    args = parser.parse_args()
    repo = args.repo.resolve(strict=True)
    sys.path.insert(0, str(repo))
    output, prepared = args.output.resolve(), args.prepared.resolve(strict=True)
    if output == prepared or prepared in output.parents:
        parser.error("Output must be separate from the input prepared directory")
    if args.action == "prepare":
        if args.baseline and digest(args.baseline) != XCLBIN:
            raise ValueError("Baseline xclbin differs from the image measured on the U55C")
        prepare(repo, prepared, output)
    else:
        bundle(prepared, args.linked.resolve(strict=True), args.timing.resolve(strict=True),
               args.baseline.resolve(strict=True), output, args.xclbinutil)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"STOP: {error}")
