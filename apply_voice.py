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
    defaults = defaults.replace("CONFIG_BT_NIMBLE_NVS_PERSIST=n", "CONFIG_BT_NIMBLE_NVS_PERSIST=y")
    defaults += "\n# Voice application\nCONFIG_LOG_DEFAULT_LEVEL_NONE=y\nCONFIG_LOG_MAXIMUM_LEVEL=0\nCONFIG_BT_NIMBLE_SM_SC=y\n"
    files["sdkconfig.defaults"] = defaults.encode()
    gate = subprocess.check_output(["git", "show", f"{BASELINE}:tools/validate.sh"], cwd=target).decode()
    addition = '''    "${CC:-cc}" -std=c11 -Wall -Wextra -Werror -Imain \\
        tests/test_voice_protocol.c main/voice_protocol.c main/voice_model.c \\
        -o "${test_dir}/test_voice_protocol"
    "${test_dir}/test_voice_protocol"
'''
    gate = gate.replace('    rm -rf "${test_dir}"', addition + '    rm -rf "${test_dir}"')
    gate = gate.replace('mktemp -d /tmp/ai-passport-firmware.XXXXXX',
                        'mktemp -d "${TMPDIR:-/tmp}/ai-passport-firmware.XXXXXX"')
    gate = gate.replace('in /tmp/ai-passport-firmware.*)',
                        'in "${TMPDIR:-/tmp}"/ai-passport-firmware.*)')
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
