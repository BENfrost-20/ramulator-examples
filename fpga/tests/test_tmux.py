"""Exercise tmux launcher wiring with a stub, without server/vendor execution."""
import errno
import json
import os
from pathlib import Path
import pty
import select
import subprocess
import time
import unittest

import fpga.tests.test_build as fixtures


class TmuxLauncherTests(unittest.TestCase):
    def setUp(self):
        self.flow = fixtures.DriverFlow()
        self.flow.setUp()
        self.addCleanup(self.flow.doCleanups)
        self.root = self.flow.root
        self.config = self.root / "site config's settings.sh"
        self.config.write_text('''export FPGA_BAMBU_SETTINGS=''
export FPGA_VIVADO_SETTINGS=''
export FPGA_VITIS_SETTINGS=''
export FPGA_TMUX_MODE=auto
''')
        self.calls = self.root / 'tmux-calls.jsonl'
        self.tmux = self.flow.tools / 'tmux'
        self.tmux.write_text('''#!/usr/bin/env python3
import json,os,subprocess,sys
from pathlib import Path
with Path(os.environ['FPGA_TEST_TMUX_CALLS']).open('a') as f:
    f.write(json.dumps(sys.argv[1:])+'\\n')
cmd=sys.argv[1]
if cmd=='has-session':
    sys.exit(0 if os.getenv('FPGA_TEST_TMUX_EXISTS') else 1)
if cmd=='display-message':
    print('@42'); sys.exit(0)
if cmd in ('set-option','attach-session'):
    sys.exit(0)
if cmd=='new-session':
    # Simulate a long-lived tmux server with stale/missing client settings.
    child=dict(os.environ,TMUX='test-socket,123,0',TMUX_PANE='%1')
    for name in list(child):
        if name.startswith('FPGA_'):
            del child[name]
    cwd=sys.argv[sys.argv.index('-c')+1]
    result=subprocess.run(sys.argv[-1],shell=True,cwd=cwd,env=child,
                          text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    print(result.stdout,end='')
    # Session startup success is distinct from the pane command exit status.
    sys.exit(0)
sys.exit(2)
''')
        self.tmux.chmod(0o755)
        self.env = dict(self.flow.env, FPGA_TMUX_BIN=str(self.tmux),
            FPGA_TMUX_ROOT=str(self.root / "session files' $(printf literal)"),
            FPGA_TEST_TMUX_CALLS=str(self.calls))
        for key in ('TMUX', 'TMUX_PANE', 'FPGA_TMUX_SESSION', 'FPGA_TMUX_MODE'):
            self.env.pop(key, None)

    def command(self, *flags):
        return ['bash', str(fixtures.ROOT / 'fpga/build.sh'), '--env', str(self.config),
                '--xo', str(self.flow.input_xo), '--platform', str(self.flow.platform),
                '--output', str(self.flow.output), *flags]

    def invoke(self, *flags, env=None):
        return subprocess.run(self.command(*flags), cwd=fixtures.ROOT,
            env=env or self.env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    def recorded(self):
        return [json.loads(line) for line in self.calls.read_text().splitlines()] if self.calls.exists() else []

    def test_automatic_noninteractive_launch_preserves_environment_and_arguments(self):
        result = self.invoke('--session', 'probe-auto', '--synth-jobs', '3')
        self.assertEqual(result.returncode, 0, result.stdout)
        calls = self.recorded()
        self.assertEqual(sum(c[0]=='new-session' for c in calls), 1)
        self.assertFalse(any(c[0]=='attach-session' for c in calls))
        self.assertIn(['set-option', '-w', '-t', '@42', 'remain-on-exit', 'on'], calls)
        folder = next(Path(self.env['FPGA_TMUX_ROOT']).glob('probe-auto-*'))
        self.assertEqual((folder/'exit-code').read_text().strip(), '0')
        self.assertEqual((folder/'launch.sh').stat().st_mode & 0o077, 0)
        state = json.loads((self.flow.output/'build.json').read_text())
        self.assertEqual(state['parallel']['synth_jobs'], 3)

    def test_detached_failure_records_real_exit_status(self):
        result = self.invoke('--detach', '--session', 'probe-failed',
            env=dict(self.env, FPGA_TEST_LINK_FAIL='1'))
        self.assertEqual(result.returncode, 0, result.stdout)
        folder = next(Path(self.env['FPGA_TMUX_ROOT']).glob('probe-failed-*'))
        self.assertEqual((folder/'exit-code').read_text().strip(), '2')
        self.assertEqual(json.loads((self.flow.output/'build.json').read_text())['status'], 'failed')

    def test_existing_session_is_not_reused(self):
        result = self.invoke('--session', 'existing', env=dict(self.env, FPGA_TEST_TMUX_EXISTS='1'))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Session already exists', result.stdout)
        self.assertFalse(any(c[0]=='new-session' for c in self.recorded()))
        self.assertFalse(self.flow.output.exists())

    def test_direct_and_existing_tmux_avoid_nesting(self):
        for flag, env in (('--no-tmux', self.env), (None, dict(self.env, TMUX='existing,1,0'))):
            with self.subTest(flag=flag):
                if self.flow.output.exists():
                    import shutil
                    shutil.rmtree(self.flow.output)
                result = self.invoke(*([flag] if flag else []), env=env)
                self.assertEqual(result.returncode, 0, result.stdout)
                self.assertEqual(self.recorded(), [])

    def test_explicit_detach_inside_tmux_creates_a_dedicated_session(self):
        result = self.invoke('--detach', '--session', 'dedicated',
                             env=dict(self.env, TMUX='existing,1,0'))
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(sum(c[0]=='new-session' for c in self.recorded()), 1)
        self.assertFalse(any(c[0]=='attach-session' for c in self.recorded()))

    def test_session_name_can_be_reused_after_closing_without_deleting_history(self):
        first = self.invoke('--detach', '--session', 'repeatable')
        self.assertEqual(first.returncode, 0, first.stdout)
        second = self.invoke('--detach', '--session', 'repeatable', '--resume')
        self.assertEqual(second.returncode, 0, second.stdout)
        folders = list(Path(self.env['FPGA_TMUX_ROOT']).glob('repeatable-*'))
        self.assertEqual(len(folders), 2)
        self.assertTrue(all((folder/'exit-code').read_text().strip()=='0' for folder in folders))

    def test_dry_run_and_help_do_not_launch_tmux(self):
        dry = self.invoke('--dry-run', '--detach')
        self.assertEqual(dry.returncode, 0, dry.stdout)
        json.loads(dry.stdout)
        help_result = self.invoke('--help')
        self.assertEqual(help_result.returncode, 0, help_result.stdout)
        self.assertIn('--no-tmux', help_result.stdout)
        self.assertEqual(self.recorded(), [])
        self.assertFalse(self.flow.output.exists())

    def test_invalid_names_and_missing_tmux_fail_without_building(self):
        invalid = self.invoke('--session', 'invalid:name')
        self.assertNotEqual(invalid.returncode, 0)
        missing = self.invoke(env=dict(self.env, FPGA_TMUX_BIN='/missing/tmux'))
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn('tmux not found', missing.stdout)
        self.assertFalse(self.flow.output.exists())

    def test_interactive_launch_attaches(self):
        try:
            master, slave = pty.openpty()
        except OSError as exc:
            self.skipTest('Local PTY unavailable: ' + str(exc))
        process = subprocess.Popen(self.command('--session', 'probe-interactive'),
            cwd=fixtures.ROOT, env=self.env, stdin=slave, stdout=slave, stderr=slave)
        os.close(slave)
        output = bytearray()
        deadline = time.monotonic() + 15
        try:
            while time.monotonic() < deadline:
                ready, _, _ = select.select([master], [], [], 0.1)
                if ready:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError as exc:
                        if exc.errno == errno.EIO:
                            break
                        raise
                    if not chunk:
                        break
                    output.extend(chunk)
                elif process.poll() is not None:
                    break
            self.assertEqual(process.wait(timeout=1), 0, output.decode(errors='replace'))
            self.assertIn(['attach-session', '-t', 'probe-interactive'], self.recorded())
        finally:
            os.close(master)
            if process.poll() is None:
                process.kill()
                process.wait()


if __name__ == '__main__':
    unittest.main()
