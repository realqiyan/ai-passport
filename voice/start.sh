#!/usr/bin/env bash
# Start the Mac bridge for the AI Passport voice application.
#
# The bridge runs in the foreground. Stop it with Control-C; the default input
# device is restored on the way out.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
voice="$here/bridge/.venv/bin/passport-voice"
remembered="$here/.local/host"

usage() {
    cat <<'TXT'
用法：
  start.sh usb  [串口]   [桥接选项]    有线链路
  start.sh wifi [设备IP] [桥接选项]    无线链路

串口和设备 IP 可以省略：
  usb   只有一个 /dev/cu.usbmodem* 时自动使用
  wifi  沿用上次记住的设备 IP

桥接选项原样传给 `passport-voice run`，例如 --output 'BlackHole 2ch'
或 --mic-device ''（不改动系统默认输入）。
TXT
}

die() { printf 'start.sh: %s\n' "$1" >&2; exit 1; }

# Print the first argument when it is a value rather than an option.
address() {
    if [ $# -gt 0 ] && [ "${1#-}" = "$1" ]; then
        printf '%s' "$1"
    fi
}

[ -x "$voice" ] || die "桥接程序未安装。先运行 $here/install.sh"
[ $# -ge 1 ] || { usage; exit 2; }

mode="$1"
shift

"$voice" microphone 2>/dev/null | grep -q '^Passport Mic: present' \
    || printf 'start.sh: 警告：找不到 Passport Mic 聚合设备，输入法收不到声音。修复：%s microphone --create\n' \
        "$voice" >&2

case "$mode" in
usb)
    port="$(address "$@")"
    if [ -n "$port" ]; then
        shift
    else
        found=()
        for candidate in /dev/cu.usbmodem*; do
            [ -e "$candidate" ] && found+=("$candidate")
        done
        [ ${#found[@]} -gt 0 ] || die "没有找到 /dev/cu.usbmodem* 串口。插好数据线，或直接给出串口路径。"
        [ ${#found[@]} -eq 1 ] || die "找到多个串口，请指定一个：${found[*]}"
        port="${found[0]}"
    fi
    printf 'USB 链路：%s\n' "$port" >&2
    printf '打开串口会让设备复位一次，屏幕闪一下属正常现象。\n' >&2
    exec "$voice" run --serial "$port" "$@"
    ;;
wifi)
    host="$(address "$@")"
    if [ -n "$host" ]; then
        shift
    elif [ -r "$remembered" ]; then
        host="$(cat "$remembered")"
    fi
    [ -n "$host" ] || die "请给出设备 IP，例如：$here/start.sh wifi 192.0.2.2"
    mkdir -p "$(dirname "$remembered")"
    printf '%s\n' "$host" >"$remembered"
    printf 'Wi-Fi 链路：%s\n' "$host" >&2
    exec "$voice" run --host "$host" "$@"
    ;;
-h | --help | help)
    usage
    ;;
*)
    printf 'start.sh: 未知模式 %s\n\n' "$mode" >&2
    usage >&2
    exit 2
    ;;
esac
