#!/usr/bin/env bash
# Clean up successfully before removing this checkout's environment.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
[ "$(uname -s)" = Darwin ] || { printf '此程序只在 macOS 上运行。\n' >&2; exit 1; }
[ $# -le 1 ] && { [ $# -eq 0 ] || [ "$1" = --yes ]; } || {
    printf '用法：uninstall.sh [--yes]\n' >&2
    exit 1
}
source "$here/bridge-command.sh"
# Permit removal of an old editable project environment when pipx is absent.
if [ -z "$voice" ]; then
    voice="$here/bridge/.venv/bin/passport-voice"
    [ -x "$voice" ] || {
        printf '找不到桥接环境，无法安全清理音频设备和状态。请先运行 install.sh。\n' >&2
        exit 1
    }
    legacy_source="$("$here/bridge/.venv/bin/python" -I -c 'from pathlib import Path; import voice_bridge; print(Path(voice_bridge.__file__).resolve().parent.parent)')" || {
        printf '无法核验旧环境来源，已停止。\n' >&2
        exit 1
    }
    [ "$legacy_source" = "$here/bridge" ] || { printf '旧环境来自其他目录，已停止。\n' >&2; exit 1; }
fi
printf '将停止桥接、清理 Passport Mic 和已保存状态，再删除当前目录的安装。\n'
if [ $# -eq 0 ]; then
    printf '继续请输入 yes：'
    read -r answer
    [ "$answer" = yes ] || { printf '已取消，未做改动。\n'; exit 0; }
fi
"$voice" cleanup --yes --legacy-state-dir "$here/.local"
if [ -n "$installed_source" ]; then
    pipx uninstall "$pipx_package"
fi
rm -rf "$here/bridge/.venv" "$here/bridge/passport_voice_bridge.egg-info"
find "$here/bridge" -name __pycache__ -type d -prune -exec rm -rf {} +
printf '卸载完成。辅助功能授权和输入法麦克风选择需手动移除；BlackHole 和设备 NVS 保留。\n'
