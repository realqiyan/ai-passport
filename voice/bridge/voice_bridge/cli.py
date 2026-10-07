"""Configure the device and forward PCM to a selected virtual output."""
import argparse
import contextlib
import getpass
import glob
import json
import os
from pathlib import Path
import secrets
import signal
import sys
import time
from . import lifecycle, microphone, state
from .hostaudio import CoreAudio, InputSwitcher
from .protocol import COMMAND, PCM, STATUS, Parser, encode
from .shortcut import Injector, trusted
from .transport import SerialLink, TcpLink
from .discovery import discover_host

MODIFIERS = {"ctrl": 1, "shift": 2, "alt": 4, "cmd": 8}
KEYS = {"space": 0x2c, "enter": 0x28, "escape": 0x29, "tab": 0x2b}
KEYS.update({chr(ord("a") + i): 4 + i for i in range(26)})
KEYS.update({f"f{i}": 0x39 + i for i in range(1, 13)})
DEFAULT_TOKEN = state.directory() / "token"

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
    try:
        token = path.read_text().strip()
    except FileNotFoundError:
        raise RuntimeError(
            f"Wi-Fi token is missing: {path}. Connect the device by USB, stop the USB bridge, "
            "turn the microphone off, then run passport-voice configure --serial <serial> --wifi-ssid <network>. "
            "This creates and saves the token on both the Mac and the device. "
            "If you have the matching token elsewhere, use --token-file <path>."
        ) from None
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
    # Check local credentials before discovery or opening the device connection.
    token = "" if args.serial else read_token(args.token_file)
    reconnecting = getattr(args, "_reconnecting", False)
    if getattr(args, "discover", False):
        try:
            args.host = discover_host(timeout=1 if reconnecting else 3)
        except TimeoutError:
            if not args.host_file.is_file() or not args.host_file.read_text().strip():
                raise
            args.host = args.host_file.read_text().strip()
            print(f"Discovery timed out; trying saved address {args.host}.", file=sys.stderr)
        print(f"Wi-Fi device: {args.host}", file=sys.stderr)
    link = SerialLink(args.serial) if args.serial else TcpLink(
        args.host, connect_timeout=1 if reconnecting else 3)
    session = Session(link)
    try:
        session.request("hello", token=token)
        if not args.serial and hasattr(args, "host_file"):
            args.host_file.parent.mkdir(parents=True, exist_ok=True)
            args.host_file.write_text(args.host + "\n")
        return session
    except BaseException:
        link.close()
        raise

def configure(args):
    session = open_session(args)
    try:
        # Omit the shortcut unless it was given, so configuring Wi-Fi cannot
        # silently replace the shortcut the device already uses.
        fields = {}
        if args.shortcut:
            modifier, key = args.shortcut
            fields.update(modifiers=modifier, key=key)
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
        print("Configuration saved." + (" Set the same shortcut in macOS." if fields else ""))
        if token:
            print(f"Token saved at {args.token_file}. Stop the microphone, then press DOWN for Wi-Fi.")
    finally:
        session.link.close()

@contextlib.contextmanager
def graceful_termination():
    """Turn SIGTERM and SIGHUP into KeyboardInterrupt, so cleanup blocks run.

    Without this, a killed bridge would leave the system default input device
    pointing at the microphone.
    """
    def interrupt(signum, frame):
        raise KeyboardInterrupt
    installed = {}
    for name in ("SIGTERM", "SIGHUP"):
        number = getattr(signal, name, None)
        if number is None:
            continue
        try:
            installed[number] = signal.signal(number, interrupt)
        except ValueError:
            pass  # Not the main thread; keep the default handlers.
    try:
        yield
    finally:
        for number, previous in installed.items():
            signal.signal(number, previous)

def run(args):
    """Run the bridge. SIGTERM and SIGHUP run the same cleanup as Ctrl-C."""
    with graceful_termination():
        automatic = getattr(args, "discover", False)
        failures = 0
        while True:
            try:
                return _run(args)
            except PermissionError:
                raise
            except (ConnectionError, TimeoutError):
                if args.serial:
                    raise
                if failures == 0:
                    print("Wi-Fi disconnected. Waiting for the device; press UP to wake it.",
                          file=sys.stderr, flush=True)
                failures += 1
                args._reconnecting = True
                # Use the last address first. Periodic discovery handles DHCP changes.
                if automatic and getattr(args, "host", None):
                    args.discover = failures % 2 == 0
                time.sleep(1)

def _run(args):
    from .audio import AudioSink
    sink = None
    session = None
    switcher = None
    try:
        session = open_session(args)
        initial = session.request("status")
        expected = "usb" if args.serial else "wifi"
        if initial.get("transport") != expected:
            raise RuntimeError(f"Select {expected} on the device with DOWN before running the bridge")
        # Reconnect probes must not repeatedly open CoreAudio while the device sleeps.
        sink = AudioSink(args.output)
        switcher = InputSwitcher(args.mic_device) if args.mic_device else None
        injector = Injector()
        if not trusted():
            print("Warning: macOS does not trust this process for Accessibility, so the "
                  "device cannot send the shortcut.", file=sys.stderr)
            print(f"Allow the terminal application, or {sys.executable}, in System Settings > "
                  "Privacy & Security > Accessibility.", file=sys.stderr)
        session.request("ready", active=True)
        print("Audio output ready. Press OK for temporary input, then OK again to stop. UP keeps the microphone on.")
        heartbeat = time.monotonic()
        received = heartbeat
        latest = None
        mic_active = False
        temporary_session = None
        while True:
            for frame in session.receive():
                received = time.monotonic()
                if frame.kind == PCM:
                    sink.set_active(True)
                    sink.buffer.push(frame.sequence, frame.payload)
                elif frame.kind == STATUS:
                    status = json.loads(frame.payload)
                    if status.get("event") == "shortcut":
                        if status.get("temporary") and status.get("ending"):
                            if temporary_session != status.get("session"):
                                continue
                            temporary_session = None
                        try:
                            if not trusted():
                                raise RuntimeError("macOS does not trust this process for Accessibility")
                            if switcher and not status.get("ending"):
                                if switcher.set(True):
                                    print(f"Default input: {switcher.name}", flush=True)
                                mic_active = True
                            modifiers, key = getattr(args, "shortcut", None) or (
                                status.get("modifiers"), status.get("key"))
                            injector.send(modifiers, key)
                            if status.get("temporary") and not status.get("ending"):
                                temporary_session = status.get("session")
                            print("Shortcut sent", flush=True)
                        except (RuntimeError, ValueError) as error:
                            print(f"Shortcut not sent: {error}", file=sys.stderr, flush=True)
                            if status.get("temporary") and not status.get("ending"):
                                session.send("stop", session=status.get("session"))
                        continue
                    if (status.get("rate"), status.get("channels"), status.get("bits")) != (16000, 1, 16):
                        raise ValueError("Device audio format differs from the bridge format")
                    if status.get("transport") != expected:
                        raise ConnectionError("Device changed audio transport")
                    sink.set_active(bool(status.get("audio")))
                    if switcher and bool(status.get("mic")) != mic_active:
                        desired = bool(status.get("mic"))
                        try:
                            if switcher.set(desired):
                                print(f"Default input: {switcher.name}" if desired
                                      else "Default input restored", flush=True)
                            mic_active = desired
                        except RuntimeError as error:
                            print(f"Default input unchanged: {error}", file=sys.stderr, flush=True)
                    brief = {k: status.get(k) for k in (
                        "mic", "audio", "bridge", "error", "drops", "power_profile",
                        "battery_pct", "battery_mv", "screen_off", "codec_asleep",
                        "usb_host", "deep_wakes", "sleep_error")}
                    if brief != latest:
                        print(json.dumps(brief), flush=True)
                        latest = brief
            now = time.monotonic()
            if now - received > 3:
                raise TimeoutError("No device frames for 3 seconds")
            if latest and latest.get("audio") and not sink.stream.active:
                raise RuntimeError("Audio output stopped")
            if now - heartbeat >= 1:
                session.send("ready", active=True)
                heartbeat = now
    finally:
        if switcher is not None:
            try:
                switcher.set(False)
            except Exception as error:
                print(f"Default input restore failed: {error}", file=sys.stderr)
        try:
            if session:
                try:
                    session.send("ready", active=False)
                except Exception:
                    pass
                session.link.close()
        finally:
            if sink is not None:
                sink.buffer.clear()
                sink.close()

def serial_port(explicit):
    """Return the USB serial port, or explain how to choose one."""
    if explicit:
        return explicit
    found = sorted(glob.glob("/dev/cu.usbmodem*"))
    if not found:
        raise SystemExit("没有找到 /dev/cu.usbmodem* 串口。插好数据线，或直接给出串口路径。")
    if len(found) > 1:
        raise SystemExit("找到多个串口，请指定一个：" + " ".join(found))
    return found[0]

def warn_missing_microphone():
    """Warn when the aggregate input device is missing. Never fail the start."""
    try:
        report = microphone.describe(CoreAudio())
    except Exception as exc:
        print(f"警告：无法读取音频设备状态（{exc}）。", file=sys.stderr)
        return
    if not any(line.startswith(f"{microphone.DEFAULT_NAME}: present") for line in report):
        print(f"警告：找不到 {microphone.DEFAULT_NAME} 聚合设备，输入法收不到声音。"
              f"修复：passport-voice setup", file=sys.stderr)

def launch(args):
    """Run a normalized link in this process, including module entry points."""
    warn_missing_microphone()
    if args.command == "usb":
        args.serial = serial_port(args.address)
        args.host = None
        args.discover = False
        print(f"USB 链路：{args.serial}", file=sys.stderr)
        print("打开串口会让设备复位一次，屏幕闪一下属正常现象。", file=sys.stderr)
    else:
        args.serial = None
        args.host = args.address
        args.discover = args.address is None
        if args.host:
            print(f"Wi-Fi 链路：{args.host}", file=sys.stderr)
        else:
            print("正在查找局域网中的 Passport，请先在设备上选择 Wi-Fi 模式。", file=sys.stderr)
    return run(args)


def run_options(parser):
    """Use the same audio, shortcut and state options for every link."""
    parser.add_argument("--host-file", type=Path, default=DEFAULT_TOKEN.with_name("host"),
        help="Saved address to try when discovery times out")
    parser.add_argument("--shortcut", type=shortcut,
        help="Override the shortcut for this run; configure saves it on the device")
    parser.add_argument("--output", default="BlackHole 2ch")
    parser.add_argument("--mic-device", default="Passport Mic",
        help="Input device to select while recording; an empty value keeps the current default")
    parser.add_argument("--token-file", type=Path, default=DEFAULT_TOKEN)

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("devices", help="List audio outputs")
    commands.add_parser("inputs", help="List audio inputs; the system default is marked")
    commands.add_parser("ports", help="List serial ports without opening them")
    mic = commands.add_parser("microphone",
        help="Report the aggregate input device that the voice input method records from")
    mic.add_argument("--create", action="store_true", help="Create the device when it is missing")
    mic.add_argument("--name", default=microphone.DEFAULT_NAME)
    mic.add_argument("--subdevice", default=microphone.SUBDEVICE)
    config = commands.add_parser("configure", help="Save shortcut and optional Wi-Fi credentials over USB")
    config.add_argument("--serial", required=True)
    config.add_argument("--wifi-ssid")
    config.add_argument("--shortcut", type=shortcut,
        help="Shortcut the device asks the bridge to press; the device keeps its current shortcut when omitted")
    config.add_argument("--token-file", type=Path, default=DEFAULT_TOKEN)
    config.set_defaults(host=None)
    bridge = commands.add_parser("run", help="Receive audio and play it into the selected virtual output")
    transport = bridge.add_mutually_exclusive_group(required=True)
    transport.add_argument("--serial")
    transport.add_argument("--host")
    transport.add_argument("--discover", action="store_true", help="Find a device on the local network")
    run_options(bridge)
    for name, help_text in (
            ("usb", "Start USB; omit the port when there is one device"),
            ("wifi", "Start Wi-Fi; omit the address to discover a device")):
        link = commands.add_parser(name, help=help_text)
        link.add_argument("address", nargs="?", help="Serial port or Wi-Fi address")
        run_options(link)
    setup = commands.add_parser("setup", help="Check BlackHole, prepare the input and migrate legacy state")
    setup.add_argument("--legacy-state-dir", type=Path, default=state.legacy_directory())
    cleanup = commands.add_parser("cleanup", help="Stop this bridge and remove its input and saved state")
    cleanup.add_argument("--yes", action="store_true", help="Skip the cleanup confirmation")
    cleanup.add_argument("--legacy-state-dir", type=Path, default=state.legacy_directory())
    args = parser.parse_args(argv)
    try:
        if args.command == "devices":
            import sounddevice as sd
            print(sd.query_devices())
        elif args.command == "inputs":
            import sounddevice as sd
            hal = CoreAudio()
            current = hal.name(hal.default_input())
            for device in sd.query_devices():
                if device["max_input_channels"]:
                    print(f"{'*' if device['name'] == current else ' '} {device['name']}")
        elif args.command == "ports":
            from serial.tools import list_ports
            for port in list_ports.comports():
                print(f"{port.device}: {port.description}")
        elif args.command == "microphone":
            hal = CoreAudio()
            if args.create:
                created = microphone.create(hal, microphone.AggregateHal(),
                                            args.name, subdevice=args.subdevice)
                print(f"Created {args.name} (device {created})")
            for line in microphone.describe(hal, args.name, args.subdevice):
                print(line)
        elif args.command == "configure":
            configure(args)
        elif args.command == "setup":
            lifecycle.setup(DEFAULT_TOKEN.parent, args.legacy_state_dir)
        elif args.command == "cleanup":
            if not lifecycle.cleanup(DEFAULT_TOKEN.parent, args.legacy_state_dir, yes=args.yes):
                return 1
        elif args.command in ("usb", "wifi"):
            launch(args)
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
