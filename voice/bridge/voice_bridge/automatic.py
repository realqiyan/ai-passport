"""Select a USB candidate without opening ports during Wi-Fi recording."""
import time


def usb_ports():
    from serial.tools import list_ports
    # ESP32-C3 native USB Serial/JTAG. The protocol handshake still verifies
    # that this is a Passport; never probe unrelated serial adapters.
    return sorted({port.device for port in list_ports.comports()
                   if (port.vid, port.pid) == (0x303a, 0x1001)})


class AutoSelector:
    def __init__(self):
        self.retry_after = {}

    def usb(self):
        try:
            ports = usb_ports()
        except OSError:
            # A transient enumeration failure must not stop an active Wi-Fi link.
            return None
        self.retry_after = {port: deadline for port, deadline in self.retry_after.items()
                            if port in ports}
        if len(ports) > 1:
            # Do not reset an arbitrary board when the choice is ambiguous.
            return None
        if ports and time.monotonic() >= self.retry_after.get(ports[0], 0):
            return ports[0]
        return None

    def failed(self, port):
        # Opening USB can reset the board. Let Wi-Fi recover before retrying.
        self.retry_after[port] = time.monotonic() + 30


def can_switch_to_usb(status, recording_session):
    return bool(status) and recording_session is None and all(
        status.get(field) is False for field in ("mic", "audio", "recording"))
