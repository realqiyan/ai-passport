#!/usr/bin/env bash
# Compatibility wrapper for the voice bridge.
#
# The bridge entry point is `passport-voice usb|wifi`. This script only forwards
# its arguments, so existing habits and documentation keep working. Both link
# modes, the serial port and the device address are handled by the command.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
voice="$here/bridge/.venv/bin/passport-voice"

[ -x "$voice" ] || {
    printf 'start.sh: 桥接程序未安装。先运行 %s/install.sh\n' "$here" >&2
    exit 1
}

exec "$voice" "$@"
