"""Prepare macOS audio and clean up before removing the Python environment."""
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

from . import microphone, state
from .hostaudio import CoreAudio


def require_macos():
    if sys.platform != "darwin":
        raise RuntimeError("This operation requires macOS")


def setup(state_dir, legacy_dir=None):
    require_macos()
    hal = CoreAudio()
    if hal.find(microphone.SUBDEVICE) is None:
        raise RuntimeError("BlackHole 2ch is not loaded. Install it with: "
                           "brew install --cask blackhole-2ch; then load the driver and retry setup")
    device = hal.find(microphone.DEFAULT_NAME)
    if device is not None and hal.uid(device) != microphone.DEFAULT_UID:
        raise RuntimeError("Passport Mic has an unrelated UID; select a different device name")
    state.migrate(state_dir, legacy_dir)
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if device is None:
        microphone.create(hal, microphone.AggregateHal())
    for line in microphone.describe(hal):
        print(line)
    print(f"State directory: {state_dir}")
    print(f"Allow your terminal or {sys.executable} in macOS Accessibility, then restart the bridge.")
    print("Select Passport Mic in your input method. Start with passport-voice usb or wifi.")


def bridge_processes(legacy_dir=None):
    """Return owned and other bridge PIDs. Preserve venv interpreter paths."""
    if legacy_dir is not None:
        legacy_dir = legacy_dir.absolute()
    result = subprocess.run(["ps", "-axo", "pid=,command="],
                            check=True, text=True, capture_output=True)
    owned, other = set(), set()
    scripts = {str(Path(sys.argv[0]).absolute()),
               str(Path(sys.executable).parent / "passport-voice")}
    if legacy_dir is not None:
        scripts.add(str(legacy_dir.parent / "bridge/.venv/bin/passport-voice"))
    mode = r" (?:run|usb|wifi)(?:\s|$)"
    python = r"(/.+?/(?:python[0-9.]*|Python))"
    module_pattern = re.compile(r"^" + python + r" -m voice_bridge\.cli" + mode)
    script_pattern = re.compile(r"^(?:" + python + r" )?(/.+?/passport-voice)" + mode)
    interpreters = {sys.executable}
    if legacy_dir is not None:
        interpreters.add(str(legacy_dir.parent / "bridge/.venv/bin/python"))
    interpreter_dirs = {Path(path).parent for path in interpreters}
    resolved_scripts = {str(Path(path).resolve()) for path in scripts}
    for line in result.stdout.splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) != 2 or not fields[0].isdigit():
            continue
        pid, command = int(fields[0]), fields[1]
        if pid == os.getpid():
            continue
        module = module_pattern.match(command)
        script = script_pattern.match(command)
        if not module and not script:
            continue
        interpreter = (module or script).group(1)
        is_owned = interpreter is not None and Path(interpreter).parent in interpreter_dirs
        if script:
            is_owned = is_owned or str(Path(script.group(2)).resolve()) in resolved_scripts
        target = owned if is_owned else other
        target.add(pid)
    return owned, other


def cleanup(state_dir, legacy_dir=None, *, yes=False):
    require_macos()
    # Queries and ownership checks must pass before any change.
    hal = CoreAudio()
    report = microphone.describe(hal)
    owned, other = bridge_processes(legacy_dir)
    if other:
        raise RuntimeError("Another installation has a running bridge; stop it before cleanup")
    device = hal.find(microphone.DEFAULT_NAME)
    if device is not None:
        if hal.uid(device) != microphone.DEFAULT_UID:
            raise RuntimeError("Passport Mic has an unrelated UID; cleanup stopped")
        if device == hal.default_input() and not owned:
            raise RuntimeError("Passport Mic is the default input; select another input before cleanup")
    print("\n".join(report))
    print(f"Stop this bridge, remove Passport Mic, and delete token/host in {state_dir}.")
    if legacy_dir is not None:
        print(f"Also delete legacy token/host in {legacy_dir}.")
    if not yes and input("Type yes to continue: ") != "yes":
        print("Cancelled; no changes made.")
        return False
    for pid in owned:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 10
    while True:
        running, other = bridge_processes(legacy_dir)
        if other:
            raise RuntimeError("Another bridge started; saved state was retained")
        if not running:
            break
        if time.monotonic() >= deadline:
            raise RuntimeError("Bridge did not stop; saved state was retained")
        time.sleep(0.1)
    # Re-read audio after graceful termination restores the default input.
    hal = CoreAudio()
    if hal.find(microphone.DEFAULT_NAME) is not None:
        microphone.remove(hal, microphone.AggregateHal())
    for folder in {state_dir, legacy_dir} - {None}:
        for name in state.FILES:
            (folder / name).unlink(missing_ok=True)
        try:
            folder.rmdir()
        except OSError:
            pass  # Keep unknown files.
    print("Cleanup complete. BlackHole, Accessibility permissions and device NVS were retained.")
    return True
