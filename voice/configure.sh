#!/usr/bin/env bash
# Save the shortcut and optional Wi-Fi configuration over USB.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source "$here/bridge-command.sh"
if [ "${1:-}" = --help ]; then
    printf '用法：configure.sh [串口] --shortcut ctrl+shift+v [--wifi-ssid 网络名]\n先停止 USB 桥接，并关闭麦克风。\n'
    exit 0
fi
[ -n "$voice" ] || { printf '请先运行 %s/install.sh\n' "$here" >&2; exit 1; }
if [ $# -gt 0 ] && [ "${1#-}" = "$1" ]; then
    port="$1"
    shift
else
    ports=()
    for port in /dev/cu.usbmodem*; do
        [ -e "$port" ] && ports+=("$port")
    done
    [ ${#ports[@]} -eq 1 ] || { printf '请指定唯一串口：configure.sh /dev/cu.usbmodem… --shortcut ctrl+shift+v\n' >&2; exit 1; }
    port="${ports[0]}"
fi
[ $# -gt 0 ] || { printf '请提供 --shortcut 或 --wifi-ssid。\n' >&2; exit 2; }
exec "$voice" configure --serial "$port" "$@"
