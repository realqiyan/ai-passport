#!/usr/bin/env bash
# Remove the Mac side of the AI Passport voice application.
#
# This script reverses install.sh. It does not touch BlackHole 2ch, the system
# dictation settings, the input method, or the device firmware.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bridge="$here/bridge"
venv="$bridge/.venv"
voice="$venv/bin/passport-voice"
state="$here/.local"

step() { printf '\n== %s\n' "$1"; }
note() { printf '   %s\n' "$1"; }
die() { printf '\nuninstall.sh: %s\n' "$1" >&2; exit 1; }

[ "$(uname -s)" = "Darwin" ] || die "此脚本只在 macOS 上运行。"

assume_yes=0
if [ $# -gt 0 ]; then
    [ "$1" = "--yes" ] || die "未知参数 $1。用法：uninstall.sh [--yes]"
    assume_yes=1
fi

step "检查"
if [ -x "$voice" ] && [ "$("$voice" microphone | sed -n 's/^Default input: //p')" = "Passport Mic" ]; then
    die "系统默认输入仍是 Passport Mic，此时删除会让输入法失去麦克风。
先在“系统设置 → 声音 → 输入”里选别的设备，再运行本脚本。"
fi
# The bracket keeps this pattern from matching the check itself.
if pgrep -f '[p]assport-voice run' >/dev/null 2>&1; then
    note "有桥接正在运行，将被停止"
else
    note "没有正在运行的桥接"
fi

step "将要执行"
cat <<TXT
   停止正在运行的桥接，并还原系统默认输入
   删除聚合音频设备 Passport Mic
   删除 Wi-Fi 令牌与本地状态 $state
   删除虚拟环境 $venv
TXT

if [ "$assume_yes" -eq 0 ]; then
    printf '\n继续请输入 yes：'
    read -r answer
    [ "$answer" = "yes" ] || { printf '已取消，未做任何改动。\n'; exit 0; }
fi

step "停止桥接"
if pgrep -f '[p]assport-voice run' >/dev/null 2>&1; then
    pkill -TERM -f '[p]assport-voice run'
    for _ in $(seq 1 20); do
        pgrep -f '[p]assport-voice run' >/dev/null 2>&1 || break
        sleep 0.5
    done
    pgrep -f '[p]assport-voice run' >/dev/null 2>&1 \
        && die "桥接没有停止。手动结束后重新运行本脚本。"
    note "已停止，系统默认输入已还原"
else
    note "没有正在运行的桥接"
fi

step "删除聚合音频设备"
if [ ! -x "$voice" ]; then
    note "虚拟环境不存在，跳过。删除聚合设备请用“音频 MIDI 设置”。"
elif "$voice" microphone | grep -q '^Passport Mic: present'; then
    "$venv/bin/python" - <<'PY'
from voice_bridge.hostaudio import CoreAudio
from voice_bridge.microphone import AggregateHal, remove
remove(CoreAudio(), AggregateHal())
PY
    note "已删除 Passport Mic"
else
    note "Passport Mic 不存在，跳过"
fi

step "删除令牌与本地状态"
for file in "$state/token" "$state/host"; do
    if [ -e "$file" ]; then
        rm -f "$file"
        note "已删除 $file"
    fi
done
rmdir "$state" 2>/dev/null || true

step "删除虚拟环境与构建残留"
if [ -d "$venv" ]; then
    rm -rf "$venv"
    note "已删除 $venv"
else
    note "虚拟环境不存在，跳过"
fi
rm -rf "$bridge/passport_voice_bridge.egg-info"
find "$bridge" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true

step "还需要手动处理"
cat <<TXT
   Mac 侧
   1. 辅助功能：系统设置 → 隐私与安全性 → 辅助功能，移除 python 条目。
   2. 输入法：把麦克风来源改回原来的设备。
   3. BlackHole 2ch 未卸载，它可能被其他程序共用。如要卸载：
        brew uninstall --cask blackhole-2ch

   设备侧
   4. 设备仍保存着 Wi-Fi 配置和令牌，桥接已删除，设备不会再被连上。
      重装后运行 install.sh，再用 `passport-voice configure` 重新配网；
      要彻底清干净则刷回时钟应用或擦除 NVS，两者都会清掉现有设置。
TXT

printf '\n卸载完成。\n'
