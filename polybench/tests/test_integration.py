# SPDX-License-Identifier: Apache-2.0
"""Check generated kernels against upstream execution and stage every recipe."""
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from polybench.cases import COMMON_FLAGS, cases
from polybench.prepare import BANNER, PATHS, SUITE, generate, prepare
from tools import execution


class PolyBenchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        prepare()

    def test_kernel_bodies_and_harness_statements_preserved(self):
        for name, path in PATHS.items():
            with self.subTest(kernel=name):
                original = (SUITE / 'sources' / path / (name + '.c')).read_text()
                generated = generate(name, SUITE / 'sources')
                top = 'kernel_' + name.replace('-', '_')
                match = re.search(r'^static\n(void ' + top + r'\([\s\S]*?^\})', original, re.M)
                kernel = generated[name + '.c'][len(BANNER):]
                self.assertTrue(kernel.endswith(match.group(1) + '\n'))
                harness = generated['tb_' + name + '.c'][len(BANNER):]
                self.assertEqual(harness, original[:match.start()] + original[match.end():])
                self.assertIn('#ifdef USE_AXI\n', kernel)
                self.assertNotIn('#pragma HLS', harness)
        self.assertEqual(prepare(check=True), 24)

    def test_generated_native_and_axi_outputs_match_original(self):
        utilities = SUITE / 'sources/utilities'
        with tempfile.TemporaryDirectory() as temporary:
            for name, path in PATHS.items():
                with self.subTest(kernel=name):
                    original = SUITE / 'sources' / path
                    generated = SUITE / 'build/adapters' / name
                    outputs = []
                    for variant in ('original', 'native', 'axi'):
                        exe = Path(temporary) / (name + '-' + variant)
                        directory = original if variant == 'original' else generated
                        command = ['gcc', '-std=gnu11', '-O1', '-DMINI_DATASET',
                                   '-DDATA_TYPE_IS_FLOAT', '-DPOLYBENCH_USE_RESTRICT',
                                   '-DPOLYBENCH_DUMP_ARRAYS', '-Wno-unknown-pragmas',
                                   '-I' + str(utilities), '-I' + str(directory)]
                        if variant == 'axi':
                            command.append('-DUSE_AXI')
                        command += [str(directory / (name + '.c'))]
                        if variant != 'original':
                            command.append(str(directory / ('tb_' + name + '.c')))
                        command += [str(utilities / 'polybench.c'), '-lm', '-o', str(exe)]
                        subprocess.run(command, check=True, capture_output=True)
                        result = subprocess.run([str(exe)], check=True, capture_output=True, timeout=20)
                        self.assertIn(b'==BEGIN DUMP_ARRAYS==', result.stderr)
                        outputs.append(result.stderr)
                    self.assertEqual(outputs[0], outputs[1])
                    self.assertEqual(outputs[0], outputs[2])

    def test_all_58_recipes_stage_original_inputs_and_generated_adapters(self):
        profile = dict(default_ramulator_yaml='smoke/configs/ddr4_1ch.yaml',
                       default_clock_ns=5.0, bambu_device='xcu250-2Lfigd2104')
        entries = list(cases())
        self.assertEqual(len(entries), 58)
        self.assertEqual(len({case['name'] for case in entries}), 58)
        with tempfile.TemporaryDirectory() as temporary, patch.object(execution, 'ROOT', ROOT):
            for case in entries:
                with self.subTest(case=case['name']):
                    snapshot = Path(temporary) / case['name']
                    snapshot.mkdir()
                    argv, yaml = execution.stage_case(dict(case, flags=COMMON_FLAGS + case['flags']),
                                                       snapshot, '', 'bambu', profile)
                    self.assertTrue(yaml.is_file())
                    for flag in argv[1:]:
                        if flag.startswith(('--generate-tb=', '--tb-arg=')):
                            self.assertTrue(Path(flag.split('=', 1)[1]).is_file(), flag)
                        elif flag.startswith('-I'):
                            self.assertTrue(Path(flag[2:]).is_dir(), flag)
                        elif flag.endswith('.c'):
                            self.assertTrue(Path(flag).is_file(), flag)


if __name__ == '__main__':
    unittest.main()
