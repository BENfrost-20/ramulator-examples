"""Read existing suite factories without launching their runner or copying flags."""
import ast
import fnmatch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUITES = ('smoke', 'micro', 'openmp', 'gapbs', 'polybench', 'machsuite')
SMALL = ('memory_probe_single', 'memory_probe_banked', 'smoke_axi_1ch',
         't01_clock', 't02_single_read', 't03_read_after_write', 't04_stream', 't06_byte_lanes')


def registry():
    result = {}
    for suite in SUITES:
        path = ROOT / suite / 'run.sh'
        source = path.read_text().split("<<'PYTHON'\n", 1)[1].rsplit('\nPYTHON', 1)[0]
        tree = ast.parse(source)
        # Retain only factory definitions, constants and recipe helper imports.
        nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.Assign))
                 and not (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'suite_dir' for t in node.targets))]
        imports = [node for node in tree.body if isinstance(node, ast.ImportFrom)
                   and node.module in ('tools.source_list', 'machsuite.cases', 'polybench.cases')]
        namespace = {}
        exec(compile(ast.Module(body=imports + nodes, type_ignores=[]), str(path), 'exec'), namespace)
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'run_suite']
        if len(calls) != 1:
            raise ValueError(f'{path}: expected one run_suite call')
        value = next(k.value for k in calls[0].keywords if k.arg == 'common_flags')
        common = eval(compile(ast.Expression(value), str(path), 'eval'), namespace)
        for case in namespace['cases']():
            case = dict(case, suite=suite, flags=[*common, *case['flags']])
            if case['name'] in result:
                raise ValueError('Duplicate case ' + case['name'])
            result[case['name']] = case
    for banks, mode in ((1, 'single'), (2, 'banked')):
        name = 'memory_probe_' + mode
        result[name] = dict(name=name, suite='calibration', banks=banks,
                            members=['fpga/calibration/memory_probe.c'], clock_period_ns=10,
                            flags=['--compiler=I386_CLANG13', '-m64', '-O2', '--top-fname=memory_probe',
                                   '--generate-interface=INFER', '--memory-allocation-policy=NO_BRAM',
                                   '--channels-type=MEM_ACC_11', '--channels-number=1', '--base-address=1073741824',
                                   *(['-DBANKED'] if banks == 2 else []), '@/fpga/calibration/memory_probe.c'])
    return result


def select(patterns=(), all_supported=False):
    cases = registry()
    names = list(SMALL) if all_supported else list(SMALL[:2])
    if patterns:
        names = []
        for pattern in (p for item in patterns for p in item.split(',')):
            matched = [n for n in cases if fnmatch.fnmatchcase(n, pattern)]
            if not matched:
                raise ValueError('No registered case matches ' + pattern)
            names.extend(n for n in matched if n not in names)
    unsupported = [n for n in names if n not in SMALL]
    if unsupported:
        raise ValueError('Deployment not yet implemented (no substitution): ' + ', '.join(unsupported))
    return [cases[n] for n in names]
