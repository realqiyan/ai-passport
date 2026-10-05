"""Exercise the usb and wifi entry points without touching audio or devices."""
import argparse
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from voice_bridge import cli


class LaunchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.token = Path(self.temp.name) / '.local' / 'token'
        self.token.parent.mkdir(parents=True)
        for target, value in (('DEFAULT_TOKEN', self.token),
                              ('warn_missing_microphone', mock.Mock())):
            patcher = mock.patch.object(cli, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def launched(self, function, *arguments):
        with mock.patch.object(cli, 'launch') as launch:
            function(argparse.Namespace(arguments=list(arguments)))
        return launch.call_args.args[0]

    def ports(self, *names):
        patcher = mock.patch.object(cli.glob, 'glob', return_value=list(names))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_usb_keeps_explicit_port_and_option_spaces(self):
        self.assertEqual(self.launched(cli.usb, '/dev/cu.test port', '--output', 'BlackHole 2ch'),
                         ['--serial', '/dev/cu.test port', '--output', 'BlackHole 2ch'])

    def test_usb_finds_the_only_device(self):
        self.ports('/dev/cu.usbmodem2101')
        self.assertEqual(self.launched(cli.usb), ['--serial', '/dev/cu.usbmodem2101'])
        self.assertEqual(self.launched(cli.usb, '--shortcut', 'ctrl+shift+v'),
                         ['--serial', '/dev/cu.usbmodem2101', '--shortcut', 'ctrl+shift+v'])

    def test_usb_reports_a_missing_device(self):
        self.ports()
        with self.assertRaises(SystemExit) as caught:
            self.launched(cli.usb)
        self.assertIn('/dev/cu.usbmodem', str(caught.exception))

    def test_usb_asks_which_device_when_several_exist(self):
        self.ports('/dev/cu.usbmodem2101', '/dev/cu.usbmodem3101')
        with self.assertRaises(SystemExit) as caught:
            self.launched(cli.usb)
        self.assertIn('/dev/cu.usbmodem3101', str(caught.exception))

    def test_wifi_remembers_an_explicit_address(self):
        self.assertEqual(self.launched(cli.wifi, '192.0.2.1', '--mic-device', ''),
                         ['--host', '192.0.2.1', '--mic-device', ''])
        self.assertEqual((self.token.parent / 'host').read_text(), '192.0.2.1\n')

    def test_wifi_discovers_without_an_address(self):
        host = str(self.token.parent / 'host')
        self.assertEqual(self.launched(cli.wifi), ['--discover', '--host-file', host])
        self.assertFalse((self.token.parent / 'host').exists())

    def test_wifi_keeps_options_that_look_like_an_address_missing(self):
        host = str(self.token.parent / 'host')
        self.assertEqual(self.launched(cli.wifi, '--shortcut', 'ctrl+shift+v'),
                         ['--discover', '--host-file', host, '--shortcut', 'ctrl+shift+v'])

    def test_unknown_command_fails(self):
        with self.assertRaises(SystemExit) as caught:
            cli.main(['invalid'])
        self.assertNotEqual(caught.exception.code, 0)
