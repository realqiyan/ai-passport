"""Test pipx wrappers in a sandbox without installed packages or macOS audio."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ScriptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'Other Mac [test] with spaces' / 'voice'
        self.root.mkdir(parents=True)
        for name in ('install.sh', 'start.sh', 'uninstall.sh', 'configure.sh', 'bridge-command.sh'):
            shutil.copy2(ROOT / name, self.root / name)
        self.bin = Path(self.temp.name) / 'bin'
        self.bin.mkdir()
        self.log = Path(self.temp.name) / 'calls'
        self.venvs = Path(self.temp.name) / 'pipx envs'
        self.voice = self.venvs / 'passport-voice-bridge/bin/passport-voice'
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ['PATH'],
                        CALL_LOG=str(self.log), PIPX_VENVS=str(self.venvs),
                        INSTALLED_SOURCE=str(self.root / 'bridge'))
        self.executable(self.bin / 'uname', 'printf "Darwin\\n"')
        self.executable(self.bin / 'pipx', '''printf 'pipx %s\n' "$*" >>"$CALL_LOG"
case "$1" in
environment) printf '%s\n' "$PIPX_VENVS" ;;
install) [ "${INSTALL_FAIL:-0}" = 0 ] || exit 1 ;;
uninstall) [ "${UNINSTALL_FAIL:-0}" = 0 ] || exit 1 ;;
esac''')
        self.executable(self.voice, '''printf '%s\n' "$@" >>"$CALL_LOG"
if [ "$1" = cleanup ] && [ "${CLEANUP_FAIL:-0}" = 1 ]; then exit 1; fi''')
        self.executable(self.voice.parent / 'python', '''[ "${SOURCE_FAIL:-0}" = 0 ] || exit 1
printf '%s\n' "$INSTALLED_SOURCE"''')
        self.legacy = self.root / 'bridge/.venv/bin/passport-voice'
        self.executable(self.legacy, 'printf "legacy %s\\n" "$*" >>"$CALL_LOG"')
        self.executable(self.legacy.parent / 'python', 'printf "%s\\n" "$INSTALLED_SOURCE"')
        (self.root / '.local').mkdir()
        (self.root / '.local/token').write_text('test')

    def executable(self, path, body):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('#!/bin/bash\n' + body + '\n')
        path.chmod(0o755)

    def run_script(self, name, *args, text=None):
        return subprocess.run(['bash', str(self.root / name), *args], env=self.env,
                              input=text, text=True, capture_output=True, timeout=15,
                              cwd=self.temp.name)

    def test_start_uses_pipx_without_a_project_environment(self):
        shutil.rmtree(self.root / 'bridge/.venv')
        result = self.run_script('start.sh', 'usb', '/dev/cu.test port', '--output', 'BlackHole 2ch')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.log.read_text().splitlines()[1:],
                         ['usb', '/dev/cu.test port', '--output', 'BlackHole 2ch'])

    def test_start_reports_a_missing_pipx_installation(self):
        shutil.rmtree(self.venvs)
        result = self.run_script('start.sh', 'usb')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('install.sh', result.stderr)

    def test_uninstall_cancels_before_cleanup(self):
        self.assertEqual(self.run_script('uninstall.sh', text='no\n').returncode, 0)
        self.assertTrue(self.legacy.exists())
        self.assertNotIn('cleanup', self.log.read_text())

    def test_invalid_arguments_do_not_touch_pipx(self):
        for name, argv in [('uninstall.sh', ['--yes', 'extra']), ('uninstall.sh', ['--no']),
                           ('install.sh', ['--output', 'test'])]:
            self.assertNotEqual(self.run_script(name, *argv).returncode, 0)
        self.assertFalse(self.log.exists())

    def test_foreign_checkout_is_preserved_by_install_and_uninstall(self):
        self.env['INSTALLED_SOURCE'] = str(Path(self.temp.name) / 'other checkout/bridge')
        for name, argv in [('uninstall.sh', ['--yes']), ('install.sh', []), ('start.sh', ['wifi'])]:
            result = self.run_script(name, *argv)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('与当前目录不同', result.stderr)
        calls = self.log.read_text()
        self.assertNotIn('cleanup', calls)
        self.assertNotIn('pipx uninstall', calls)
        self.assertNotIn('pipx install', calls)
        self.assertTrue(self.legacy.exists())
        self.assertTrue((self.root / '.local/token').exists())

    def test_unverifiable_installation_stops_before_cleanup(self):
        self.env['SOURCE_FAIL'] = '1'
        result = self.run_script('uninstall.sh', '--yes')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('cleanup', self.log.read_text())

    def test_uninstall_cleans_before_removing_environment(self):
        result = self.run_script('uninstall.sh', '--yes')
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.log.read_text()
        self.assertLess(calls.index('cleanup\n'), calls.index('pipx uninstall'))
        self.assertIn(str(self.root / '.local'), calls)
        self.assertFalse(self.legacy.exists())
        self.assertTrue((self.root / 'start.sh').exists())

    def test_cleanup_failure_preserves_both_environments_and_state(self):
        self.env['CLEANUP_FAIL'] = '1'
        self.assertNotEqual(self.run_script('uninstall.sh', '--yes').returncode, 0)
        self.assertNotIn('pipx uninstall', self.log.read_text())
        self.assertTrue(self.legacy.exists())
        self.assertTrue(self.voice.exists())
        self.assertTrue((self.root / '.local/token').exists())

    def test_pipx_uninstall_failure_preserves_legacy_environment(self):
        self.env['UNINSTALL_FAIL'] = '1'
        self.assertNotEqual(self.run_script('uninstall.sh', '--yes').returncode, 0)
        self.assertTrue(self.legacy.exists())

    def test_legacy_only_uninstall_does_not_remove_a_pipx_package(self):
        shutil.rmtree(self.venvs)
        self.assertEqual(self.run_script('uninstall.sh', '--yes').returncode, 0)
        self.assertIn('legacy cleanup', self.log.read_text())
        self.assertNotIn('pipx uninstall', self.log.read_text())

    def test_install_refreshes_owned_package_and_runs_setup(self):
        for _ in range(2):
            result = self.run_script('install.sh')
            self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.log.read_text()
        self.assertIn('pipx install --editable ' + str(self.root / 'bridge') + ' --force', calls)
        self.assertIn('setup\n--legacy-state-dir\n' + str(self.root / '.local'), calls)
        self.assertNotIn('legacy ', calls)

    def test_first_install_creates_pipx_environment_without_force(self):
        template = Path(self.temp.name) / 'template'
        shutil.copytree(self.voice.parent, template)
        shutil.rmtree(self.venvs)
        self.env['TEMPLATE'] = str(template)
        self.executable(self.bin / 'pipx', """printf 'pipx %s\n' "$*" >>"$CALL_LOG"
case "$1" in
environment) printf '%s\n' "$PIPX_VENVS" ;;
install)
    mkdir -p "$PIPX_VENVS/passport-voice-bridge/bin"
    cp "$TEMPLATE/python" "$TEMPLATE/passport-voice" "$PIPX_VENVS/passport-voice-bridge/bin/"
    ;;
esac""")
        result = self.run_script('install.sh')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('--force', self.log.read_text())
        self.assertIn('setup\n', self.log.read_text())

    def test_custom_python_rebuilds_the_owned_environment(self):
        self.env['PYTHON'] = '/custom python/bin/python'
        result = self.run_script('install.sh')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('pipx reinstall passport-voice-bridge --python /custom python/bin/python', self.log.read_text())
        self.assertNotIn('--force', self.log.read_text())

    def test_install_failure_does_not_run_setup(self):
        self.env['INSTALL_FAIL'] = '1'
        self.assertNotEqual(self.run_script('install.sh').returncode, 0)
        self.assertNotIn('setup\n', self.log.read_text())

    def test_configure_uses_pipx_and_preserves_parameters(self):
        shutil.rmtree(self.root / 'bridge/.venv')
        result = self.run_script('configure.sh', '/dev/cu.port with spaces', '--shortcut', 'ctrl+shift+v')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.log.read_text().splitlines()[1:],
                         ['configure', '--serial', '/dev/cu.port with spaces', '--shortcut', 'ctrl+shift+v'])
