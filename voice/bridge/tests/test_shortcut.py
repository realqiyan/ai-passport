import unittest
from voice_bridge.shortcut import KEYCODES, Injector

class FakeQuartz:
    kCGEventSourceStateHIDSystemState = 0
    kCGHIDEventTap = 0
    kCGEventFlagMaskControl = 1
    kCGEventFlagMaskShift = 2
    kCGEventFlagMaskAlternate = 4
    kCGEventFlagMaskCommand = 8

    def __init__(self):
        self.posted = []

    def CGEventSourceCreate(self, state):
        return "source"

    def CGEventCreateKeyboardEvent(self, source, code, down):
        return (code, down)

    def CGEventSetFlags(self, event, flags):
        self.flags = flags

    def CGEventPost(self, tap, event):
        self.posted.append((event, self.flags))

class ShortcutTests(unittest.TestCase):
    def test_keycodes_match_the_device_key_set(self):
        self.assertEqual(KEYCODES[25], 9)   # v
        self.assertEqual(KEYCODES[4], 0)    # a
        self.assertEqual(KEYCODES[29], 6)   # z
        self.assertEqual(KEYCODES[44], 49)  # space
        self.assertEqual(KEYCODES[0x39 + 1], 122)  # f1

    def test_control_shift_v_presses_and_releases(self):
        quartz = FakeQuartz()
        Injector(quartz).send(3, 25)
        self.assertEqual([event for event, _ in quartz.posted],
                         [(59, True), (56, True), (9, True), (9, False), (56, False), (59, False)])
        self.assertEqual([flags for _, flags in quartz.posted], [1, 3, 3, 3, 1, 0])

    def test_keyboard_keys_press_and_release_without_modifiers(self):
        for usage, code in ((0x28, 36), (0x2a, 51), (0x52, 126), (0x51, 125)):
            with self.subTest(usage=usage):
                quartz = FakeQuartz()
                Injector(quartz).send(0, usage)
                self.assertEqual(quartz.posted, [((code, True), 0), ((code, False), 0)])

    def test_default_constructor_loads_the_system_framework(self):
        try:
            import Quartz
        except ImportError:
            self.skipTest("Key injection needs macOS")
        injector = Injector()
        self.assertIs(injector.quartz, Quartz)
        self.assertTrue(injector.source)

    def test_rejects_input_that_is_not_a_key(self):
        injector = Injector(FakeQuartz())
        with self.assertRaises(ValueError):
            injector.send(3, 0x99)
        with self.assertRaises(ValueError):
            injector.send("ctrl", 25)

if __name__ == "__main__":
    unittest.main()
