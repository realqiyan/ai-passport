#!/usr/bin/env bash
# Source this file from a Bash shell before building.
AI_PASSPORT_PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export IDF_TOOLS_PATH="${AI_PASSPORT_PROJECT_ROOT}/.tools/espressif"
export PATH="${AI_PASSPORT_PROJECT_ROOT}/.venv/bin:${PATH}"
source "${AI_PASSPORT_PROJECT_ROOT}/.tools/esp-idf/export.sh"
