#!/usr/bin/env bash
# Use the Python interpreter from an activated ESP-IDF environment.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${PYTHON:-python3}" "$here/flash_firmware.py" "$@"
