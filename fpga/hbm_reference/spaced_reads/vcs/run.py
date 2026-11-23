import argparse
import csv
import json
from math import ceil
from pathlib import Path
import shutil
import subprocess
import time

import prepare_integration as vendor
import prepare_probe as single

src = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument("--vendor-run", type=Path,
                    default=vendor.ROOT / "integration-runs/run_20261117_191951_121861")
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--prepare-only", action="store_true")
args = parser.parse_args()
run = args.output.resolve()
export = args.vendor_run.resolve()
if run == vendor.ROOT or any(run == p or p in run.parents for p in
                             (export, vendor.ROOT / "bridge-project", vendor.ROOT / "example")):
    raise SystemExit("Use a separate output directory")
run.mkdir()
for name in ("fpga_kernel.sv","control.sv"):
    shutil.copyfile(src / name, run / name)
single.INPUT = bytes.fromhex("78563412")
prefix, marker, rest = single.testbench().partition("  // Test sequence appended after")
if not marker:
    raise SystemExit("Cannot locate validated testbench wiring")
common, marker, _ = ("  // Test sequence appended after" + rest).partition("  task automatic read_counter")
if not marker:
    raise SystemExit("Cannot locate validated AXI-Lite tasks")
tb = run / "tb_hbm_probe.sv"
tb.write_text(prefix + common + (src / "spaced_sequence.sv").read_text() + vendor.TB_LOADER + "endmodule\n")
(run / "simulate.do").write_text("run 12ms\nquit\n")
print("RESULTS:", run, flush=True)
if args.prepare_only:
    raise SystemExit(0)
start = time.monotonic()
metadata = vendor.compile_vendor(run, export)
work = run / "vcs"
vendor.command(["vlogan","-full64","-work","xil_defaultlib","-sverilog",
                "-l","kernel-compile.log", run/"control.sv", run/"fpga_kernel.sv", tb], work)
vendor.command(["vcs","-full64","-t","ps","-licqueue","-l","elaborate.log",
                "xil_defaultlib.tb_hbm_probe","xil_defaultlib.glbl","-o","spaced_simv"],work)
metadata["compile_wall_seconds"]=round(time.monotonic()-start,3)
metadata["rtl_sha256"]={n:vendor.sha(run/n) for n in ("fpga_kernel.sv","control.sv")}
metadata["testbench_sha256"]=vendor.sha(tb)
metadata["vendor_run"]=str(export)
(run/"build.json").write_text(json.dumps(metadata,indent=2)+"\n")
for count in (100,1000):
    path = run / f"vcs-{count}.csv"
    stdout = run / f"vcs-{count}.stdout.log"
    start = time.monotonic()
    with stdout.open("w") as f:
        subprocess.run([str(work/"spaced_simv"),"-ucli","-licqueue","-l",
                        str(run/f"vcs-{count}.log"),"-do",str(run/"simulate.do"),
                        f"+samples={count}",f"+csv={path}"],cwd=work,stdout=f,
                       stderr=subprocess.STDOUT,check=True)
    wall = time.monotonic()-start
    with path.open() as f:
        rows = list(csv.DictReader(f))
    if f"SPACED_READS_PASS samples={count}" not in stdout.read_text() or len(rows)!=count:
        raise SystemExit(f"VCS did not complete {count} samples; inspect {stdout}")
    print(f"PASS {count} reads, simulation wall time {wall:.2f} s",flush=True)

def quantiles(path):
    with path.open() as f:
        values = sorted(int(r["latency_cycles"]) for r in csv.DictReader(f))
    if len(values)!=1000:
        raise ValueError(f"Expected 1000 reads in {path}")
    return [values[ceil(len(values)*p)-1] for p in (.5,.90,.95,.99,1.0)]

hw = quantiles(src/"hardware.csv")
vcs = quantiles(run/"vcs-1000.csv")
shift = hw[0]-vcs[0]
lines = ["mode\tp50\tp90\tp95\tp99\tmax", *( "\t".join(map(str,[mode,*values]))
         for mode,values in (("hardware",hw),("vcs",vcs),
                             (f"vcs_shifted_{shift:+d}",[x+shift for x in vcs])))]
table = "\n".join(lines)+"\n"
(run/"comparison.tsv").write_text(table)
print(table,end="")
