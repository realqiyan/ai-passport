#!/usr/bin/env bash
# Compatibility installer: pipx owns the environment; setup owns audio/state.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
[ $# -eq 0 ] || { printf '用法：install.sh\n' >&2; exit 1; }
[ "$(uname -s)" = Darwin ] || { printf '此程序只在 macOS 上运行。\n' >&2; exit 1; }
command -v pipx >/dev/null 2>&1 || {
    printf '请先安装 pipx，并运行 pipx ensurepath。详见 README.md。\n' >&2
    exit 1
}
source "$here/bridge-command.sh"
# Refresh metadata and dependencies only after verifying an existing source.
if [ -n "$voice" ] && [ -n "${PYTHON:-}" ]; then
    # --force does not change the interpreter; reinstall does.
    pipx reinstall "$pipx_package" --python "$PYTHON"
else
    install_args=(install --editable "$here/bridge")
    [ -z "$voice" ] || install_args+=(--force)
    [ -z "${PYTHON:-}" ] || install_args+=(--python "$PYTHON")
    pipx "${install_args[@]}"
fi
source "$here/bridge-command.sh"
[ -n "$voice" ] || { printf 'pipx 未提供桥接命令。\n' >&2; exit 1; }
exec "$voice" setup --legacy-state-dir "$here/.local"
