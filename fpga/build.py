"""Build Bambu RTL -> XO -> hardware xclbin. No device or XRT host is required."""
import argparse
import datetime as dt
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from zipfile import ZipFile, BadZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fpga.catalog import select
from fpga.run import board

STAGES = ('generate', 'prepare', 'package', 'link')


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, data):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')
    temporary.replace(path)


def positive(value):
    n = int(value)
    if n < 1:
        raise argparse.ArgumentTypeError('Expected a positive integer')
    return n


def kernel_ports(xo):
    """Reject inconsistent descriptors before an expensive Vitis link."""
    with ZipFile(xo) as archive:
        names = [n for n in archive.namelist() if n.endswith('/kernel.xml') or n == 'kernel.xml']
        if len(names) != 1:
            raise ValueError('XO must contain exactly one kernel.xml')
        kernel = ET.fromstring(archive.read(names[0])).find('kernel')
    if kernel is None or kernel.get('name') != 'fpga_kernel':
        raise ValueError('XO must define the fpga_kernel kernel')
    if kernel.get('hwControlProtocol') != 'user_managed':
        raise ValueError('Expected a user-managed RTL kernel')
    ports = {p.get('name'): p for p in kernel.findall('ports/port')}
    if 'S_AXI_CONTROL' not in ports or ports['S_AXI_CONTROL'].get('mode') != 'slave':
        raise ValueError('XO is missing the S_AXI_CONTROL slave port')
    for arg in kernel.findall('args/arg'):
        if arg.get('port') not in ports:
            raise ValueError('kernel.xml argument references an unknown port: ' + str(arg.get('port')))
    masters = sorted(name for name, port in ports.items() if port.get('mode') == 'master')
    if not masters:
        raise ValueError('XO has no external-memory master')
    return masters


def connectivity(ports, resources, overrides, banked=False, require_explicit=False):
    chosen = {}
    for item in overrides or []:
        if '=' not in item:
            raise ValueError('--memory requires PORT=RESOURCE')
        port, resource = item.split('=', 1)
        if port in chosen:
            raise ValueError('Duplicate memory mapping for ' + port)
        if port not in ports or resource not in resources:
            raise ValueError('Memory mapping is outside the selected kernel/board profile: ' + item)
        chosen[port] = resource
    if require_explicit and set(chosen) != set(ports):
        raise ValueError('Imported multiport XO requires --memory for every master')
    if banked and len(ports) > len(resources):
        raise ValueError('Insufficient board resources; add a reviewed deployment profile')
    for i, port in enumerate(ports):
        chosen.setdefault(port, resources[i if banked else 0])
    if not banked and not require_explicit and len(set(chosen.values())) > 1:
        raise ValueError('Single-slab cases require all masters to use the same memory resource')
    return ('[connectivity]\nnk=fpga_kernel:1:fpga_kernel_1\n' +
            ''.join('sp=fpga_kernel_1.' + port + ':' + chosen[port] + '\n' for port in ports))


def prepared_info(path):
    path = Path(path)
    info = read(path / 'manifest.json')
    if info.get('reference_only') or 'generation' not in info:
        raise ValueError('Prepared RTL requires a board-correct generation receipt')
    for folder, key in (('rtl', 'rtl_sha256'), ('original', 'original_sha256')):
        actual = {p.name for p in (path / folder).iterdir()}
        if actual != set(info[key]):
            raise ValueError('Unlisted or missing prepared source files in ' + folder)
        for name, expected in info[key].items():
            if Path(name).name != name or sha(path / folder / name) != expected:
                raise ValueError('Prepared RTL fingerprint mismatch: ' + name)
    return info


def import_prepared(source, dest):
    info = prepared_info(source)
    dest.mkdir()
    for folder in ('rtl', 'original'):
        shutil.copytree(Path(source) / folder, dest / folder)
    for name in ('manifest.json', 'registers.tcl', 'adapter.diff'):
        p = Path(source) / name
        if p.exists():
            shutil.copyfile(p, dest / name)
    # Existing sources.tcl contains absolute paths; rebuild it for the new copy.
    files = sorted((dest / 'rtl').iterdir())
    if any(any(c in str(p) for c in '{}\n\r') for p in files):
        raise ValueError('Unsupported Tcl source path')
    (dest / 'sources.tcl').write_text('set rtl_files [list ' +
        ' '.join('{' + str(p) + '}' for p in files) + ']\n')
    return info


def run(argv, cwd, log):
    print('$ ' + shlex.join(list(map(str, argv))), flush=True)
    print('Log: ' + str(log), flush=True)
    with Path(log).open('w') as handle:
        handle.write('$ ' + shlex.join(list(map(str, argv))) + '\n')
        handle.flush()
        child = subprocess.Popen(list(map(str, argv)), cwd=cwd, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, errors='replace', start_new_session=True)
        try:
            for line in child.stdout:
                handle.write(line)
                handle.flush()
                print(line, end='', flush=True)
            result = child.wait()
        except BaseException:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
            raise
    if result:
        raise RuntimeError('Command exited ' + str(result) + '; see ' + str(log))


def executable(value):
    path = shutil.which(value)
    if not path:
        raise ValueError('Executable not found: ' + value)
    return str(Path(path).resolve())


def version(binary, flag, cwd):
    p = subprocess.run([binary, flag], cwd=cwd, capture_output=True,
                       text=True, errors='replace', timeout=30)
    output = p.stdout + p.stderr
    if p.returncode or not re.search(r'\b2024\.2\b', output):
        raise ValueError('Expected usable release 2024.2: ' + binary + '\n' + output[-2000:])
    return {'path': binary, 'launcher_sha256': sha(binary), 'version': output}


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--board')
    p.add_argument('--case', dest='case_name')
    p.add_argument('--period', type=float, help='Kernel period in ns')
    p.add_argument('--platform', help='Development .xpfm path')
    p.add_argument('--target', choices=('hw', 'hw_emu'))
    p.add_argument('--jobs', type=positive, help='Default concurrent Vivado runs')
    p.add_argument('--synth-jobs', type=positive)
    p.add_argument('--impl-jobs', type=positive)
    p.add_argument('--threads', type=positive, help='Threads per Vivado process, 1..8')
    cache = p.add_mutually_exclusive_group()
    cache.add_argument('--ip-cache', help='Shared Vivado IP synthesis cache directory')
    cache.add_argument('--no-ip-cache', action='store_true', help='Disable IP cache for this link')
    p.add_argument('--memory', action='append', help='PORT=RESOURCE, repeatable')
    fix = p.add_mutually_exclusive_group()
    fix.add_argument('--fix-adapter-log2', dest='fix', action='store_true')
    fix.add_argument('--no-fix-adapter-log2', dest='fix', action='store_false')
    p.set_defaults(fix=None)
    reuse = p.add_mutually_exclusive_group()
    reuse.add_argument('--generation', help='Reuse an existing generation.json')
    reuse.add_argument('--prepared', help='Copy and reuse an existing prepared integration')
    reuse.add_argument('--xo', help='Copy and link an existing XO')
    p.add_argument('--output', help='New build directory; defaults to a unique directory')
    p.add_argument('--resume', action='store_true', help='Reuse verified completed stages in --output')
    p.add_argument('--stop-after', choices=STAGES, default='link')
    p.add_argument('--dry-run', action='store_true', help='Print settings without running tools or writing files')
    return p


def settings(args):
    saved = {}
    if args.resume:
        if not args.output:
            raise ValueError('--resume requires --output')
        saved = read(Path(args.output).resolve() / 'build.json')['request']
        if not any((args.generation, args.prepared, args.xo)):
            for key in ('generation', 'prepared', 'xo'):
                setattr(args, key, saved.get(key))
    imported = None
    if args.generation:
        imported = read(args.generation)
    elif args.prepared:
        imported = prepared_info(args.prepared)['generation']
    board_name = args.board or saved.get('board') or (imported or {}).get('board') or os.getenv('FPGA_BOARD', 'xcu55c')
    period = args.period if args.period is not None else saved.get('period', (imported or {}).get('period_ns', os.getenv('FPGA_PERIOD_NS', '10')))
    period = float(period)
    if not math.isfinite(period) or period <= 0:
        raise ValueError('Period must be positive and finite')
    if imported and (board_name != imported['board'] or not math.isclose(period, imported['period_ns'])):
        raise ValueError('Requested board/period differs from the imported RTL receipt')
    case_name = None if args.xo else (args.case_name or saved.get('case') or (imported or {}).get('case') or os.getenv('FPGA_CASE', 'memory_probe_single'))
    if imported and case_name != imported['case']:
        raise ValueError('Requested case differs from the imported RTL receipt')
    case = None
    if case_name:
        cases = select([case_name])
        if len(cases) != 1 or cases[0]['name'] != case_name:
            raise ValueError('Specify one exact supported case name')
        case = cases[0]
    _, profile = board(board_name)
    if profile['tools'] != '2024.2':
        raise ValueError('This driver requires an AMD 2024.2 deployment profile')
    platform = args.platform or saved.get('platform') or os.getenv(profile['platform_env'])
    platform = str(Path(platform).expanduser().resolve()) if platform else None
    if STAGES.index(args.stop_after) >= 2 and (not platform or not Path(platform).is_file()):
        raise ValueError('Set --platform or ' + profile['platform_env'] + ' to a development .xpfm')
    jobs = args.jobs or positive(os.getenv('FPGA_JOBS', '8'))
    threads = args.threads or positive(os.getenv('FPGA_THREADS', '8'))
    if threads > 8:
        raise ValueError('Vivado 2024.2 general.maxThreads must be 1..8')
    fix = args.fix if args.fix is not None else saved.get('fix_log2', os.getenv('FPGA_FIX_ADAPTER_LOG2', '0') == '1')
    request = dict(board=board_name, case=case_name, period=period, platform=platform,
        target=args.target or saved.get('target') or 'hw', fix_log2=fix,
        memory=args.memory if args.memory is not None else saved.get('memory',
            [item for item in os.getenv('FPGA_MEMORY_MAPS', '').split(',') if item]),
        generation=str(Path(args.generation).resolve()) if args.generation else None,
        prepared=str(Path(args.prepared).resolve()) if args.prepared else None,
        xo=str(Path(args.xo).resolve()) if args.xo else None)
    if args.xo and STAGES.index(args.stop_after) < 2:
        raise ValueError('--xo starts after generation/preparation')
    if args.prepared and args.stop_after == 'generate':
        raise ValueError('--prepared starts after generation')
    cache = args.ip_cache or os.getenv('FPGA_IP_CACHE')
    return request, profile, case, dict(threads=threads,
        synth_jobs=args.synth_jobs or args.jobs or positive(os.getenv('FPGA_SYNTH_JOBS', str(jobs))),
        impl_jobs=args.impl_jobs or args.jobs or positive(os.getenv('FPGA_IMPL_JOBS', str(jobs))),
        ip_cache=str(Path(cache).expanduser().resolve()) if cache and not args.no_ip_cache else None,
        no_ip_cache=args.no_ip_cache)


def signature(request, case, profile):
    result = dict(request=request, deployment_profile=profile, code={})
    for name in ('fpga/build.py', 'fpga/run.py', 'fpga/catalog.py', 'fpga/prepare.py',
                 'fpga/hostgen.py', 'fpga/abi.json', 'fpga/tcl/package.tcl',
                 'fpga/toolchain.json', 'boards.json'):
        result['code'][name] = sha(ROOT / name)
    if request['platform'] and Path(request['platform']).is_file():
        result['platform_sha256'] = sha(request['platform'])
    for key in ('generation', 'xo'):
        if request[key]:
            result[key + '_sha256'] = sha(request[key])
    if request['prepared']:
        result['prepared_sha256'] = sha(Path(request['prepared']) / 'manifest.json')
    if case and not any(request[k] for k in ('generation', 'prepared', 'xo')):
        result['case_flags'] = case['flags']
        result['source_sha256'] = {name: sha(ROOT / name) for name in case['members']}
    return result


def build(args):
    request, profile, case, parallel = settings(args)
    if args.dry_run:
        print(json.dumps(dict(request=request, parallel=parallel, part=profile['part'],
            resources=profile['resources'], stop_after=args.stop_after,
            case_flags=case['flags'] if case else None), indent=2))
        return
    if args.resume:
        out = Path(args.output).resolve()
    elif args.output:
        out = Path(args.output).resolve()
        out.mkdir(parents=True, exist_ok=False)
    else:
        parent = Path(os.getenv('FPGA_BUILD_ROOT', str(ROOT / '.fpga/builds'))).resolve()
        parent.mkdir(parents=True, exist_ok=True)
        out = Path(tempfile.mkdtemp(prefix=request['board'] + '-' + (request['case'] or 'xo') + '-', dir=parent))
    print('Build directory: ' + str(out), flush=True)
    with (out / 'build.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Another driver is using this output directory')
        fingerprint = signature(request, case, profile)
        state_path = out / 'build.json'
        if args.resume:
            state = read(state_path)
            if state['signature'] != fingerprint:
                raise ValueError('Build inputs/code changed; use a new output directory and explicit artifact reuse')
            for data in state['completed'].values():
                for path, expected in data['files'].items():
                    if sha(path) != expected:
                        raise ValueError('Completed-stage artifact changed: ' + path)
        else:
            state = dict(format=1, request=request, signature=fingerprint, completed={}, attempts={},
                         created_utc=dt.datetime.now(dt.timezone.utc).isoformat(), tools={})
        state['parallel'] = parallel
        state['status'] = 'running'
        write(state_path, state)
        current = 'preflight'
        try:
            # Build-only checks: no installed device, deployment shell or host XRT required.
            vivado = os.getenv('FPGA_VIVADO', 'vivado')
            vpp = os.getenv('FPGA_VPP', 'v++')
            need_package = args.stop_after in ('package', 'link') and not request['xo'] and 'package' not in state['completed']
            if need_package:
                vivado = executable(vivado)
                state['tools']['vivado'] = version(vivado, '-version', out)
            if args.stop_after == 'link' and 'link' not in state['completed']:
                vpp = executable(vpp)
                state['tools']['v++'] = version(vpp, '--version', out)
            write(state_path, state)

            def complete(stage, artifact, files):
                state['completed'][stage] = dict(artifact=str(artifact), files={str(p): sha(p) for p in files})
                write(state_path, state)

            def attempt(stage):
                nonlocal current
                current = stage
                number = state['attempts'].get(stage, 0) + 1
                state['attempts'][stage] = number
                state['stage'] = stage
                write(state_path, state)
                return number

            if request['xo'] and 'package' not in state['completed']:
                number = attempt('package')
                kernel_ports(request['xo'])
                xo = out / ('imported-' + str(number) + '.xo')
                shutil.copyfile(request['xo'], xo)
                complete('package', xo, [xo])
            elif request['prepared'] and 'prepare' not in state['completed']:
                number = attempt('prepare')
                prepared = out / ('prepared-imported-' + str(number))
                import_prepared(request['prepared'], prepared)
                complete('prepare', prepared, [p for p in prepared.rglob('*') if p.is_file()])
            elif request['generation'] and 'generate' not in state['completed']:
                attempt('generate')
                gen = read(request['generation'])
                rtl = Path(gen['rtl_dir'])
                for name, expected in gen['rtl_sha256'].items():
                    if sha(rtl / name) != expected:
                        raise ValueError('Imported generation RTL changed: ' + name)
                complete('generate', Path(request['generation']), [Path(request['generation']),
                    *(rtl / name for name in gen['rtl_sha256'])])

            stop = STAGES.index(args.stop_after)
            if not any(s in state['completed'] for s in ('generate', 'prepare', 'package')):
                number = attempt('generate')
                dest = out / ('generated-' + str(number))
                env_period = os.environ.get('CLOCK_PERIOD_NS')
                os.environ['CLOCK_PERIOD_NS'] = str(request['period'])
                try:
                    run([sys.executable, ROOT / 'fpga/run.py', 'generate', '--board', request['board'],
                         '--tests', request['case'], '--output', dest], out, out / ('generate-' + str(number) + '.log'))
                finally:
                    if env_period is None:
                        os.environ.pop('CLOCK_PERIOD_NS', None)
                    else:
                        os.environ['CLOCK_PERIOD_NS'] = env_period
                gen_path = dest / request['case'] / 'generation.json'
                gen = read(gen_path)
                complete('generate', gen_path, [gen_path, *(Path(gen['rtl_dir']) / name for name in gen['rtl_sha256'])])
            if stop >= 1 and not any(s in state['completed'] for s in ('prepare', 'package')):
                number = attempt('prepare')
                gen_path = Path(state['completed']['generate']['artifact'])
                gen = read(gen_path)
                prepared = out / ('prepared-' + str(number))
                command = [sys.executable, ROOT / 'fpga/run.py', 'prepare', '--board', request['board'],
                    '--tests', request['case'], '--rtl-dir', gen['rtl_dir'], '--generation', gen_path, '--output', prepared]
                if request['fix_log2']:
                    command.append('--fix-adapter-log2')
                run(command, out, out / ('prepare-' + str(number) + '.log'))
                prepared_info(prepared)
                complete('prepare', prepared, [p for p in prepared.rglob('*') if p.is_file()])
            if stop >= 2 and 'package' not in state['completed']:
                number = attempt('package')
                prepared = Path(state['completed']['prepare']['artifact'])
                prepared_info(prepared)
                run([vivado, '-mode', 'batch', '-source', ROOT / 'fpga/tcl/package.tcl', '-tclargs',
                     prepared, profile['part'], request['period'], parallel['threads']], prepared,
                    out / ('package-' + str(number) + '.log'))
                xo = prepared / 'fpga_kernel.xo'
                kernel_ports(xo)
                complete('package', xo, [xo])
            if stop >= 3 and 'link' not in state['completed']:
                number = attempt('link')
                xo = Path(state['completed']['package']['artifact'])
                ports = kernel_ports(xo)
                dest = out / ('link-' + str(number))
                dest.mkdir()
                config = dest / 'connectivity.cfg'
                info = None
                if 'prepare' in state['completed']:
                    info = prepared_info(state['completed']['prepare']['artifact'])
                config.write_text(connectivity(ports, profile['resources'], request['memory'],
                    banked=bool(info and info['banks'] == 2), require_explicit=info is None and len(ports) > 1))
                xclbin = dest / 'fpga_kernel.xclbin'
                cache_args = []
                if parallel['no_ip_cache']:
                    cache_args = ['--no_ip_cache']
                elif parallel['ip_cache']:
                    Path(parallel['ip_cache']).mkdir(parents=True, exist_ok=True)
                    cache_args = ['--remote_ip_cache', parallel['ip_cache']]
                command = [vpp, '--link', '--target', request['target'], '--platform', request['platform'],
                    '--config', config, '--kernel_frequency', str(1000 / request['period']),
                    '--vivado.synth.jobs', str(parallel['synth_jobs']),
                    '--vivado.impl.jobs', str(parallel['impl_jobs']),
                    '--vivado.param', 'general.maxThreads=' + str(parallel['threads']),
                    '--save-temps', '--temp_dir', dest / 'temp', '--log_dir', dest / 'logs',
                    '--report_dir', dest / 'reports', *cache_args, '-o', xclbin, xo]
                run(command, dest, dest / 'link.log')
                if not xclbin.is_file() or not xclbin.stat().st_size:
                    raise ValueError('Link returned without a nonempty xclbin')
                complete('link', xclbin, [xclbin])
            state['status'] = 'complete_to_' + args.stop_after
            state['timing_status'] = 'Target implementation reports require review; OOC timing is not target timing approval'
            state['board_tested'] = False
            state['functional_validation'] = 'Not performed by this build-only driver'
            write(state_path, state)
            print('SUCCESS: ' + state['status'], flush=True)
            stage = next(s for s in reversed(STAGES[:stop + 1]) if s in state['completed'])
            print('Artifact: ' + state['completed'][stage]['artifact'], flush=True)
        except BaseException as exc:
            state.update(status='interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed',
                         stage=current, error=str(exc))
            write(state_path, state)
            raise


def main():
    args = parser().parse_args()
    try:
        build(args)
    except KeyboardInterrupt:
        print('ERROR: Build interrupted; completed stages are recorded for --resume.', file=sys.stderr)
        return 130
    except (ValueError, OSError, RuntimeError, KeyError, subprocess.SubprocessError,
            BadZipFile, ET.ParseError, argparse.ArgumentTypeError) as exc:
        print('ERROR: ' + str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
