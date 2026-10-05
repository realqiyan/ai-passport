"""Configure the device and forward PCM to a selected virtual output."""
import argparse
import getpass
import json
import os
from pathlib import Path
import secrets
import sys
import time
from .protocol import COMMAND, PCM, STATUS, Parser, encode
from .transport import SerialLink, TcpLink

MODIFIERS = {"ctrl": 1, "shift": 2, "alt": 4, "cmd": 8}
KEYS = {"space": 0x2c, "enter": 0x28, "escape": 0x29, "tab": 0x2b}
KEYS.update({chr(ord("a") + i): 4 + i for i in range(26)})
KEYS.update({f"f{i}": 0x39 + i for i in range(1, 13)})
DEFAULT_TOKEN = Path(__file__).resolve().parents[2] / ".local" / "token"

def shortcut(value):
    parts = value.lower().split("+")
    if not parts or parts[-1] not in KEYS or any(p not in MODIFIERS for p in parts[:-1]):
        raise argparse.ArgumentTypeError("Use a shortcut such as ctrl+alt+space; Fn needs separate compatibility work")
    modifiers = 0
    for part in parts[:-1]:
        modifiers |= MODIFIERS[part]
    return modifiers, KEYS[parts[-1]]

class Session:
    def __init__(self, link):
        self.link = link
        self.parser = Parser()
        self.sequence = 0
        self.pending = []

    def send(self, op, **fields):
        self.sequence = (self.sequence + 1) & 0xffffffff
        self.link.write(encode(COMMAND, self.sequence,
            json.dumps({"op": op, **fields}, separators=(",", ":")).encode()))
        return self.sequence

    def receive(self):
        if self.pending:
            frames, self.pending = self.pending, []
            return frames
        return self.parser.feed(self.link.read())

    def request(self, op, timeout=3, **fields):
        sequence = self.send(op, **fields)
        deadline = time.monotonic() + timeout
        # Do not consume from pending here: preserve PCM for the run loop.
        while time.monotonic() < deadline:
            reply = None
            for frame in self.parser.feed(self.link.read()):
                if frame.kind == STATUS:
                    status = json.loads(frame.payload)
                    if status.get("result") == "authentication failed":
                        raise PermissionError("Device rejected the token")
                    if status.get("ack") == sequence:
                        if status.get("result") != "ok":
                            raise RuntimeError(status.get("result", "Device rejected the command"))
                        reply = status
                        continue
                self.pending.append(frame)
            if reply is not None:
                return reply
        raise TimeoutError(f"No acknowledgement for {op}")

def read_token(path):
    token = path.read_text().strip()
    if len(token) != 64 or any(c not in "0123456789abcdef" for c in token):
        raise ValueError("Token file must contain 64 hexadecimal characters")
    return token

def save_token(path, token):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic replacement avoids a truncated token after interruption.
    temporary = path.with_name(path.name + ".tmp-" + secrets.token_hex(4))
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w") as output:
            output.write(token + "\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)

def open_session(args):
    link = SerialLink(args.serial) if args.serial else TcpLink(args.host)
    session = Session(link)
    try:
        token = read_token(args.token_file) if args.host else ""
        session.request("hello", token=token)
        return session
    except BaseException:
        link.close()
        raise

def configure(args):
    session = open_session(args)
    try:
        modifier, key = args.shortcut
        fields = {"modifiers": modifier, "key": key}
        token = None
        if args.wifi_ssid is not None:
            if not 1 <= len(args.wifi_ssid.encode()) <= 32:
                raise ValueError("SSID must contain 1 to 32 UTF-8 bytes")
            password = getpass.getpass("Wi-Fi password (not displayed): ")
            if not 8 <= len(password.encode()) <= 64 or (len(password.encode()) == 64 and any(c not in "0123456789abcdefABCDEF" for c in password)):
                raise ValueError("Use 8 to 63 password bytes, or a 64-digit hexadecimal PSK")
            token = read_token(args.token_file) if args.token_file.exists() else secrets.token_hex(32)
            # Save before device configuration, so a lost acknowledgement cannot lose the token.
            save_token(args.token_file, token)
            fields.update(ssid=args.wifi_ssid, password=password, token=token)
        session.request("configure", **fields)
        print("Configuration saved. Set the same shortcut in macOS.")
        if token:
            print(f"Token saved at {args.token_file}. Stop the microphone, then press DOWN for Wi-Fi.")
    finally:
        session.link.close()

def run(args):
    from .audio import AudioSink
    sink = AudioSink(args.output)
    session = None
    try:
        sink.start()
        session = open_session(args)
        initial = session.request("status")
        expected = "usb" if args.serial else "wifi"
        if initial.get("transport") != expected:
            raise RuntimeError(f"Select {expected} on the device with DOWN before running the bridge")
        session.request("ready", active=True)
        print("Audio output ready. Press UP to enable the microphone, then OK for the shortcut.")
        heartbeat = time.monotonic()
        received = heartbeat
        latest = None
        while True:
            for frame in session.receive():
                received = time.monotonic()
                if frame.kind == PCM:
                    sink.buffer.push(frame.sequence, frame.payload)
                elif frame.kind == STATUS:
                    status = json.loads(frame.payload)
                    if (status.get("rate"), status.get("channels"), status.get("bits")) != (16000, 1, 16):
                        raise ValueError("Device audio format differs from the bridge format")
                    if status.get("transport") != expected:
                        raise ConnectionError("Device changed audio transport")
                    if not status.get("audio"):
                        sink.buffer.clear()
                    brief = {k: status.get(k) for k in ("mic", "audio", "bridge", "hid", "error", "drops")}
                    if brief != latest:
                        print(json.dumps(brief), flush=True)
                        latest = brief
            now = time.monotonic()
            if now - received > 3:
                raise TimeoutError("No device frames for 3 seconds")
            if not sink.stream.active:
                raise RuntimeError("Audio output stopped")
            if now - heartbeat >= 1:
                session.send("ready", active=True)
                heartbeat = now
    finally:
        if session:
            try:
                session.send("ready", active=False)
            except Exception:
                pass
            session.link.close()
        sink.buffer.clear()
        sink.close()

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("devices", help="List audio outputs")
    commands.add_parser("ports", help="List serial ports without opening them")
    config = commands.add_parser("configure", help="Save shortcut and optional Wi-Fi credentials over USB")
    config.add_argument("--serial", required=True)
    config.add_argument("--wifi-ssid")
    config.add_argument("--shortcut", type=shortcut, default=shortcut("ctrl+alt+space"))
    config.add_argument("--token-file", type=Path, default=DEFAULT_TOKEN)
    config.set_defaults(host=None)
    bridge = commands.add_parser("run", help="Receive audio and play it into the selected virtual output")
    transport = bridge.add_mutually_exclusive_group(required=True)
    transport.add_argument("--serial")
    transport.add_argument("--host")
    bridge.add_argument("--output", default="BlackHole 2ch")
    bridge.add_argument("--token-file", type=Path, default=DEFAULT_TOKEN)
    args = parser.parse_args(argv)
    try:
        if args.command == "devices":
            import sounddevice as sd
            print(sd.query_devices())
        elif args.command == "ports":
            from serial.tools import list_ports
            for port in list_ports.comports():
                print(f"{port.device}: {port.description}")
        elif args.command == "configure":
            configure(args)
        else:
            run(args)
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
