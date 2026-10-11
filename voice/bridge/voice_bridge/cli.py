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
from .log import display_value, log, timestamp, persistent_log, StatusLogger
from .automatic import AutoSelector, can_switch_to_usb

MODIFIERS = {"ctrl": 1, "shift": 2, "alt": 4, "cmd": 8}
KEYS = {"space": 0x2c, "enter": 0x28, "escape": 0x29, "tab": 0x2b}
KEYS.update({chr(ord("a") + i): 4 + i for i in range(26)})
KEYS.update({f"f{i}": 0x39 + i for i in range(1, 13)})
DEFAULT_TOKEN = state.directory() / "token"

def shortcut(value):
    parts = value.lower().split("+")
    if not parts or parts[-1] not in KEYS or any(p not in MODIFIERS for p in parts[:-1]):
        raise argparse.ArgumentTypeError("Use a shortcut such as ctrl+alt+space")
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
    link = SerialLink(args.serial) if args.serial else TcpLink(
        args.host, connect_timeout=1 if reconnecting else 3)
    session = Session(link)
    try:
        session.request("hello", token=token, **({"timeout": 8} if args.serial else {}))
        if not args.serial and hasattr(args, "host_file"):
            args.host_file.parent.mkdir(parents=True, exist_ok=True)
            args.host_file.write_text(args.host + "\n")
        return session
    except BaseException:
        try:
            link.close()
        except Exception as error:
            log(f"连接清理失败：{error}", file=sys.stderr)
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
        log("Configuration saved." + (" Set the same shortcut in macOS." if fields else ""))
        if token:
            log(f"Token saved at {args.token_file}. Start passport-voice for automatic connection.")
    finally:
        session.link.close()

class TerminationRequested(KeyboardInterrupt):
    def __init__(self, signum):
        self.signum = signum


class SwitchToUSB(ConnectionError):
    pass


@contextlib.contextmanager
def graceful_termination():
    """Keep terminal hangups from stopping a running bridge; honor stop signals."""
    def interrupt(signum, frame):
        raise TerminationRequested(signum)
    installed = {}
    for name in ("SIGINT", "SIGTERM", "SIGHUP"):
        number = getattr(signal, name, None)
        if number is None:
            continue
        try:
            handler = signal.SIG_IGN if name == "SIGHUP" else interrupt
            installed[number] = signal.signal(number, handler)
        except ValueError:
            pass  # Not the main thread; keep the default handlers.
    try:
        yield
    finally:
        for number, previous in installed.items():
            signal.signal(number, previous)

def run(args):
    """Keep retrying transport failures, with USB preferred in automatic mode."""
    with graceful_termination():
        automatic = getattr(args, "discover", False)
        selector = AutoSelector() if getattr(args, "auto", False) else None
        args._selector = selector
        failures = 0
        waiting_since = None
        disconnected_at = None
        last_error = None

        def connected():
            nonlocal failures, waiting_since, disconnected_at, last_error
            details = ""
            if waiting_since is not None:
                elapsed = time.monotonic() - waiting_since
                details = (f"；等待={elapsed:.1f} s；重试={failures} 次"
                           f"；等待开始={disconnected_at}")
            failures = 0
            waiting_since = disconnected_at = None
            last_error = None
            args._reconnecting = False
            args.discover = automatic
            return details

        while True:
            try:
                if selector:
                    args.serial = selector.usb()
                    args.discover = not args.serial and (not args.host or failures % 2 == 0)
                    if not args.serial:
                        try:
                            read_token(args.token_file)
                        except (RuntimeError, ValueError, OSError) as error:
                            raise ConnectionError(str(error)) from error
                return _run(args, on_connected=connected)
            except SwitchToUSB:
                continue
            except (ConnectionError, TimeoutError, PermissionError) as error:
                if isinstance(error, PermissionError) and not selector:
                    raise
                if selector and args.serial:
                    selector.failed(args.serial)
                if selector and str(error) != last_error:
                    if last_error is None or getattr(args, "verbose", False):
                        log(f"连接暂不可用，继续等待：{error}", file=sys.stderr)
                    last_error = str(error)
                if waiting_since is None:
                    waiting_since = time.monotonic()
                    disconnected_at = timestamp()
                failures += 1
                args._reconnecting = True
                # Use the last address first. Periodic discovery handles DHCP changes.
                if automatic and getattr(args, "host", None):
                    args.discover = failures % 2 == 0
                time.sleep(1)

def idle_heartbeat(status):
    return bool(status and status.get("idle_heartbeat") is True and
                status.get("screen_off") is True and
                all(status.get(key) is False for key in ("mic", "audio", "recording")))


def _run(args, *, on_connected=None):
    from .audio import AudioSink
    sink = None
    session = None
    switcher = None
    verbose = getattr(args, "verbose", False)
    status_logger = StatusLogger(verbose)
    try:
        session = open_session(args)
        initial = session.request("status")
        expected = "usb" if args.serial else "wifi"
        if "auto_transport" in initial:
            try:
                initial = session.request("transport", mode=expected,
                                          automatic=bool(getattr(args, "auto", False)))
                # Pre-selection frames belong to the previous transport.
                # The firmware permits selection only when recording is off.
                session.pending.clear()
            except RuntimeError as error:
                raise ConnectionError(f"Transport selection deferred: {error}") from error
        if initial.get("transport") != expected:
            raise ConnectionError(f"Select {expected} on the device by holding OK; "
                                  "update firmware for automatic transport selection")
        # Reconnect probes must not repeatedly open CoreAudio while the device sleeps.
        sink = AudioSink(args.output)
        switcher = InputSwitcher(args.mic_device) if args.mic_device else None
        injector = Injector()
        session.request("ready", active=True)
        details = on_connected() if on_connected is not None else ""
        address = args.serial if args.serial else getattr(args, "host", "unknown")
        log(f"连接已建立：{expected} {address}{details}", file=sys.stderr)
        if not trusted():
            log("Warning: macOS does not trust this process for Accessibility, so the "
                  "device cannot send the shortcut.", file=sys.stderr)
            log(f"Allow the terminal application, or {sys.executable}, in System Settings > "
                  "Privacy & Security > Accessibility.", file=sys.stderr)
        heartbeat_idle = False
        heartbeat = time.monotonic()
        received = heartbeat
        latest = None
        mic_active = False
        recording_session = None
        usb_checked_at = heartbeat
        while True:
            for frame in session.receive():
                received = time.monotonic()
                if frame.kind == PCM:
                    sink.set_active(True)
                    sink.buffer.push(frame.sequence, frame.payload)
                elif frame.kind == STATUS:
                    status = json.loads(frame.payload)
                    if status.get("event") in ("recording", "key"):
                        keyboard = status.get("event") == "key"
                        event_details = " | ".join(
                            f"{name}={display_value(value)}" for name, value in status.items())
                        if not keyboard and status.get("ending"):
                            if recording_session != status.get("session"):
                                if verbose:
                                    log(f"忽略过期结束快捷键 | {event_details}")
                                continue
                            recording_session = None
                        try:
                            if not trusted():
                                raise RuntimeError("macOS does not trust this process for Accessibility")
                            if not keyboard and switcher and not status.get("ending"):
                                if switcher.set(True) and verbose:
                                    log(f"Default input: {switcher.name}")
                                mic_active = True
                            modifiers, key = status.get("modifiers"), status.get("key")
                            if not keyboard:
                                modifiers, key = getattr(args, "shortcut", None) or (modifiers, key)
                            injector.send(modifiers, key)
                            if not keyboard and not status.get("ending"):
                                recording_session = status.get("session")
                            label = "按键已发送" if keyboard else "快捷键已发送"
                            if verbose:
                                log(f"{label} | {event_details} | 实际修饰键={modifiers} | 实际键码={key}")
                            elif not keyboard:
                                log("录音结束。" if status.get("ending") else "录音开始。")
                        except (RuntimeError, ValueError) as error:
                            log(f"Shortcut not sent: {error} | {event_details}", file=sys.stderr)
                            if not keyboard and not status.get("ending"):
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
                            if switcher.set(desired) and verbose:
                                log(f"Default input: {switcher.name}" if desired
                                    else "Default input restored")
                            mic_active = desired
                        except RuntimeError as error:
                            log(f"Default input unchanged: {error}", file=sys.stderr)
                    status_logger.update(status)
                    latest = status
            now = time.monotonic()
            idle = idle_heartbeat(latest)
            timeout = 15 if idle else 3
            if now - received > timeout:
                raise TimeoutError(f"No device frames for {timeout} seconds")
            if latest and latest.get("audio") and not sink.stream.active:
                raise RuntimeError("Audio output stopped")
            if idle != heartbeat_idle or now - heartbeat >= (5 if idle else 1):
                if latest and latest.get("idle_heartbeat") is True:
                    session.send("ready", active=True, idle=idle)
                else:
                    session.send("ready", active=True)
                heartbeat = now
                heartbeat_idle = idle
            selector = getattr(args, "_selector", None)
            if selector and not args.serial and now - usb_checked_at >= 1:
                usb_checked_at = now
                if can_switch_to_usb(latest, recording_session) and selector.usb():
                    log("录音已停止，切换到 USB。", file=sys.stderr)
                    raise SwitchToUSB
    finally:
        if switcher is not None:
            try:
                switcher.set(False)
            except Exception as error:
                log(f"Default input restore failed: {error}", file=sys.stderr)
        try:
            if session:
                try:
                    session.send("ready", active=False)
                except Exception:
                    pass
                try:
                    session.link.close()
                except Exception as error:
                    log(f"连接清理失败：{error}", file=sys.stderr)
        finally:
            if sink is not None:
                sink.buffer.clear()
                try:
                    sink.close()
                except Exception as error:
                    log(f"音频清理失败：{error}", file=sys.stderr)

def serial_port(explicit):
    """Return the USB serial port, or explain how to choose one."""
    if explicit:
        return explicit
    found = sorted(glob.glob("/dev/cu.usbmodem*"))
    if not found:
        raise SystemExit(f"[{timestamp()}] 没有找到 /dev/cu.usbmodem* 串口。插好数据线，或直接给出串口路径。")
    if len(found) > 1:
        raise SystemExit(f"[{timestamp()}] 找到多个串口，请指定一个：" + " ".join(found))
    return found[0]

def warn_missing_microphone():
    """Warn when the aggregate input device is missing. Never fail the start."""
    try:
        report = microphone.describe(CoreAudio())
    except Exception as exc:
        log(f"警告：无法读取音频设备状态（{exc}）。", file=sys.stderr)
        return
    if not any(line.startswith(f"{microphone.DEFAULT_NAME}: present") for line in report):
        log(f"警告：找不到 {microphone.DEFAULT_NAME} 聚合设备，输入法收不到声音。"
              f"修复：passport-voice setup", file=sys.stderr)

def launch(args):
    """Run a normalized link in this process, including module entry points."""
    warn_missing_microphone()
    args.auto = args.command == "auto"
    if args.auto:
        args.serial = args.host = None
        args.discover = True
        log("自动连接：USB 优先；不可用时等待 Wi-Fi。录音中不主动切换。", file=sys.stderr)
    elif args.command == "usb":
        args.serial = serial_port(args.address)
        args.host = None
        args.discover = False
        log(f"USB 链路：{args.serial}", file=sys.stderr)
        log("打开串口会让设备复位一次，屏幕闪一下属正常现象。", file=sys.stderr)
    else:
        args.serial = None
        args.host = args.address
        args.discover = args.address is None
        if args.host:
            log(f"Wi-Fi 链路：{args.host}", file=sys.stderr)
        else:
            log("正在查找局域网中的 Passport。旧固件需在设备上选择 Wi-Fi 模式。", file=sys.stderr)
    return run(args)


def run_options(parser):
    """Use the same audio, shortcut and state options for every link."""
    parser.add_argument("--host-file", type=Path, default=DEFAULT_TOKEN.with_name("host"),
        help="Saved address to try when discovery times out")
    parser.add_argument("--shortcut", type=shortcut,
        help="Override only the recording shortcut for this run; configure saves it on the device")
    parser.add_argument("--output", default="BlackHole 2ch")
    parser.add_argument("--mic-device", default="Passport Mic",
        help="Input device to select while recording; an empty value keeps the current default")
    parser.add_argument("--token-file", type=Path, default=DEFAULT_TOKEN)
    parser.add_argument("--verbose", action="store_true",
        help="Include full device status and successful key events in terminal and saved logs")

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
    auto = commands.add_parser("auto", help="Automatically connect; prefer USB when idle (default)")
    run_options(auto)
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
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or (argv[0].startswith("--") and argv[0] != "--help"):
        argv.insert(0, "auto")
    args = parser.parse_args(argv)
    if args.command in ("auto", "usb", "wifi", "run"):
        path = state.directory() / "bridge.log"
        with persistent_log(path):
            log(f"桥接启动：PID={os.getpid()}，模式={args.command}，日志={path}", file=sys.stderr)
            return execute(args)
    return execute(args)


def execute(args):
    try:
        if args.command == "devices":
            import sounddevice as sd
            log(sd.query_devices())
        elif args.command == "inputs":
            import sounddevice as sd
            hal = CoreAudio()
            current = hal.name(hal.default_input())
            for device in sd.query_devices():
                if device["max_input_channels"]:
                    log(f"{'*' if device['name'] == current else ' '} {device['name']}")
        elif args.command == "ports":
            from serial.tools import list_ports
            for port in list_ports.comports():
                log(f"{port.device}: {port.description}")
        elif args.command == "microphone":
            hal = CoreAudio()
            if args.create:
                created = microphone.create(hal, microphone.AggregateHal(),
                                            args.name, subdevice=args.subdevice)
                log(f"Created {args.name} (device {created})")
            for line in microphone.describe(hal, args.name, args.subdevice):
                log(line)
        elif args.command == "configure":
            configure(args)
        elif args.command == "setup":
            lifecycle.setup(DEFAULT_TOKEN.parent, args.legacy_state_dir)
        elif args.command == "cleanup":
            if not lifecycle.cleanup(DEFAULT_TOKEN.parent, args.legacy_state_dir, yes=args.yes):
                return 1
        elif args.command in ("auto", "usb", "wifi"):
            launch(args)
        else:
            run(args)
    except TerminationRequested as exc:
        name = signal.Signals(exc.signum).name
        log(f"程序已停止：收到 {name} ({exc.signum})，PID={os.getpid()}。", file=sys.stderr)
        return 0 if exc.signum == signal.SIGINT else 128 + exc.signum
    except KeyboardInterrupt:
        log(f"程序已停止：KeyboardInterrupt（Ctrl+C 或代码中断），PID={os.getpid()}。", file=sys.stderr)
        return 0
    except Exception as exc:
        log(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
