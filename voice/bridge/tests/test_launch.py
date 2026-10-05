"""Test real argument parsing and both Python entry points without hardware."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from voice_bridge import cli


class LaunchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.token = Path(self.temp.name) / 'token'
        for target, value in (('DEFAULT_TOKEN', self.token),
                              ('warn_missing_microphone', mock.Mock())):
            patcher = mock.patch.object(cli, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def launched(self, *arguments):
        with mock.patch.object(cli, 'run') as run:
            self.assertEqual(cli.main(list(arguments)), 0)
        return run.call_args.args[0]

    def test_usb_keeps_explicit_port_and_option_spaces(self):
        args = self.launched('usb', '/dev/cu.test port', '--output', 'BlackHole 2ch')
        self.assertEqual(args.serial, '/dev/cu.test port')
        self.assertEqual(args.output, 'BlackHole 2ch')

    def test_usb_without_port_accepts_bridge_options(self):
        with mock.patch.object(cli.glob, 'glob', return_value=['/dev/cu.usbmodem2101']):
            args = self.launched('usb', '--shortcut', 'ctrl+shift+v', '--mic-device', '')
        self.assertEqual(args.serial, '/dev/cu.usbmodem2101')
        self.assertEqual(args.shortcut, (3, 25))
        self.assertEqual(args.mic_device, '')

    def test_usb_reports_a_missing_device(self):
        with mock.patch.object(cli.glob, 'glob', return_value=[]), self.assertRaises(SystemExit) as caught:
            self.launched('usb')
        self.assertIn('/dev/cu.usbmodem', str(caught.exception))

    def test_usb_asks_which_device_when_several_exist(self):
        with mock.patch.object(cli.glob, 'glob', return_value=['/dev/cu.a', '/dev/cu.b']), self.assertRaises(SystemExit) as caught:
            self.launched('usb')
        self.assertIn('/dev/cu.b', str(caught.exception))

    def test_wifi_does_not_change_cache_before_authentication(self):
        args = self.launched('wifi', '192.0.2.1', '--mic-device', '')
        self.assertEqual(args.host, '192.0.2.1')
        self.assertFalse(args.discover)
        self.assertFalse(args.host_file.exists())

    def test_wifi_without_address_accepts_all_bridge_options(self):
        host = Path(self.temp.name) / 'custom host'
        args = self.launched('wifi', '--shortcut', 'ctrl+shift+v', '--host-file', str(host),
                             '--token-file', str(self.token), '--output', 'Output with spaces')
        self.assertTrue(args.discover)
        self.assertEqual(args.host_file, host)
        self.assertEqual(args.token_file, self.token)
        self.assertEqual(args.output, 'Output with spaces')

    def test_unknown_commands_and_options_fail_before_launch(self):
        for argv in (['invalid'], ['wifi', '--typo'], ['usb', '/dev/cu.test', '--typo']):
            with self.subTest(argv=argv), mock.patch.object(cli, 'run') as run, self.assertRaises(SystemExit) as caught:
                cli.main(argv)
            self.assertEqual(caught.exception.code, 2)
            run.assert_not_called()

    def test_cancelled_cleanup_returns_failure_to_prevent_chained_uninstall(self):
        with mock.patch.object(cli.lifecycle, 'cleanup', return_value=False):
            self.assertEqual(cli.main(['cleanup']), 1)

    def test_module_entry_preserves_package_imports(self):
        # Missing USB ports stop before audio or transport initialization.
        code = "from unittest.mock import patch; import runpy, sys; sys.argv=['voice_bridge.cli','usb']; " + \
               "p=patch('glob.glob', return_value=[]); p.start(); runpy.run_module('voice_bridge.cli', run_name='__main__')"
        result = subprocess.run([sys.executable, '-c', code], env=os.environ,
                                text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 1)
        self.assertIn('/dev/cu.usbmodem', result.stderr)
        self.assertNotIn('ImportError', result.stderr)
