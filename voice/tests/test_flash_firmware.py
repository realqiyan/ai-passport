import importlib.util
import contextlib
import io
from types import SimpleNamespace
import sys
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('flash_firmware', Path(__file__).resolve().parents[1] / 'flash_firmware.py')
flash = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flash)


def table(size=3 * 1024 * 1024, offset=0x10000, subtype=0, flags=0):
    entry = struct.pack('<HBBII16sI', 0x50AA, 0, subtype, offset, size, b'factory', flags)
    return entry + bytes([255]) * (4096 - len(entry))


def image():
    header = bytearray(112)
    header[0] = 0xE9
    struct.pack_into('<H', header, 12, 5)
    struct.pack_into('<I', header, 32, 0xABCD5432)
    header[80:98] = b'FoloToy-AI-Passport'
    return bytes(header)


class FlashTests(unittest.TestCase):
    def test_accepts_recorded_device_app_partition(self):
        self.assertEqual(flash.check_partition(table(), 1211216), 3 * 1024 * 1024)

    def test_refuses_oversize_or_wrong_partition(self):
        for data, size in [(table(), 3 * 1024 * 1024 + 1), (table(offset=0x20000), 24),
                           (table(subtype=0x10), 24), (table(flags=1), 24),
                           (table()[:32], 24), (bytes(4096), 24)]:
            with self.subTest(size=size, data=data[:32]):
                with self.assertRaises(ValueError):
                    flash.check_partition(data, size)

    def test_refuses_merged_or_wrong_chip_images(self):
        for data in (bytes(24), image()[:12], image()[:12] + bytes(12)):
            with self.assertRaises(ValueError):
                flash.check_application(data)

    def test_merged_bootloader_header_is_rejected(self):
        merged = bytearray(image())
        struct.pack_into('<I', merged, 32, 0x50)
        with self.assertRaisesRegex(ValueError, 'merged image'):
            flash.check_application(merged)

    def test_wrong_project_is_rejected(self):
        other = bytearray(image())
        other[80:112] = bytes(32)
        with self.assertRaisesRegex(ValueError, 'another project'):
            flash.check_application(other)

    def test_write_and_verify_only_after_partition_check(self):
        with tempfile.TemporaryDirectory() as directory:
            firmware = Path(directory) / 'app.bin'
            firmware.write_bytes(image())
            def run(args, **kwargs):
                if 'read_flash' in args:
                    Path(args[-1]).write_bytes(table())
                if 'image_info' in args:
                    # A source file change cannot replace the checked snapshot.
                    firmware.write_bytes(bytes(24))
                if 'write_flash' in args:
                    self.assertEqual(Path(args[-1]).read_bytes(), image())
            with patch.object(flash.subprocess, 'run', side_effect=run) as commands:
                flash.flash('/dev/cu.test', firmware)
            calls = [call.args[0] for call in commands.call_args_list]
            self.assertIn('read_flash', calls[1])
            self.assertEqual(calls[2][-3:-1], ['write_flash', '0x10000'])
            self.assertEqual(calls[3][-3:-1], ['verify_flash', '0x10000'])

    def test_partition_failure_never_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            firmware = Path(directory) / 'app.bin'
            firmware.write_bytes(image())
            def run(args, **kwargs):
                if 'read_flash' in args:
                    Path(args[-1]).write_bytes(table(size=1))
            with patch.object(flash.subprocess, 'run', side_effect=run) as commands:
                with self.assertRaises(ValueError):
                    flash.flash('/dev/cu.test', firmware)
            self.assertFalse(any('write_flash' in c.args[0] for c in commands.call_args_list))


class PortListTests(unittest.TestCase):
    def test_lists_ports_without_flashing_or_opening_them(self):
        enumeration = SimpleNamespace(comports=lambda: [
            SimpleNamespace(device='/dev/cu.usbmodem2101', description='USB JTAG/serial debug unit', vid=0x303a, pid=0x1001),
            SimpleNamespace(device='/dev/cu.Bluetooth', description='Bluetooth', vid=None, pid=None)])
        output = io.StringIO()
        modules = {'serial': SimpleNamespace(), 'serial.tools': SimpleNamespace(list_ports=enumeration)}
        with patch.dict(sys.modules, modules), patch.object(flash, 'flash') as write, \
             patch.object(flash.subprocess, 'run') as command, contextlib.redirect_stdout(output):
            self.assertEqual(flash.main(['--list-ports']), 0)
        write.assert_not_called()
        command.assert_not_called()
        self.assertEqual(output.getvalue().splitlines(), [
            '/dev/cu.Bluetooth: Bluetooth',
            '/dev/cu.usbmodem2101: USB JTAG/serial debug unit [USB 303a:1001]'])

    def test_no_ports_has_an_actionable_message(self):
        output = io.StringIO()
        enumeration = SimpleNamespace(comports=lambda: [])
        with patch.dict(sys.modules, {'serial': SimpleNamespace(), 'serial.tools': SimpleNamespace(list_ports=enumeration)}), \
             contextlib.redirect_stdout(output):
            self.assertEqual(flash.main(['--list-ports']), 0)
        self.assertIn('USB data cable', output.getvalue())

    def test_missing_serial_support_is_reported(self):
        with patch.dict(sys.modules, {'serial': None}), contextlib.redirect_stderr(io.StringIO()) as error:
            self.assertEqual(flash.main(['--list-ports']), 1)
        self.assertIn('Activate ESP-IDF', error.getvalue())

    def test_incomplete_or_mixed_arguments_never_flash(self):
        with patch.object(flash, 'flash') as write, contextlib.redirect_stderr(io.StringIO()):
            for args in ([], ['test-port'], ['--list-ports', 'test-port', 'test.bin']):
                with self.subTest(args=args), self.assertRaises(SystemExit) as error:
                    flash.main(args)
                self.assertEqual(error.exception.code, 2)
        write.assert_not_called()
