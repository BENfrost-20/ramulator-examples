"""Compile the host application with the local XRT installation."""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import time


def main():
    sources = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared', type=Path, default=sources)
    parser.add_argument('--xrt-root', type=Path,
                        default=Path(os.environ.get('XILINX_XRT', '/opt/xilinx/xrt')))
    args = parser.parse_args()
    prepared = args.prepared.resolve()
    xrt = args.xrt_root.resolve()
    flags = json.loads((prepared / 'host-flags.json').read_text())
    started = time.monotonic()
    print('Compiling the XRT host...', flush=True)
    with tempfile.TemporaryDirectory(prefix='.host-', dir=prepared) as temporary:
        binary = Path(temporary) / 'host'
        cmd = [os.environ.get('CXX', 'g++'), '-std=c++17', '-O2',
               '-Wno-unknown-pragmas', '-pthread', '-I' + str(prepared),
               '-I' + str(sources), '-I' + str(xrt / 'include'), *flags,
               str(sources / 'host.cpp'), '-L' + str(xrt / 'lib'),
               '-Wl,-rpath,' + str(xrt / 'lib'), '-lxrt_coreutil', '-o', str(binary)]
        print('$ ' + shlex.join(cmd), flush=True)
        subprocess.run(cmd, cwd=prepared, check=True)
        duration = round(time.monotonic() - started, 3)
        receipt = Path(temporary) / 'host-build.json'
        receipt.write_text(json.dumps({
            'wall_seconds': duration,
            'compiler': cmd[0],
            'xrt_root': str(xrt),
        }, indent=2) + '\n')
        binary.replace(prepared / 'host')
        receipt.replace(prepared / receipt.name)
    print(f'Host ready: {prepared / "host"} ({duration:.3f} s)')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit('ERROR: ' + str(error))
