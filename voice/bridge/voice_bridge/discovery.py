"""Find voice devices without opening a serial port or sending credentials."""
import ipaddress
import re
import secrets
import socket
import subprocess
import sys
import threading
import time

PORT = 8765
REQUEST = b"PASSPORT_VOICE_DISCOVER_V1 "
RESPONSE = b"PASSPORT_VOICE_V1 "
ANNOUNCE = b"PASSPORT_VOICE_ANNOUNCE_V1"
# One boot repeats its announcement three times, 200 ms apart. A longer gap
# means the device booted again, which invalidates any open session.
ANNOUNCE_BOOT_WINDOW = 2.0


def broadcast_addresses():
    addresses = {"255.255.255.255"}
    if sys.platform == "darwin":
        # Include every IPv4 interface, so a VPN route cannot hide Wi-Fi.
        try:
            result = subprocess.run(["/sbin/ifconfig"], capture_output=True,
                                    text=True, timeout=2, check=True)
            for value in re.findall(r"\bbroadcast\s+(\d+\.\d+\.\d+\.\d+)", result.stdout):
                addresses.add(str(ipaddress.IPv4Address(value)))
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
    return sorted(addresses)


def discover_host(timeout=3, announced=None):
    """Find voice devices without opening a serial port or sending credentials.

    A device that announced itself is already online and carries its own address,
    so a reconnect can use it without listening for the whole window.
    """
    nonce = secrets.token_hex(16).encode("ascii")
    expected = RESPONSE + nonce
    targets = broadcast_addresses()
    hosts = set()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as channel:
        channel.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        channel.bind(("0.0.0.0", 0))
        deadline = time.monotonic() + timeout
        next_send = 0
        while time.monotonic() < deadline:
            if announced is not None and announced.host and announced.event.is_set():
                return announced.host
            now = time.monotonic()
            if now >= next_send:
                for address in targets:
                    try:
                        channel.sendto(REQUEST + nonce, (address, PORT))
                    except OSError:
                        continue
                next_send = now + 0.5
            channel.settimeout(max(0.001, min(0.2, deadline - now)))
            try:
                packet, (host, port) = channel.recvfrom(256)
            except socket.timeout:
                continue
            if port == PORT and packet == expected:
                hosts.add(host)
    if not hosts:
        raise TimeoutError("No Passport found. Select Wi-Fi on the device and use the same LAN. "
                           "Update the device firmware or run start.sh wifi <IP>.")
    if len(hosts) > 1:
        raise RuntimeError("Multiple Passports found; run start.sh wifi <IP>: " + ", ".join(sorted(hosts)))
    return hosts.pop()


class AnnounceListener:
    """Hear a device announce itself online instead of polling for it."""

    def __init__(self):
        self.host = None
        self.event = threading.Event()
        self.generation = 0
        self._announced_at = 0.0
        self._closed = False
        self._channel = None
        self._thread = None
        try:
            channel = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        except OSError:
            return
        try:
            channel.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            channel.bind(("", PORT))
            channel.settimeout(0.5)
        except OSError:
            channel.close()
            return
        self._channel = channel
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    @property
    def active(self):
        return self._channel is not None

    @property
    def announced_at(self):
        """Monotonic time of the last announcement, or zero before the first."""
        return self._announced_at

    def _serve(self):
        channel = self._channel
        while not self._closed:
            try:
                packet, (host, port) = channel.recvfrom(256)
            except socket.timeout:
                continue
            except OSError:
                return
            if packet == ANNOUNCE and port == PORT:
                now = time.monotonic()
                if now - self._announced_at > ANNOUNCE_BOOT_WINDOW:
                    self.generation += 1
                self._announced_at = now
                self.host = host
                self.event.set()

    def close(self):
        self._closed = True
        if self._channel is not None:
            self._channel.close()
            self._channel = None
        if self._thread is not None:
            self._thread.join(timeout=2)
