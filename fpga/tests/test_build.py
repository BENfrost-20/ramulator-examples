"""Tool-independent regressions. Fake tools never establish vendor validation."""
import json
import fcntl
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from fpga.build import connectivity, kernel_ports
from fpga.prepare import bounded_log2, verify, render_wrapper
from fpga.tests.test_deployment import fixture

XML = '''<root><kernel name="fpga_kernel" hwControlProtocol="user_managed">
<ports><port name="S_AXI_CONTROL" mode="slave"/><port name="m_axi_0" mode="master"/></ports>
<args><arg name="n" port="S_AXI_CONTROL"/><arg name="base0" port="m_axi_0"/></args>
</kernel></root>'''

LIB = '''module MinimalAXI4Adapter();
  `ifndef _SIM_HAVE_CLOG2
  function integer log2;
    input integer value;
    integer temp_value;
    begin
      temp_value = value - 1;
      for(log2 = 0; temp_value > 0; log2 = log2 + 1)
        temp_value = temp_value >> 1;
    end
  endfunction
  `endif
  localparam BYTES_PER_WORD = BITSIZE_m_axi_rdata / 8;
  localparam BYTE_OFFSET_BITS = BYTES_PER_WORD > 1 ? log2(BYTES_PER_WORD) : 1;
  wire [2:0] size_next;
  generate
    assign size_next = log2(Mout_data_ram_size >> 3);
  endgenerate
endmodule
'''


def xo(path, xml=XML):
    with ZipFile(path, 'w') as archive:
        archive.writestr('fpga_kernel/kernel.xml', xml)


class BuildContracts(unittest.TestCase):
    def test_xo_unknown_port_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'kernel.xo'
            xo(p, XML.replace('name="n" port="S_AXI_CONTROL"', 'name="n" port="s_axi_control"'))
            with self.assertRaisesRegex(ValueError, 'unknown port'):
                kernel_ports(p)
            xo(p)
            self.assertEqual(kernel_ports(p), ['m_axi_0'])

    def test_memory_mapping_checks_profile_and_ports(self):
        text = connectivity(['m_axi_0'], ['HBM[0]', 'HBM[1]'], ['m_axi_0=HBM[1]'])
        self.assertIn('sp=fpga_kernel_1.m_axi_0:HBM[1]', text)
        for override in ('m_axi_1=HBM[0]', 'm_axi_0=DDR[0]', 'm_axi_0'):
            with self.assertRaises(ValueError):
                connectivity(['m_axi_0'], ['HBM[0]'], [override])

    def test_shared_slab_banked_and_unknown_xo_mapping(self):
        ports = ['m_axi_0', 'm_axi_1', 'm_axi_2']
        shared = connectivity(ports, ['HBM[0]', 'HBM[1]'], [])
        self.assertEqual(shared.count(':HBM[0]'), 3)
        banked = connectivity(ports[:2], ['HBM[0]', 'HBM[1]'], [], banked=True)
        self.assertIn('m_axi_1:HBM[1]', banked)
        with self.assertRaisesRegex(ValueError, 'every master'):
            connectivity(ports[:2], ['HBM[0]', 'HBM[1]'], [], require_explicit=True)
        with self.assertRaisesRegex(ValueError, 'Single-slab'):
            connectivity(ports[:2], ['HBM[0]', 'HBM[1]'], ['m_axi_1=HBM[1]'])

    def test_log2_fix_preserves_new_adapter_constants(self):
        fixed = bounded_log2(LIB)
        before = LIB.split('  `endif', 1)[1]
        after = fixed.split('  `endif', 1)[1]
        self.assertEqual(before, after)
        self.assertIn('for(j = 0; j < 32;', fixed)
        with self.assertRaises(ValueError):
            bounded_log2(LIB.replace('temp_value = value - 1;', 'temp_value = value;'))

    def test_wide_probe_retains_full_addresses(self):
        text, info = fixture()
        text = text.replace('input [31:0] data;', 'input [63:0] data;')
        for channel in ('araddr', 'awaddr'):
            text = text.replace('output [31:0] m_axi_0_' + channel,
                                'output [63:0] m_axi_0_' + channel)
        ports, prefixes = verify(text, info)
        wrapper = render_wrapper(info, ports, prefixes)
        self.assertIn(".data(64'h40000000)", wrapper)
        self.assertNotIn("{0{", wrapper)
        with self.assertRaises(ValueError):
            verify(text.replace('output [63:0] m_axi_0_awaddr;', 'output [31:0] m_axi_0_awaddr;'), info)


class DriverFlow(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.platform = self.root / 'test.xpfm'
        self.platform.write_text('Tool-independent platform fixture, not a vendor platform')
        self.input_xo = self.root / 'input.xo'
        xo(self.input_xo)
        self.tools = self.root / 'tools'
        self.tools.mkdir()
        self.vpp = self.tools / 'vpp'
        self.vpp.write_text('''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
if '--version' in sys.argv:
    print('v++ 2024.2 test stub'); sys.exit(0)
Path('stub-argv.json').write_text(json.dumps(sys.argv[1:]))
if os.getenv('FPGA_TEST_LINK_FAIL'):
    print('Intentional link failure'); sys.exit(7)
Path(sys.argv[sys.argv.index('-o')+1]).write_bytes(b'Test artifact: not an xclbin')
print('Test stub completed; no vendor implementation performed')
''')
        self.vpp.chmod(0o755)
        self.env = dict(os.environ, FPGA_VPP=str(self.vpp), FPGA_JOBS='4', FPGA_THREADS='8',
                        PYTHONDONTWRITEBYTECODE='1')
        for key in ('FPGA_PROFILE', 'FPGA_TEST_LINK_FAIL', 'FPGA_IP_CACHE',
                    'FPGA_SYNTH_JOBS', 'FPGA_IMPL_JOBS', 'FPGA_MEMORY_MAPS'):
            self.env.pop(key, None)
        self.output = self.root / 'build'

    def cli(self, *args, env=None):
        return subprocess.run([sys.executable, str(ROOT / 'fpga/build.py'), '--platform', str(self.platform),
            '--output', str(self.output), *args], env=env or self.env,
            cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    def test_link_reuse_parallel_options_and_safe_resume(self):
        self.env.update(FPGA_SYNTH_JOBS='2', FPGA_IMPL_JOBS='1')
        cache = self.root / 'shared-cache'
        first = self.cli('--xo', str(self.input_xo), '--jobs', '3', '--threads', '6', '--ip-cache', str(cache))
        self.assertEqual(first.returncode, 0, first.stdout)
        state = json.loads((self.output / 'build.json').read_text())
        argv = json.loads((self.output / 'link-1/stub-argv.json').read_text())
        for flag, value in (('--vivado.synth.jobs', '3'), ('--vivado.impl.jobs', '3'),
                            ('--vivado.param', 'general.maxThreads=6'), ('--remote_ip_cache', str(cache.resolve()))):
            self.assertEqual(argv[argv.index(flag)+1], value)
        self.assertTrue(cache.is_dir())
        self.assertFalse(state['board_tested'])
        again = self.cli('--resume')
        self.assertEqual(again.returncode, 0, again.stdout)
        self.assertEqual(json.loads((self.output/'build.json').read_text())['attempts']['link'], 1)
        Path(state['completed']['package']['artifact']).write_bytes(b'changed')
        rejected = self.cli('--resume')
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn('artifact changed', rejected.stdout)

    def test_failed_link_retries_in_new_directory(self):
        failed = self.cli('--xo', str(self.input_xo), env=dict(self.env, FPGA_TEST_LINK_FAIL='1'))
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn('Intentional link failure', (self.output / 'link-1/link.log').read_text())
        resumed = self.cli('--resume', '--synth-jobs', '2', '--impl-jobs', '1')
        self.assertEqual(resumed.returncode, 0, resumed.stdout)
        state = json.loads((self.output/'build.json').read_text())
        self.assertEqual(state['attempts']['link'], 2)
        self.assertTrue((self.output/'link-2/fpga_kernel.xclbin').is_file())
        self.assertTrue((self.output/'link-1/link.log').is_file())

    def test_no_overwrite_and_dry_run(self):
        dry = self.cli('--xo', str(self.input_xo), '--dry-run')
        self.assertEqual(dry.returncode, 0, dry.stdout)
        self.assertFalse(self.output.exists())
        self.output.mkdir()
        sentinel = self.output / 'keep.txt'
        sentinel.write_text('Keep active or existing builds intact')
        denied = self.cli('--xo', str(self.input_xo))
        self.assertNotEqual(denied.returncode, 0)
        self.assertEqual(sentinel.read_text(), 'Keep active or existing builds intact')

    def test_resume_refuses_an_active_output_lock(self):
        initial = self.cli('--xo', str(self.input_xo))
        self.assertEqual(initial.returncode, 0, initial.stdout)
        before = (self.output/'build.json').read_bytes()
        with (self.output/'build.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            denied = self.cli('--resume')
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn('Another driver', denied.stdout)
        self.assertEqual((self.output/'build.json').read_bytes(), before)

    def test_thread_limit_and_changed_platform(self):
        denied = self.cli('--xo', str(self.input_xo), '--threads', '16')
        self.assertNotEqual(denied.returncode, 0)
        self.assertFalse(self.output.exists())
        initial = self.cli('--xo', str(self.input_xo))
        self.assertEqual(initial.returncode, 0, initial.stdout)
        self.platform.write_text('Changed platform')
        denied = self.cli('--resume')
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn('inputs/code changed', denied.stdout)

    def fake_compilers(self):
        text, _ = fixture()
        text = '// I386_CLANG13 test fixture; not a computational DUT\n' + text
        text = text.replace('input [31:0] data;', 'input [63:0] data;')
        for channel in ('araddr', 'awaddr'):
            text = text.replace('output [31:0] m_axi_0_' + channel,
                                'output [63:0] m_axi_0_' + channel)
        install = self.root / 'test-install'
        (install / 'bin').mkdir(parents=True)
        bambu = install / 'bin/bambu'
        revision = json.loads((ROOT / 'fpga/toolchain.json').read_text())['bambu']['revision']
        bambu.write_text('''#!/usr/bin/env python3
import sys
from pathlib import Path
if '--version' in sys.argv:
    print('Version: PandA test fixture - Revision ''' + revision + '''-HEAD'); sys.exit(0)
dest=Path(next(arg.split('=',1)[1] for arg in sys.argv if arg.startswith('--output-directory=')))
dest.mkdir(parents=True)
(dest/'memory_probe.v').write_text(''' + repr(text) + ''')
(dest/'panda_libtech.v').write_text(''' + repr(LIB) + ''')
''')
        bambu.chmod(0o755)
        from fpga.build import sha
        receipt = self.root / 'receipt.json'
        receipt.write_text(json.dumps(dict(repository='ferrandi/PandA-bambu', source_revision=revision,
            binary_sha256=sha(bambu), build_evidence='Explicit tool-independent test fixture',
            artifacts={'bin/bambu': sha(bambu)})))
        vivado = self.tools / 'vivado'
        vivado.write_text('''#!/usr/bin/env python3
import json,sys
from pathlib import Path
from zipfile import ZipFile
if '-version' in sys.argv:
    print('Vivado 2024.2 test stub'); sys.exit(0)
prepared=Path(sys.argv[sys.argv.index('-tclargs')+1])
(prepared/'stub-package-argv.json').write_text(json.dumps(sys.argv[1:]))
with ZipFile(prepared/'fpga_kernel.xo','w') as z:
    z.writestr('fpga_kernel/kernel.xml', ''' + repr(XML) + ''')
print('Package test stub completed; no RTL synthesis performed')
''')
        vivado.chmod(0o755)
        return dict(self.env, FPGA_BAMBU=str(bambu), BAMBU_HLS=str(install),
                    FPGA_TOOLCHAIN_RECEIPT=str(receipt), FPGA_VIVADO=str(vivado))

    def test_full_orchestration_and_resume_after_package(self):
        env = self.fake_compilers()
        first = self.cli('--case', 'memory_probe_single', '--fix-adapter-log2',
                         '--stop-after', 'package', env=env)
        self.assertEqual(first.returncode, 0, first.stdout)
        state = json.loads((self.output / 'build.json').read_text())
        self.assertEqual(set(state['completed']), {'generate', 'prepare', 'package'})
        prepared = Path(state['completed']['prepare']['artifact'])
        self.assertIn('for(j = 0; j < 32;', (prepared / 'rtl/panda_libtech.v').read_text())
        self.assertIn('BYTE_OFFSET_BITS', (prepared / 'rtl/panda_libtech.v').read_text())
        resumed = self.cli('--resume', env=env)
        self.assertEqual(resumed.returncode, 0, resumed.stdout)
        state = json.loads((self.output / 'build.json').read_text())
        self.assertEqual(state['attempts'], dict(generate=1, prepare=1, package=1, link=1))

    def test_import_prepared_copies_only_inputs_and_rewrites_paths(self):
        env = self.fake_compilers()
        first = self.cli('--case', 'memory_probe_single', '--fix-adapter-log2',
                         '--stop-after', 'prepare', env=env)
        self.assertEqual(first.returncode, 0, first.stdout)
        state = json.loads((self.output/'build.json').read_text())
        prepared = Path(state['completed']['prepare']['artifact'])
        (prepared/'old-hardware-build').mkdir()
        (prepared/'old-hardware-build/keep.log').write_text('Do not copy old build trees')
        other = self.root / 'imported-build'
        command = [sys.executable, str(ROOT/'fpga/build.py'), '--prepared', str(prepared),
                   '--platform', str(self.platform), '--output', str(other)]
        result = subprocess.run(command, env=env, cwd=ROOT, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertEqual(result.returncode, 0, result.stdout)
        imported_state = json.loads((other/'build.json').read_text())
        copied = Path(imported_state['completed']['prepare']['artifact'])
        self.assertFalse((copied/'old-hardware-build').exists())
        sources = (copied/'sources.tcl').read_text()
        self.assertIn(str(copied/'rtl/fpga_kernel.sv'), sources)
        self.assertNotIn(str(prepared/'rtl/fpga_kernel.sv'), sources)


if __name__ == '__main__':
    unittest.main()
