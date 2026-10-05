"""Choose the system default input device while the device microphone records.

Voice input methods such as Chatterfly follow the system default input device.
They do not keep a device of their own, so the bridge selects the microphone by
switching that default, and restores the previous device when recording stops.
"""
import ctypes

SYSTEM = 1
GLOBAL = int.from_bytes(b"glob", "big")
MAIN = 0
UTF8 = 0x08000100
CORE_AUDIO = "/System/Library/Frameworks/CoreAudio.framework/CoreAudio"
CORE_FOUNDATION = "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"

class Address(ctypes.Structure):
    _fields_ = [("selector", ctypes.c_uint32),
                ("scope", ctypes.c_uint32),
                ("element", ctypes.c_uint32)]

def selector(text):
    return int.from_bytes(text.encode(), "big")

class CoreAudio:
    """Read device names and the default input device through the CoreAudio HAL."""

    def __init__(self, core_audio=None, core_foundation=None):
        self.ca = ctypes.CDLL(CORE_AUDIO) if core_audio is None else core_audio
        self.cf = ctypes.CDLL(CORE_FOUNDATION) if core_foundation is None else core_foundation
        self.ca.AudioObjectGetPropertyDataSize.argtypes = [
            ctypes.c_uint32, ctypes.POINTER(Address), ctypes.c_uint32, ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint32)]
        self.ca.AudioObjectGetPropertyData.argtypes = [
            ctypes.c_uint32, ctypes.POINTER(Address), ctypes.c_uint32, ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p]
        self.ca.AudioObjectSetPropertyData.argtypes = [
            ctypes.c_uint32, ctypes.POINTER(Address), ctypes.c_uint32, ctypes.c_void_p,
            ctypes.c_uint32, ctypes.c_void_p]
        self.cf.CFRelease.argtypes = [ctypes.c_void_p]
        self.cf.CFRelease.restype = None
        self.cf.CFStringGetCString.restype = ctypes.c_bool
        self.cf.CFStringGetCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                               ctypes.c_long, ctypes.c_uint32]

    def devices(self):
        address = Address(selector("dev#"), GLOBAL, MAIN)
        size = ctypes.c_uint32(0)
        status = self.ca.AudioObjectGetPropertyDataSize(SYSTEM, ctypes.byref(address), 0, None,
                                                        ctypes.byref(size))
        if status:
            raise RuntimeError(f"Cannot enumerate audio devices (status {status})")
        found = (ctypes.c_uint32 * (size.value // 4))()
        status = self.ca.AudioObjectGetPropertyData(SYSTEM, ctypes.byref(address), 0, None,
                                                    ctypes.byref(size), found)
        if status:
            raise RuntimeError(f"Cannot read audio devices (status {status})")
        return list(found)

    def string(self, device, fourcc):
        """Read a CFString property of a device, or return None."""
        address = Address(selector(fourcc), GLOBAL, MAIN)
        size = ctypes.c_uint32(ctypes.sizeof(ctypes.c_void_p))
        text = ctypes.c_void_p()
        if self.ca.AudioObjectGetPropertyData(device, ctypes.byref(address), 0, None,
                                              ctypes.byref(size), ctypes.byref(text)):
            return None
        buffer = ctypes.create_string_buffer(512)
        if not text.value:
            return None
        try:
            if not self.cf.CFStringGetCString(text, buffer, 512, UTF8):
                return None
            return buffer.value.decode("utf-8", "replace")
        finally:
            self.cf.CFRelease(text)

    def name(self, device):
        return self.string(device, "lnam")

    def uid(self, device):
        """Return the identifier that survives device reconnection."""
        return self.string(device, "uid ")

    def default_input(self):
        address = Address(selector("dIn "), GLOBAL, MAIN)
        size = ctypes.c_uint32(4)
        value = ctypes.c_uint32(0)
        status = self.ca.AudioObjectGetPropertyData(SYSTEM, ctypes.byref(address), 0, None,
                                                    ctypes.byref(size), ctypes.byref(value))
        if status:
            raise RuntimeError(f"Cannot read the default input (status {status})")
        return value.value

    def set_default_input(self, device):
        address = Address(selector("dIn "), GLOBAL, MAIN)
        value = ctypes.c_uint32(device)
        return self.ca.AudioObjectSetPropertyData(SYSTEM, ctypes.byref(address), 0, None, 4,
                                                  ctypes.byref(value)) == 0

    def find(self, wanted):
        """Return the identifier of the input device named `wanted`, if any."""
        named = [(self.name(device), device) for device in self.devices()]
        exact = [device for title, device in named if title == wanted]
        matches = exact or [device for title, device in named
                            if title and title.casefold() == wanted.casefold()]
        if len(matches) > 1:
            raise RuntimeError(f"More than one audio device is named {wanted!r}")
        return matches[0] if matches else None

class InputSwitcher:
    """Point the default input at one device while a recording session is active."""

    def __init__(self, name, hal=None):
        self.name = name
        self.hal = CoreAudio() if hal is None else hal
        self.saved = None
        self.selected = None

    def set(self, active):
        """Select the named device, or restore the device saved by `set(True)`.

        Return True when the default input changed.
        """
        if active:
            device = self.hal.find(self.name)
            if device is None:
                raise RuntimeError(f"No input device is named {self.name!r}")
            current = self.hal.default_input()
            if current == device:
                return False
            if self.saved is None:
                self.saved = current
            if not self.hal.set_default_input(device):
                raise RuntimeError("Cannot select the recording input")
            self.selected = device
            return True
        if self.saved is None:
            return False
        saved = self.saved
        current = self.hal.default_input()
        # Keep a new default chosen by the user or another application.
        if current != self.selected or current == saved:
            self.saved = None
            self.selected = None
            return False
        if not self.hal.set_default_input(saved):
            raise RuntimeError("Cannot restore the previous input")
        self.saved = None
        self.selected = None
        return True
