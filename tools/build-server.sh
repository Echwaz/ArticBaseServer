#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
python3 "$root/tools/apply_protocol_patch.py"
make -C "$root/standalone" ArticDockTest.cia "$@"
