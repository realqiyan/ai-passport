#!/usr/bin/env bash
# Forward arguments to this checkout's pipx command.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source "$here/bridge-command.sh"
[ -n "$voice" ] || {
    printf '桥接程序未安装。先运行 %s/install.sh\n' "$here" >&2
    exit 1
}
exec "$voice" "$@"
