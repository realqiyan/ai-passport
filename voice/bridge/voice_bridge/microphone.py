"""Create the aggregate input device that voice input methods record from.

Some voice input methods do not list virtual devices such as BlackHole, but
they do list an aggregate device that contains BlackHole as a subdevice.

The aggregate is not private, so coreaudiod keeps it across restarts. It
appears in the system settings under the name in DEFAULT_NAME.
"""
from .hostaudio import CoreAudio

DEFAULT_NAME = "Passport Mic"
DEFAULT_UID = "com.ai-passport.aggregate.mic"
SUBDEVICE = "BlackHole 2ch"

# Key names read back from a working device in
# /Library/Preferences/Audio/com.apple.audio.SystemSettings.plist.
KEY_NAME = "name"
KEY_UID = "uid"
KEY_PRIVATE = "private"
KEY_STACKED = "stacked"
KEY_SUBDEVICES = "subdevices"

def description(name, uid, subdevice_uid):
    """Return the CoreAudio description of an aggregate with one subdevice."""
    return {
        KEY_NAME: name,
        KEY_UID: uid,
        # A private device disappears with the process that made it.
        KEY_PRIVATE: False,
        KEY_STACKED: False,
        KEY_SUBDEVICES: [{KEY_UID: subdevice_uid}],
    }

class AggregateHal:
    """Create and remove aggregate devices through the CoreAudio framework."""

    def __init__(self, framework=None):
        if framework is None:
            import CoreAudio as framework
        self.framework = framework

    def create(self, description):
        status, device = self.framework.AudioHardwareCreateAggregateDevice(description, None)
        if status:
            raise RuntimeError(f"CoreAudio refused the aggregate device (status {status})")
        return device

    def destroy(self, device):
        status = self.framework.AudioHardwareDestroyAggregateDevice(device)
        if status:
            raise RuntimeError(f"CoreAudio refused to remove the device (status {status})")

def describe(hal, name=DEFAULT_NAME, subdevice=SUBDEVICE):
    """Return report lines for the devices the bridge needs."""
    lines = []
    for title in (subdevice, name):
        device = hal.find(title)
        lines.append(f"{title}: present (device {device})" if device is not None
                     else f"{title}: missing")
    default = hal.default_input()
    lines.append(f"Default input: {hal.name(default) or default}")
    return lines

def create(hal, aggregates, name=DEFAULT_NAME, uid=DEFAULT_UID, subdevice=SUBDEVICE):
    """Create the aggregate device and return its identifier."""
    if hal.find(name) is not None:
        raise RuntimeError(f"An audio device named {name!r} already exists")
    device = hal.find(subdevice)
    if device is None:
        raise RuntimeError(f"No audio device is named {subdevice!r}; "
                           "install it with: brew install --cask blackhole-2ch")
    subdevice_uid = hal.uid(device)
    if not subdevice_uid:
        raise RuntimeError(f"Cannot read the device identifier of {subdevice!r}")
    return aggregates.create(description(name, uid, subdevice_uid))

def remove(hal, aggregates, name=DEFAULT_NAME):
    """Remove the aggregate device. Only uninstall.sh calls this.

    The check below covers the system default input only. An input method can
    still be configured to use the device, so callers must ask the user first.
    """
    device = hal.find(name)
    if device is None:
        raise RuntimeError(f"No audio device is named {name!r}")
    if device == hal.default_input():
        raise RuntimeError(f"{name} is the system default input; "
                           "select another input device before removing it")
    if hal.uid(device) != DEFAULT_UID:
        raise RuntimeError(f"{name} has a different UID; refusing to remove an unrelated device")
    aggregates.destroy(device)
