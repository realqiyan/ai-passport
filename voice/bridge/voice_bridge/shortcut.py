"""Press the configured shortcut on this Mac with a synthetic key press.

The device reports a shortcut event over the link. This module turns that report
into one key press for the focused application. macOS delivers synthetic events
only to a process that the user trusts for Accessibility.
"""
import ctypes

# USB HID keyboard usage -> macOS virtual key code.
# Letters follow the alphabetical HID order that starts at usage 0x04.
LETTERS = {
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8,
    "v": 9, "b": 11, "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17,
    "o": 31, "u": 32, "i": 34, "p": 35, "l": 37, "j": 38, "k": 40, "n": 45,
    "m": 46,
}
# Return, Escape, Backspace, Tab, Space, Down and Up.
NAMED = {0x28: 36, 0x29: 53, 0x2a: 51, 0x2b: 48, 0x2c: 49, 0x51: 125, 0x52: 126}
# kVK_F1 through kVK_F12.
FUNCTION = {0x3a + index: code for index, code in enumerate(
    (122, 120, 99, 118, 96, 97, 98, 100, 101, 109, 103, 111))}
KEYCODES = {4 + index: LETTERS[letter] for index, letter in enumerate("abcdefghijklmnopqrstuvwxyz")}
KEYCODES.update(NAMED)
KEYCODES.update(FUNCTION)

# Configuration modifier bit -> macOS virtual key code and event flag.
MODIFIERS = (
    (1, 59, "kCGEventFlagMaskControl"),
    (2, 56, "kCGEventFlagMaskShift"),
    (4, 58, "kCGEventFlagMaskAlternate"),
    (8, 55, "kCGEventFlagMaskCommand"),
)
TRUST_PATH = "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
_application_services = None

def trusted():
    """Report whether macOS lets this process control other applications.

    macOS drops events from an untrusted process without an error, so callers
    must ask before they report a successful press. The answer is read on every
    call, because the user can grant the permission while the bridge runs.
    """
    global _application_services
    if _application_services is None:
        _application_services = ctypes.cdll.LoadLibrary(TRUST_PATH)
        _application_services.AXIsProcessTrusted.restype = ctypes.c_bool
    return bool(_application_services.AXIsProcessTrusted())

class Injector:
    """Press one shortcut in the focused application."""

    def __init__(self, quartz=None):
        if quartz is None:
            try:
                import Quartz
            except ImportError as error:
                raise RuntimeError(
                    "Install key support: pip install pyobjc-framework-Quartz") from error
            quartz = Quartz
        self.quartz = quartz
        self.source = quartz.CGEventSourceCreate(quartz.kCGEventSourceStateHIDSystemState)
        if not self.source:
            raise RuntimeError("Cannot create an event source")

    def send(self, modifiers, key):
        """Press key with modifiers, then release the key and the modifiers."""
        if not isinstance(modifiers, int) or not isinstance(key, int):
            raise ValueError("Modifiers and key must be integers")
        code = KEYCODES.get(key)
        if code is None:
            raise ValueError(f"Unsupported key code {key}")
        flags = 0
        held = []
        for bit, modifier, name in MODIFIERS:
            if modifiers & bit:
                flags |= getattr(self.quartz, name)
                self.post(modifier, True, flags)
                held.append((modifier, name))
        self.post(code, True, flags)
        self.post(code, False, flags)
        for modifier, name in reversed(held):
            flags &= ~getattr(self.quartz, name)
            self.post(modifier, False, flags)

    def post(self, code, down, flags):
        event = self.quartz.CGEventCreateKeyboardEvent(self.source, code, down)
        if not event:
            raise RuntimeError("Cannot create a key event")
        self.quartz.CGEventSetFlags(event, flags)
        self.quartz.CGEventPost(self.quartz.kCGHIDEventTap, event)
