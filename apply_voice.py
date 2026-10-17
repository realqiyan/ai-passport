#!/usr/bin/env python3
"""Apply the voice application to a separate official worktree."""
from pathlib import Path
import argparse
import subprocess
import hashlib
import json
BASELINE = "33d3d1d93a1125b356b47b6d83a7a60121be801e"
ROOT = Path(__file__).resolve().parent

def digest(data):
    return hashlib.sha256(data).hexdigest()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, default=ROOT / "voice-source")
    args = parser.parse_args()
    target = args.target.resolve()
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=target, text=True).strip()
    if base != BASELINE:
        raise SystemExit("Target HEAD differs from the supported baseline")
    sources = ROOT / "voice" / "firmware"
    files = {str(p.relative_to(sources)): p.read_bytes() for p in sources.rglob("*") if p.is_file()}
    defaults = subprocess.check_output(["git", "show", f"{BASELINE}:sdkconfig.defaults"], cwd=target).decode()
    defaults += "\n# Voice application\nCONFIG_LOG_DEFAULT_LEVEL_NONE=y\nCONFIG_LOG_MAXIMUM_LEVEL=0\n"
    defaults += "CONFIG_PM_ENABLE=y\nCONFIG_FREERTOS_USE_TICKLESS_IDLE=y\n"
    defaults += "CONFIG_USJ_NO_AUTO_LS_ON_CONNECTION=y\nCONFIG_BUTTON_PERIOD_TIME_MS=20\n"
    defaults += "CONFIG_ESP_SLEEP_GPIO_ENABLE_INTERNAL_RESISTORS=n\n"
    defaults += "CONFIG_BT_ENABLED=n\nCONFIG_BT_NIMBLE_ENABLED=n\n"
    # Ask for the last address before a full DHCP cycle so a waking device
    # is reachable in a fraction of the time, and bind it without the ARP
    # conflict check: the check costs 1-2 s on every wake, while a conflict
    # on this single-device LAN only needs a restart. ESP-IDF makes the
    # offered-address check a three-way choice, so select "no check".
    defaults += "CONFIG_LWIP_DHCP_RESTORE_LAST_IP=y\n"
    defaults += "CONFIG_LWIP_DHCP_DOES_NOT_CHECK_OFFERED_IP=y\n"
    files["sdkconfig.defaults"] = defaults.encode()
    display = subprocess.check_output(
        ["git", "show", f"{BASELINE}:components/bsp/src/bsp_display.c"], cwd=target).decode()
    files["components/bsp/src/bsp_display.c"] = display.replace(
        "LEDC_AUTO_CLK", "LEDC_USE_XTAL_CLK").encode()
    bsp_cmake = subprocess.check_output(
        ["git", "show", f"{BASELINE}:components/bsp/CMakeLists.txt"], cwd=target).decode()
    files["components/bsp/CMakeLists.txt"] = bsp_cmake.replace(
        '"src/bsp_display.c"', '"src/bsp_display.c"\n         "src/bsp_display_power.c"').encode()
    gate = subprocess.check_output(["git", "show", f"{BASELINE}:tools/validate.sh"], cwd=target).decode()
    addition = '''    "${CC:-cc}" -std=c11 -Wall -Wextra -Werror -Imain \\
        tests/test_voice_protocol.c main/voice_protocol.c main/voice_model.c \\
        -o "${test_dir}/test_voice_protocol"
    "${test_dir}/test_voice_protocol"
    "${CC:-cc}" -std=c11 -Wall -Wextra -Werror \\
        -Itests/sleep_stubs -Itests/demo_stubs -Icomponents/bsp/include -Imain \\
        tests/test_voice_controls.c main/voice_controls.c -o "${test_dir}/test_voice_controls"
    "${test_dir}/test_voice_controls"
    "${CC:-cc}" -std=c11 -Wall -Wextra -Werror \\
        -Itests/bsp_stubs -Itests/power_stubs -Icomponents/bsp/include \\
        tests/test_voice_display_power.c components/bsp/src/bsp_display_power.c \\
        -o "${test_dir}/test_voice_display_power"
    "${test_dir}/test_voice_display_power"
    "${CC:-cc}" -std=c11 -Wall -Wextra -Werror \\
        -Itests/sleep_stubs -Itests/power_stubs -Itests/demo_stubs -Itests/bsp_stubs -Icomponents/bsp/include -Imain \\
        -include tests/power_stubs/voice_sleep_test_stubs.h \\
        tests/test_voice_power.c main/voice_power.c -o "${test_dir}/test_voice_power"
    "${test_dir}/test_voice_power"
'''
    gate = gate.replace('    rm -rf "${test_dir}"', addition + '    rm -rf "${test_dir}"')
    gate = gate.replace('mktemp -d /tmp/ai-passport-firmware.XXXXXX',
                        'mktemp -d "${TMPDIR:-/tmp}/ai-passport-firmware.XXXXXX"')
    gate = gate.replace('in /tmp/ai-passport-firmware.*)',
                        'in "${TMPDIR:-/tmp}"/ai-passport-firmware.*)')
    gate = gate.replace('"${CC:-cc}"', 'host_cc')
    marker = 'set -euo pipefail'
    wrapper = """
# Darwin ld uses dead_strip instead of GNU gc-sections.
host_cc() {
    local args=() arg
    for arg in "$@"; do
        if [ "$(uname -s)" = Darwin ] && [ "$arg" = '-Wl,--gc-sections' ]; then
            args+=("-Wl,-dead_strip")
        else
            args+=("$arg")
        fi
    done
    "${CC:-cc}" "${args[@]}"
}
"""
    gate = gate.replace(marker, marker + "\n" + wrapper)
    files["tools/validate.sh"] = gate.encode()
    state = target / ".voice-applied.json"
    previous = json.loads(state.read_text()) if state.exists() else {}
    for rel, data in files.items():
        dest = target / rel
        if not dest.exists():
            continue
        current = dest.read_bytes()
        try:
            original = subprocess.check_output(["git", "show", f"{BASELINE}:{rel}"], cwd=target, stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            original = None
        if current != data and current != original and digest(current) != previous.get(rel):
            raise SystemExit(f"Preserve changed target file: {rel}")
    for rel, data in files.items():
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    state.write_text(json.dumps({rel: digest(data) for rel, data in files.items()}, indent=2) + "\n")
    print(f"Applied {len(files)} voice files to {target}")

if __name__ == "__main__":
    main()
