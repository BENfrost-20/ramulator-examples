import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

from fpga.catalog import registry
from fpga.deploy import export_bundle, xclbin_metadata
from fpga.hostgen import write as write_host_sources
from fpga.prepare import ROOT, digest, layout, make_abi_header, render_wrapper, verify
from fpga.run import link, memory_mapping
from fpga.tests.test_deployment import fixture


class HaccDeploymentTests(unittest.TestCase):
    def test_single_probe_preserves_wide_pointer_and_addresses(self):
        text, info = fixture()
        for port in ('data', 'm_axi_0_araddr', 'm_axi_0_awaddr'):
            before = '[31:0] ' + port
            self.assertIn(before, text)
            text = text.replace(before, '[63:0] ' + port)
        ports, masters = verify(text, info)
        wrapper = render_wrapper(info, ports, masters)
        self.assertIn(".data(64'h40000000)", wrapper)
        self.assertIn("raw_m_axi_0_araddr-64'h0000000040000000", wrapper)
        with self.assertRaisesRegex(ValueError, 'matching single-probe pointer and AXI widths'):
            verify(text.replace('[63:0] m_axi_0_awaddr', '[31:0] m_axi_0_awaddr'), info)

    def test_memory_mapping_keeps_aliased_ports_together(self):
        info = {'axi_ports': ['left', 'right'], 'base_register_banks': [0, 0]}
        resources = ['HBM[0]', 'HBM[1]']
        self.assertEqual(memory_mapping(info, resources, ['right=HBM[1]']),
                         {'left': 'HBM[1]', 'right': 'HBM[1]'})
        with self.assertRaisesRegex(ValueError, 'Aliased AXI'):
            memory_mapping(info, resources, ['left=HBM[0]', 'right=HBM[1]'])

    def test_xclbin_metadata_parses_alveo_interface_uuid(self):
        output = '''   UUID (xclbin):   e8ce0f39-268a-5d28-39ee-1116ca23dd2a
   UUID (IINTF):    b7ac1abe1e3e1cb686d5a81232452676
   Platform VBNV:   xilinx_u55c_gen3x16_xdma_3_202210_1
'''
        with patch('fpga.deploy.subprocess.run', return_value=SimpleNamespace(stdout=output)):
            metadata = xclbin_metadata(Path('fixture.xclbin'), 'xclbinutil')
        self.assertEqual(metadata['interface_uuid'], 'b7ac1abe-1e3e-1cb6-86d5-a81232452676')
        self.assertEqual(metadata['platform_vbnv'], 'xilinx_u55c_gen3x16_xdma_3_202210_1')

    def test_relink_and_export_reuse_xo_and_portable_oracle(self):
        with tempfile.TemporaryDirectory() as directory:
            prepared = Path(directory) / 'prepared'
            prepared.mkdir()
            case = registry()['memory_probe_single']
            info = layout(case)
            source = 'fpga/calibration/memory_probe.c'
            info.update(
                axi_ports=['m_axi_0'], base_register_banks=[0], rtl_sha256={'kernel.v': 'fixture'},
                generation={'case': case['name'], 'board': 'xcu55c', 'period_ns': 10,
                            'source_sha256': {source: digest(ROOT / source)}, 'wall_seconds': 2},
                wall_seconds=0.5,
            )
            info['host_sha256'] = write_host_sources(case, info, prepared)
            make_abi_header(prepared)
            manifest = prepared / 'manifest.json'
            manifest.write_text(json.dumps(info))
            xo = prepared / 'fpga_kernel.xo'
            with ZipFile(xo, 'w') as package:
                package.writestr(
                    'kernel.xml',
                    '<root><kernel name="fpga_kernel" hwControlProtocol="user_managed"><ports>'
                    '<port name="S_AXI_CONTROL" mode="slave"/><port name="m_axi_0" mode="master"/>'
                    '</ports><args><arg name="base0" port="m_axi_0"/></args></kernel></root>',
                )
            (prepared / 'package.json').write_text(json.dumps({
                'manifest_sha256': digest(manifest), 'xo_sha256': digest(xo), 'wall_seconds': 12,
            }))
            platform = dict(part='xcu55c-fsvh2892-2L-e', kernel_mhz=100,
                            platform_sha256='fixture', shell_vbnv='u55c', tool_release='2024.2',
                            xrt_version='2025.1')
            args = SimpleNamespace(target='hw', memory=['m_axi_0=HBM[1]'])
            linked = prepared / 'new-link'

            def fake_link(argv, cwd, log):
                self.assertEqual(digest(argv[-1]), digest(xo))
                self.assertEqual(argv[-1].parent, cwd)
                Path(argv[-2]).write_bytes(b'fixture hardware image')
                return 19

            with patch('fpga.run.run', side_effect=fake_link):
                link(prepared, linked, info, args, Path('fixture.xpfm'), platform,
                     ['HBM[0]', 'HBM[1]'])
            self.assertIn('sp=fpga_kernel_1.m_axi_0:HBM[1]',
                          (linked / 'connectivity.cfg').read_text())

            archive = Path(directory) / 'hacc.tar.gz'
            with patch('fpga.deploy.xclbin_metadata', return_value={'interface_uuid': 'fixture'}):
                export_bundle(prepared, linked, archive, 'xclbinutil')
                with self.assertRaises(FileExistsError):
                    export_bundle(prepared, linked, archive, 'xclbinutil')
            with tarfile.open(archive) as bundle:
                exported = json.load(bundle.extractfile('manifest.json'))
                self.assertEqual(exported['wall_seconds'],
                                 {'generate': 2, 'prepare': 0.5, 'package': 12, 'link': 19})
                self.assertEqual(exported['memory'], {'m_axi_0': 'HBM[1]'})
                self.assertIn('oracle/' + source, bundle.getnames())
                self.assertIn(b'#include "oracle/', bundle.extractfile('case.hpp').read())
                self.assertIn(b'fpga_kernel.xclbin', bundle.extractfile('SHA256SUMS').read())

            (linked / 'fpga_kernel.xclbin').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'fingerprint mismatch'):
                export_bundle(prepared, linked, Path(directory) / 'broken.tar.gz', 'xclbinutil')

    def test_transfer_reads_site_paths_with_spaces_and_apostrophes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mac = root / 'mac with spaces'
            hacc = root / "guest's shared home"
            mac.mkdir()
            (mac / 'probe.tar.gz').write_bytes(b'archive fixture')
            config = root / 'deploy.env'
            config.write_text(
                'FPGA_MAC_ARTIFACT_DIR="$FIXTURE/mac with spaces"\n'
                'FPGA_HACC_SSH="user@hacc"\n'
                'FPGA_HACC_ARTIFACT_DIR="$FIXTURE/guest\'s shared home"\n'
            )
            binaries = root / 'bin'
            binaries.mkdir()
            helpers = {
                'ssh': '#!/bin/bash\n[[ $1 == -- && $2 == user@hacc ]] || exit 3\nexec bash -c "$3"\n',
                'sha256sum': '#!/bin/bash\nexec shasum -a 256 "$@"\n',
            }
            for name, script in helpers.items():
                path = binaries / name
                path.write_text(script)
                path.chmod(0o700)
            env = dict(os.environ, FIXTURE=str(root), PATH=f'{binaries}:{os.environ["PATH"]}')
            command = ['bash', str(ROOT / 'fpga/transfer.sh'), '--config', str(config), 'push', 'probe.tar.gz']
            subprocess.run(command, env=env, capture_output=True, check=True)
            self.assertEqual((hacc / 'probe.tar.gz').read_bytes(), b'archive fixture')
            duplicate = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertNotEqual(duplicate.returncode, 0)
            self.assertIn('Bundle already exists', duplicate.stderr)
