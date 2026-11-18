"""Export verified hardware build outputs and portable host sources."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import uuid

from fpga.catalog import registry
from fpga.hostgen import write as hostgen
from fpga.prepare import ROOT, digest


def xclbin_metadata(path, executable):
    result = subprocess.run([executable, '--info', '--input', str(path)],
                            capture_output=True, text=True, timeout=60, check=True)
    metadata = {}
    for key, label in (('platform_vbnv', 'Platform VBNV'), ('xclbin_uuid', 'UUID (xclbin)'),
                       ('interface_uuid', 'UUID (IINTF)')):
        match = re.search(r'^\s*' + re.escape(label) + r':[ \t]*(\S(?:[^\r\n]*\S)?)',
                          result.stdout, re.MULTILINE)
        if not match:
            raise ValueError(f'Missing {label} in xclbin metadata')
        metadata[key] = match[1]
    for key in ('xclbin_uuid', 'interface_uuid'):
        metadata[key] = str(uuid.UUID(metadata[key]))
    return metadata


def checked_digest(path, expected):
    actual = digest(path)
    if actual != expected:
        raise ValueError(f'Build fingerprint mismatch: {path}')
    return actual


def export_bundle(prepared, linked, archive, executable):
    manifest_path = prepared / 'manifest.json'
    info = json.loads(manifest_path.read_text())
    build = json.loads((linked / 'build.json').read_text())
    if build['target'] != 'hw':
        raise ValueError('The HACC bundle requires a completed hardware link')
    generation = info.get('generation')
    if info.get('reference_only') or not generation:
        raise ValueError('The HACC bundle requires hardware generation provenance')
    checked_digest(manifest_path, build['manifest_sha256'])

    if archive.exists() or archive.is_symlink():
        raise FileExistsError(f'Bundle already exists: {archive}')
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.hacc-bundle-', dir=archive.parent) as temporary:
        work = Path(temporary)
        payload = work / 'payload'
        payload.mkdir()
        xclbin = payload / 'fpga_kernel.xclbin'
        shutil.copyfile(linked / xclbin.name, xclbin)
        checked_digest(xclbin, build['xclbin_sha256'])
        metadata = xclbin_metadata(xclbin, executable)

        host_files = info.get('host_sha256')
        if host_files is None:
            # Older prepared directories used absolute includes. Export their
            # oracle only when its original source hashes are available.
            case = registry()[generation['case']]
            hostgen(case, info, payload, require_source_hashes=True)
        else:
            for name, expected in sorted(host_files.items()):
                relative = Path(name)
                if (not relative.parts or relative.is_absolute() or '..' in relative.parts
                        or not (name in ('case.hpp', 'host-flags.json')
                                or relative.parts[0] == 'oracle')):
                    raise ValueError(f'Invalid prepared host path: {name}')
                target = payload / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(prepared / relative, target)
                checked_digest(target, expected)

        shutil.copyfile(prepared / 'abi.hpp', payload / 'abi.hpp')
        if 'abi_sha256' in build:
            checked_digest(payload / 'abi.hpp', build['abi_sha256'])
        host_source = ROOT / 'fpga/host'
        for name in ('host.cpp', 'buffers.hpp', 'build.py'):
            shutil.copyfile(host_source / name, payload / name)
        host_rev = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True,
                                  capture_output=True)
        git_base = generation.get('git_base', {})
        platform = build['platform']
        manifest = {
            'format_version': 1,
            'case': generation['case'],
            'board': generation['board'],
            'part': platform['part'],
            'kernel_clock_mhz': platform['kernel_mhz'],
            'target': 'hw',
            'rtl_git_revision': git_base.get('output', '').strip() if git_base.get('exit_code') == 0 else None,
            'host_git_revision': host_rev.stdout.strip() if host_rev.returncode == 0 else None,
            'rtl_source_sha256': generation.get('source_sha256', {}),
            'prepared_rtl_sha256': info['rtl_sha256'],
            'prepared_manifest_sha256': build['manifest_sha256'],
            'xo_sha256': build.get('xo_sha256'),
            'platform_sha256': platform['platform_sha256'],
            'platform_receipt_shell': platform['shell_vbnv'],
            'tool_release': platform['tool_release'],
            'memory': build.get('memory'),
            'xrt_version_in_platform_receipt': platform['xrt_version'],
            'xclbin': metadata,
            'timing_status': build.get('implementation_timing'),
            'wall_seconds': build.get('wall_seconds', {}),
        }
        (payload / 'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
        files = sorted(p for p in payload.rglob('*') if p.is_file())
        sums = payload / 'SHA256SUMS'
        sums.write_text(''.join(f'{digest(path)}  {path.relative_to(payload).as_posix()}\n' for path in files))

        candidate = work / 'bundle.tar.gz'
        with tarfile.open(candidate, mode='w:gz') as output:
            for path in [*files, sums]:
                output.add(path, arcname=path.relative_to(payload).as_posix())
        os.link(candidate, archive)
    print(f'HACC bundle: {archive}')
