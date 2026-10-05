#!/usr/bin/env bash
# Resolve the pipx environment and verify its source before repository actions.
# Source this file after setting here to the physical voice directory.
pipx_package="passport-voice-bridge"
voice=""
installed_source=""
pipx_voice=""
if command -v pipx >/dev/null 2>&1; then
    pipx_venvs="$(pipx environment --value PIPX_LOCAL_VENVS)" || {
        printf '无法读取 pipx 环境。\n' >&2
        exit 1
    }
    if [ -n "$pipx_venvs" ]; then
        pipx_env="$pipx_venvs/$pipx_package"
        pipx_voice="$pipx_env/bin/passport-voice"
        if [ -d "$pipx_env" ]; then
            [ -x "$pipx_voice" ] && [ -x "$pipx_env/bin/python" ] || {
                printf 'pipx 环境损坏，请先修复或重装。\n' >&2
                exit 1
            }
            installed_source="$("$pipx_env/bin/python" -I -c 'from pathlib import Path; import voice_bridge; print(Path(voice_bridge.__file__).resolve().parent.parent)')" || {
                printf '无法核验 pipx 安装来源，已停止。\n' >&2
                exit 1
            }
            [ "$installed_source" = "$here/bridge" ] || {
                printf 'pipx 安装来源为 %s，与当前目录不同，已停止。直接使用该安装的 passport-voice 命令，或先清理原安装。\n' "$installed_source" >&2
                exit 1
            }
            voice="$pipx_voice"
        fi
    fi
fi
