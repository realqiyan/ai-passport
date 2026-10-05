#!/usr/bin/env python3
"""Apply the clock sources to the pinned official checkout without losing edits."""
from pathlib import Path
import subprocess
import json
import hashlib

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "source"
PIN = "33d3d1d93a1125b356b47b6d83a7a60121be801e"

def git(*args):
    return subprocess.check_output(["git", "-C", str(SOURCE), *args])

def main():
    if git("rev-parse", "HEAD").decode().strip() != PIN:
        raise SystemExit("Checkout differs from the tested baseline; review before applying.")
    if git("branch", "--show-current").decode().strip() != "feature/offline-clock":
        raise SystemExit("Use the feature/offline-clock branch before applying.")
    state_path = SOURCE / ".git" / "clock-overlay.json"
    previous = json.loads(state_path.read_text()) if state_path.exists() else {}
    changes = {}
    for path in sorted((ROOT / "clock").rglob("*")):
        if path.is_file():
            changes[path.relative_to(ROOT / "clock")] = path.read_bytes()
    defaults = git("show", "HEAD:sdkconfig.defaults").decode()
    defaults = defaults[:defaults.index("# --- Bluetooth LE")]
    defaults += "# --- Offline clock ---\nCONFIG_BT_ENABLED=n\nCONFIG_LV_FONT_MONTSERRAT_48=y\n"
    changes[Path("sdkconfig.defaults")] = defaults.encode()
    gate = git("show", "HEAD:tools/validate.sh").decode()
    marker = '    echo "Host tests: PASS"'
    clock_test = '''    "${CC:-cc}" -std=c11 -Wall -Wextra -Werror -Imain \\
        tests/test_clock_model.c main/clock_model.c \\
        -o "${test_dir}/test_clock_model"
    "${test_dir}/test_clock_model"
'''
    # Keep the test executable inside the temporary directory until it runs.
    gate = gate.replace('    rm -rf "${test_dir}"\n' + marker,
                        clock_test + '    rm -rf "${test_dir}"\n' + marker)
    changes[Path("tools/validate.sh")] = gate.encode()
    for relative, desired in changes.items():
        target = SOURCE / relative
        if not target.exists() or target.read_bytes() == desired:
            continue
        if hashlib.sha256(target.read_bytes()).hexdigest() == previous.get(relative.as_posix()):
            continue
        tracked = subprocess.run(["git", "-C", str(SOURCE), "show", f"HEAD:{relative.as_posix()}"],
                                 capture_output=True)
        if tracked.returncode != 0 or target.read_bytes() != tracked.stdout:
            raise SystemExit(f"Preserved conflicting local changes: {relative}")
    for relative, desired in changes.items():
        target = SOURCE / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(desired)
    state_path.write_text(json.dumps({p.as_posix(): hashlib.sha256(data).hexdigest() for p, data in changes.items()}, indent=2) + "\n")
    print(f"Applied {len(changes)} clock files; BSP and dependency lock unchanged.")

if __name__ == "__main__":
    main()
