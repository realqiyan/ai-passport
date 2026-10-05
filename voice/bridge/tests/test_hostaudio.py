import unittest
from voice_bridge.hostaudio import InputSwitcher

class FakeHal:
    def __init__(self, names, default):
        self.names = dict(names)
        self.current = default
        self.writes = []

    def find(self, wanted):
        if wanted in self.names:
            return self.names[wanted]
        folded = [d for n, d in self.names.items() if n.casefold() == wanted.casefold()]
        return folded[0] if len(folded) == 1 else None

    def default_input(self):
        return self.current

    def set_default_input(self, device):
        self.writes.append(device)
        self.current = device
        return True

class InputSwitcherTests(unittest.TestCase):
    def hal(self):
        return FakeHal({"Passport Mic": 120, "MacBook Pro麦克风": 97}, 97)

    def test_selects_the_microphone_and_restores_the_previous_device(self):
        hal = self.hal()
        switcher = InputSwitcher("Passport Mic", hal)
        self.assertTrue(switcher.set(True))
        self.assertEqual(hal.current, 120)
        self.assertTrue(switcher.set(False))
        self.assertEqual(hal.current, 97)
        self.assertEqual(hal.writes, [120, 97])

    def test_repeated_selection_keeps_the_first_saved_device(self):
        hal = self.hal()
        switcher = InputSwitcher("Passport Mic", hal)
        switcher.set(True)
        hal.current = 97  # Another program changed the default during recording.
        self.assertTrue(switcher.set(True))
        self.assertEqual(hal.current, 120)
        switcher.set(False)
        self.assertEqual(hal.current, 97)

    def test_already_selected_device_needs_no_restore(self):
        hal = self.hal()
        hal.current = 120
        switcher = InputSwitcher("Passport Mic", hal)
        self.assertFalse(switcher.set(True))
        self.assertFalse(switcher.set(False))
        self.assertEqual(hal.writes, [])
        self.assertEqual(hal.current, 120)

    def test_release_without_selection_does_nothing(self):
        hal = self.hal()
        self.assertFalse(InputSwitcher("Passport Mic", hal).set(False))
        self.assertEqual(hal.writes, [])

    def test_unknown_device_reports_an_error(self):
        switcher = InputSwitcher("Missing Mic", self.hal())
        with self.assertRaisesRegex(RuntimeError, "Missing Mic"):
            switcher.set(True)
        self.assertFalse(switcher.set(False))

    def test_restore_keeps_a_new_input_selected_by_the_user(self):
        hal = self.hal()
        switcher = InputSwitcher("Passport Mic", hal)
        switcher.set(True)
        hal.current = 42
        self.assertFalse(switcher.set(False))
        self.assertEqual(hal.current, 42)
        self.assertIsNone(switcher.saved)

    def test_failed_restore_can_be_retried(self):
        from unittest.mock import patch
        hal = self.hal()
        switcher = InputSwitcher("Passport Mic", hal)
        switcher.set(True)
        with patch.object(hal, "set_default_input", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "restore"):
                switcher.set(False)
        self.assertEqual(switcher.saved, 97)
        self.assertTrue(switcher.set(False))
        self.assertEqual(hal.current, 97)

    def test_default_constructor_reads_the_system_devices(self):
        import sys
        if sys.platform != "darwin":
            self.skipTest("Host audio control needs macOS")
        hal = InputSwitcher("Passport Mic").hal
        self.assertIsInstance(hal.default_input(), int)


class CoreAudioErrorTests(unittest.TestCase):
    def test_native_query_errors_are_not_reported_as_missing_devices(self):
        from unittest.mock import Mock
        from voice_bridge.hostaudio import CoreAudio
        hal = CoreAudio.__new__(CoreAudio)
        hal.ca = Mock()
        hal.ca.AudioObjectGetPropertyDataSize.return_value = -50
        with self.assertRaisesRegex(RuntimeError, 'enumerate'):
            hal.devices()
        hal.ca.AudioObjectGetPropertyData.return_value = -50
        with self.assertRaisesRegex(RuntimeError, 'default input'):
            hal.default_input()

    def test_duplicate_device_names_are_rejected(self):
        from unittest.mock import Mock
        from voice_bridge.hostaudio import CoreAudio
        hal = CoreAudio.__new__(CoreAudio)
        hal.devices = Mock(return_value=[1, 2])
        hal.name = Mock(return_value="Passport Mic")
        with self.assertRaisesRegex(RuntimeError, "More than one"):
            hal.find("Passport Mic")

    def test_device_strings_are_released_after_conversion(self):
        import ctypes
        from unittest.mock import Mock
        from voice_bridge.hostaudio import CoreAudio
        hal = CoreAudio.__new__(CoreAudio)
        hal.ca, hal.cf = Mock(), Mock()
        def read(device, address, qualifier_size, qualifier, size, out):
            ctypes.cast(out, ctypes.POINTER(ctypes.c_void_p))[0] = 123
            return 0
        def convert(value, buffer, size, encoding):
            buffer.value = b'Passport Mic'
            return True
        hal.ca.AudioObjectGetPropertyData.side_effect = read
        hal.cf.CFStringGetCString.side_effect = convert
        self.assertEqual(hal.name(120), 'Passport Mic')
        self.assertEqual(hal.cf.CFRelease.call_args[0][0].value, 123)
        hal.cf.CFRelease.reset_mock()
        hal.cf.CFStringGetCString.side_effect = lambda *args: False
        self.assertIsNone(hal.name(120))
        hal.cf.CFRelease.assert_called_once()

if __name__ == "__main__":
    unittest.main()
