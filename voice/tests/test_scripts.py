"""Exercise shell entry points without changing macOS audio or installed files."""
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
        for name in ('install.sh', 'start.sh', 'uninstall.sh', 'configure.sh'):
            shutil.copy2(ROOT / name, self.root / name)
        self.bin = Path(self.temp.name) / 'bin'
        self.bin.mkdir()
        self.log = Path(self.temp.name) / 'calls'
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ['PATH'],
                        CALL_LOG=str(self.log), MIC_DEFAULT='Built-in', MIC_STATE='present')
        self.executable(self.bin / 'uname', 'printf "Darwin\\n"')
        self.executable(self.bin / 'pgrep', '''printf 'pgrep %s\n' "$*" >>"$CALL_LOG"
exit 1''')
        self.executable(self.bin / 'pipx', '''printf 'pipx %s\n' "$*" >>"$CALL_LOG"
if [ "$1" = environment ]; then
    printf '%s\n' "${PIPX_VENVS:-}"
fi
if [ "$1" = list ] && [ "${PIPX_PACKAGE:-0}" = 1 ]; then
    printf 'passport-voice-bridge 0.1.0\n'
fi''')
        self.voice = self.root / 'bridge/.venv/bin/passport-voice'
        self.executable(self.voice, '''if [ "$1" = microphone ]; then
    [ "${MIC_FAIL:-0}" = 0 ] || exit 1
    printf 'Passport Mic: %s\\nDefault input: %s\\n' "$MIC_STATE" "$MIC_DEFAULT"
else
    printf '%s\\n' "$@" >>"$CALL_LOG"
fi''')
        self.executable(self.voice.parent / 'python', '''cat >/dev/null
printf 'remove\\n' >>"$CALL_LOG"''')
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

    def test_start_forwards_arguments_verbatim(self):
        result = self.run_script('start.sh', 'usb', '/dev/cu.test port', '--output', 'BlackHole 2ch')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.log.read_text().splitlines(),
                         ['usb', '/dev/cu.test port', '--output', 'BlackHole 2ch'])

    def test_start_fails_without_installed_bridge(self):
        self.voice.unlink()
        result = self.run_script('start.sh', 'usb')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('install.sh', result.stderr)

    def test_uninstall_cancels_without_removing_files(self):
        self.assertEqual(self.run_script('uninstall.sh', text='no\n').returncode, 0)
        self.assertTrue(self.voice.exists())
        self.assertTrue((self.root / '.local/token').exists())

    def test_uninstall_rejects_extra_arguments(self):
        self.assertNotEqual(self.run_script('uninstall.sh', '--yes', 'extra').returncode, 0)
        self.assertTrue(self.voice.exists())

    def test_uninstall_leaves_a_missing_pipx_package_alone(self):
        self.assertEqual(self.run_script('uninstall.sh', '--yes').returncode, 0)
        self.assertNotIn('pipx uninstall passport-voice-bridge', self.log.read_text())

    def test_uninstall_removes_the_pipx_package(self):
        self.env['PIPX_PACKAGE'] = '1'
        self.env['PIPX_VENVS'] = str(self.root / 'pipx-venvs')
        self.assertEqual(self.run_script('uninstall.sh', '--yes').returncode, 0)
        self.assertIn('pipx uninstall passport-voice-bridge', self.log.read_text())

    def test_uninstall_fails_closed_when_audio_query_fails(self):
        self.env['MIC_FAIL'] = '1'
        self.assertNotEqual(self.run_script('uninstall.sh', '--yes').returncode, 0)
        self.assertTrue(self.voice.exists())

    def test_uninstall_rejects_default_input_without_owned_bridge(self):
        self.env['MIC_DEFAULT'] = 'Passport Mic'
        self.assertNotEqual(self.run_script('uninstall.sh', '--yes').returncode, 0)
        self.assertTrue(self.voice.exists())

    def test_uninstall_removes_only_local_files(self):
        result = self.run_script('uninstall.sh', '--yes')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.voice.exists())
        self.assertFalse((self.root / '.local/token').exists())
        self.assertTrue((self.root / 'start.sh').exists())
        self.assertIn('remove\n', self.log.read_text())
        self.assertNotIn('command not found', result.stderr)
        self.assertIn(r'Other Mac \[test\]', self.log.read_text())

    def test_uninstall_leaves_other_bridge_process_running(self):
        self.executable(self.bin / 'pgrep', '''printf 'pgrep %s\\n' "$*" >>"$CALL_LOG"
case "$*" in *'[p]assport-voice'*) exit 0 ;; *) exit 1 ;; esac''')
        result = self.run_script('uninstall.sh', '--yes')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.voice.exists())
        self.assertNotIn('remove\n', self.log.read_text())

    def test_install_rejects_arguments(self):
        self.assertNotEqual(self.run_script('install.sh', '--output', 'test').returncode, 0)

    def test_uninstall_stops_owned_bridge_before_deleting_device(self):
        marker = Path(self.temp.name) / 'running'
        marker.touch()
        self.env['RUNNING_MARKER'] = str(marker)
        self.executable(self.bin / 'pgrep', '''case "$*" in
*'[p]assport-voice'*) exit 1 ;;
*) [ -e "$RUNNING_MARKER" ] ;;
esac''')
        self.executable(self.bin / 'pkill', '''printf 'stop %s\\n' "$*" >>"$CALL_LOG"
rm "$RUNNING_MARKER"''')
        result = self.run_script('uninstall.sh', '--yes')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(self.log.read_text().index('stop '), self.log.read_text().index('remove\n'))
        self.assertFalse(marker.exists())

    def test_uninstall_checks_restore_after_stopping_bridge(self):
        marker = Path(self.temp.name) / 'running'
        marker.touch()
        self.env.update(RUNNING_MARKER=str(marker), MIC_DEFAULT='Passport Mic')
        self.executable(self.bin / 'pgrep', '''case "$*" in
*'[p]assport-voice'*) exit 1 ;;
*) [ -e "$RUNNING_MARKER" ] ;;
esac''')
        self.executable(self.bin / 'pkill', 'rm "$RUNNING_MARKER"')
        # The native removal call fails if restoration did not succeed.
        self.executable(self.voice.parent / 'python', 'cat >/dev/null; exit 1')
        result = self.run_script('uninstall.sh', '--yes')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.voice.exists())
        self.assertTrue((self.root / '.local/token').exists())

    def test_install_repeats_in_path_with_spaces_and_custom_python(self):
        driver = self.root / 'test BlackHole2ch.driver'
        driver.mkdir()
        installer = self.root / 'install.sh'
        installer.write_text(installer.read_text().replace(
            '/Library/Audio/Plug-Ins/HAL/BlackHole2ch.driver', str(driver)))
        custom = self.bin / 'python custom'
        self.executable(custom, 'printf "Python 3.12\\n"')
        self.env['PYTHON'] = str(custom)
        self.executable(self.voice.parent / 'python', 'printf "pip %s\\n" "$*" >>"$CALL_LOG"')
        self.executable(self.voice, '''case "$1" in
microphone) printf 'Passport Mic: present\\nDefault input: Built-in\\n' ;;
devices) printf 'BlackHole 2ch\\n' ;;
--help) exit 0 ;;
*) exit 1 ;;
esac''')
        for _ in range(2):
            result = self.run_script('install.sh')
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.voice.exists())

    def test_configure_preserves_shortcut_and_serial_parameters(self):
        result = self.run_script('configure.sh', '/dev/cu.port with spaces', '--shortcut', 'ctrl+shift+v')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.log.read_text().splitlines(),
                         ['configure', '--serial', '/dev/cu.port with spaces', '--shortcut', 'ctrl+shift+v'])
