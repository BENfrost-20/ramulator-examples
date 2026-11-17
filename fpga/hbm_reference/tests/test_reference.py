"""Source-only regression checks; no vendor tools or simulation are invoked."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("hbm_reference_source", SOURCE / "prepare_integration.py")
reference = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reference)


class ExportDataTests(unittest.TestCase):
    def test_reports_do_not_conflict_but_runtime_data_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scripts = []
            for design in ("hbm", "bridge"):
                folder = root / design
                folder.mkdir()
                script = folder / "compile.sh"
                script.write_text("")
                scripts.append(script)
                (folder / "README.txt").write_text(design)
                (folder / "file_info.txt").write_text(design)
                (folder / "shared.mem").write_text("a5")
            (root / "hbm/axi_tg.txt").write_text("runtime")
            plan, metadata = reference.plan_export_data(scripts)
            self.assertEqual({str(item[1]) for item in plan}, {"shared.mem", "axi_tg.txt"})
            self.assertEqual(len(metadata), 4)
            (root / "bridge/shared.mem").write_text("different")
            with self.assertRaisesRegex(ValueError, "shared.mem"):
                reference.plan_export_data(scripts)
            (root / "bridge/shared.mem").write_text("a5")
            (root / "bridge/axi_tg.txt").write_text("different")
            with self.assertRaisesRegex(ValueError, "axi_tg.txt"):
                reference.plan_export_data(scripts)


class ExportValidationTests(unittest.TestCase):
    def test_vivado_error_is_fatal_even_if_a_success_message_follows(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            (run / "export.log").write_text(
                "ERROR: [exportsim-Tcl-70] A simulation top was not set.\n"
                "INTEGRATION_EXPORT_OK: stale unconditional message\n"
            )
            with self.assertRaisesRegex(ValueError, "simulation top"):
                reference.verify_export(run)

    def test_generic_top_script_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            folder = run / "export-bridge/vcs"
            folder.mkdir(parents=True)
            (folder / "top.sh").write_text("smoke_bridge_wrapper.v")
            with self.assertRaisesRegex(ValueError, "expected smoke_bridge_wrapper.sh"):
                reference.locate_script(run, "export-bridge")


class InPlaceTests(unittest.TestCase):
    def fixture(self, run):
        (run / "vcs").mkdir()
        (run / "vcs/synopsys_sim.setup").write_text("existing mapping")
        manifest = {
            "n": 8,
            "addresses": {"vec_" + letter: hex(addr) for letter, addr in zip("abc", reference.BASES)},
            "vectors": {"vec_a": list(range(1, 9)), "vec_b": list(range(10, 81, 10)), "vec_c": [0] * 8},
        }
        (run / "manifest.json").write_text(json.dumps(manifest))
        (run / "build.json").write_text("{}")
        (run / "tb_hbm_bambu.sv").write_text("previous source")

    def test_rebuild_reuses_mapping_without_creating_another_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            self.fixture(run)
            before = {path.relative_to(run) for path in run.rglob("*") if path.is_dir()}
            with patch.object(reference, "verify_export"), patch.object(reference, "compile_testbench") as compiler:
                reference.rebuild_testbench(run)
            compiler.assert_called_once_with(run)
            after = {path.relative_to(run) for path in run.rglob("*") if path.is_dir()}
            self.assertEqual(before, after)
            self.assertEqual((run / "vcs/synopsys_sim.setup").read_text(), "existing mapping")
            build = json.loads((run / "build.json").read_text())
            self.assertTrue(build["testbench_rebuild_complete"])
            self.assertEqual(build["tb_sha256"], reference.sha(run / "tb_hbm_bambu.sv"))

    def test_failed_rebuild_blocks_the_old_binary(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            self.fixture(run)
            (run / "results.json").write_text('{"functional_pass":true}')
            with patch.object(reference, "verify_export"), patch.object(
                reference, "compile_testbench", side_effect=OSError("compiler failed")
            ):
                with self.assertRaisesRegex(OSError, "compiler failed"):
                    reference.rebuild_testbench(run)
            self.assertFalse((run / "results.json").exists())
            with self.assertRaisesRegex(ValueError, "incomplete"):
                reference.simulate_run(run)

    def test_a_new_failure_cannot_reuse_an_old_pass_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            self.fixture(run)
            (run / "build.json").write_text(json.dumps({
                "testbench_rebuild_complete": True,
                "tb_sha256": reference.sha(run / "tb_hbm_bambu.sv"),
            }))
            (run / "vcs/simulate.log").write_text("HBM_BAMBU_TEST_PASSED\n")
            def failed_simulator(args, cwd):
                self.assertEqual((cwd / "simulate.log").read_text(), "")
                (cwd / "simulate.log").write_text("new failed simulation")
            with patch.object(reference, "command", side_effect=failed_simulator):
                with self.assertRaisesRegex(ValueError, "PASS marker"):
                    reference.simulate_run(run)


if __name__ == "__main__":
    unittest.main()
