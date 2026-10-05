"""Find voice devices without opening a serial port or sending credentials."""
import ipaddress
import re
import secrets
import socket
import subprocess
import sys
import time

PORT = 8765
REQUEST = b"PASSPORT_VOICE_DISCOVER_V1 "
RESPONSE = b"PASSPORT_VOICE_V1 "


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


def discover_host(timeout=3):
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
