# SPDX-License-Identifier: Apache-2.0
"""Exercise concurrent benchmark subprocesses and their saved results."""
from contextlib import redirect_stderr, redirect_stdout
import csv
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools import execution

BAMBU_STUB = """
import os
from pathlib import Path
import sys
import time

work = Path.cwd()
temporary = Path(os.environ["TMPDIR"])
assert temporary == work / "tmp"
assert Path(os.environ["BAMBU_IPC_FILENAME"]) == work / "panda_ipc_mmap"
yaml = Path(os.environ["RAMULATOR2_CONFIG"])
assert yaml.parent.name == work.name
assert yaml.is_file()
start = time.time_ns()
(temporary / "ready").touch()
if os.environ["STUB_JOBS"] == "4" and work.name != "case_4":
    deadline = time.monotonic() + 10
    while len(list(work.parent.glob("case_[0-3]/tmp/ready"))) < 4:
        if time.monotonic() > deadline:
            sys.exit("Four workers did not start together")
        time.sleep(0.01)
(temporary / "interval").write_text(f"{start} {time.time_ns()}")
failed = work.name == os.environ["STUB_FAIL"]
Path("output").mkdir()
Path("output/bambu_results.xml").write_text(
    f'<results><timing><simulation return_value="{int(failed)}">'
    '<run>13</run></simulation></timing></results>'
)
print(f"Using Ramulator2 config from RAMULATOR2_CONFIG env var: {yaml}")
print("Ramulator2 successfully initialized for interface 0")
print("[MDPI-MEMORY] DRAM_TICKS=11,READS=1,COMPLETED=1,WRITES=1")
if failed:
    print(f"Simulated compiler diagnostic for {work.name}", file=sys.stderr)
"""


class BenchmarkExecutionTests(unittest.TestCase):
    def run_cases(self, jobs=None, fail=""):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        bambu = root / "bambu"
        bambu.write_text(f"#!{sys.executable}\n{BAMBU_STUB}")
        bambu.chmod(0o700)
        cases = [
            {"name": f"case_{index}", "members": ["smoke/vector_add_axi.c"], "flags": []}
            for index in range(5)
        ]
        stdout, stderr = io.StringIO(), io.StringIO()
        versions = {"bambu": {"exit_code": 0, "output": "Bambu 1.0"}}
        with patch.dict(os.environ):
            os.environ.pop("RAMULATOR_BATCH", None)
            os.environ.pop("J", None)
            if jobs is not None:
                os.environ["J"] = jobs
            env = dict(os.environ, STUB_JOBS=jobs or "1", STUB_FAIL=fail)
            preflight = ({"bambu": str(bambu)}, versions, env, None, [])
            with patch.object(execution, "RESULTS", root / ".runs"), \
                 patch.object(execution, "inspect_host", return_value=preflight), \
                 redirect_stdout(stdout), redirect_stderr(stderr):
                status = execution.main(
                    "smoke", "test", str(execution.ROOT / "smoke/configs/hbm2_32ch.yaml"),
                    False, board="xcu55c", keep_work=True, cases=cases, compare_results=False,
                )
        run = (root / ".runs/latest").resolve(strict=True)
        self.assertTrue((run / ".complete").exists())
        metadata = json.loads((run / "metadata.json").read_text())
        self.assertEqual(metadata["jobs"], int(jobs or "1"))
        with (run / "summary.csv").open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), len(cases))
        self.assertEqual({row["test_name"] for row in rows}, {case["name"] for case in cases})
        self.assertEqual(set(metadata["cases"]), {case["name"] for case in cases})
        self.assertTrue(all((run / row["log_file"]).is_file() for row in rows))
        intervals = [
            tuple(map(int, path.read_text().split()))
            for path in run.glob("work/*/tmp/interval")
        ]
        self.assertEqual(len(intervals), len(cases), stderr.getvalue())
        peak = max(sum(start <= point < end for start, end in intervals) for point, _ in intervals)
        return status, peak, {row["test_name"]: row["status"] for row in rows}, stderr.getvalue()

    def test_j_limits_parallel_cases_and_retains_failure_output(self):
        status, peak, results, errors = self.run_cases(jobs="4", fail="case_1")
        self.assertEqual(status, 1)
        self.assertEqual(peak, 4)
        self.assertEqual(results.pop("case_1"), "FAIL")
        self.assertEqual(set(results.values()), {"PASS"})
        self.assertIn("Simulated compiler diagnostic for case_1", errors)

    def test_unset_j_runs_cases_serially(self):
        status, peak, results, errors = self.run_cases()
        self.assertEqual(status, 0, errors)
        self.assertEqual(peak, 1)
        self.assertEqual(set(results.values()), {"PASS"})


if __name__ == "__main__":
    unittest.main()
