#!/usr/bin/env bash
# Install the Mac side of the AI Passport voice application.
#
# This script is safe to run again. It writes only inside its own directory and
# one system audio device. It never installs system packages by itself.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bridge="$here/bridge"
venv="$bridge/.venv"
voice="$venv/bin/passport-voice"
driver="/Library/Audio/Plug-Ins/HAL/BlackHole2ch.driver"

step() { printf '\n== %s\n' "$1"; }
note() { printf '   %s\n' "$1"; }
die() { printf '\ninstall.sh: %s\n' "$1" >&2; exit 1; }

[ $# -eq 0 ] || die "用法：install.sh（不接受桥接选项）"
step "检查环境"
[ "$(uname -s)" = "Darwin" ] || die "此桥接程序只在 macOS 上运行。"
python_bin="${PYTHON:-python3}"
command -v "$python_bin" >/dev/null 2>&1 || die "缺少 python3。安装 Python 3.10 或更新版本后重试。"
"$python_bin" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' \
    || die "需要 Python 3.10 或更新版本。"
note "$("$python_bin" -V)"

step "安装桥接程序"
if [ ! -x "$venv/bin/python" ]; then
    "$python_bin" -m venv "$venv"
    note "已创建虚拟环境 $venv"
fi
"$venv/bin/python" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' \
    || die "现有虚拟环境不可用。迁移时不要复制 .venv；请在新 Mac 重建。"
"$venv/bin/python" -m pip install --quiet --upgrade pip
"$venv/bin/python" -m pip install --quiet -e "$bridge"
"$voice" --help >/dev/null || die "桥接命令不可用。迁移时不要复制 .venv；请在新 Mac 重建。"
note "passport-voice 命令可用"

step "检查 BlackHole 2ch"
if [ ! -e "$driver" ]; then
    die "缺少 BlackHole 2ch 驱动。先执行下面两条命令，再运行本脚本：
    brew install --cask blackhole-2ch
    sudo killall coreaudiod"
fi
if ! "$voice" devices | grep -q 'BlackHole 2ch'; then
    die "驱动已安装，但音频服务还没有加载它。执行下面这条命令，再运行本脚本：
    sudo killall coreaudiod"
fi
note "BlackHole 2ch 已加载"

step "准备聚合输入设备"
report="$("$voice" microphone)" || die "无法读取聚合设备状态。"
if printf '%s\n' "$report" | grep -q '^Passport Mic: present'; then
    note "Passport Mic 已存在，未改动"
else
    "$voice" microphone --create
fi
"$voice" microphone | sed 's/^/   /'

step "下一步"
cat <<TXT
   1. 授予辅助功能权限，否则设备无法触发快捷键：
      系统设置 → 隐私与安全性 → 辅助功能
      允许运行桥接的终端应用，或直接允许 $venv/bin/python
      授权后必须重启桥接程序才会生效。

   2. 在输入法里把麦克风选为 Passport Mic。

   3. 启动桥接：
      $here/start.sh usb     有线链路
      $here/start.sh wifi    无线链路

   详细用法见 $here/README.md。
TXT

printf '\n安装完成。\n'
