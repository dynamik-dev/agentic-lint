#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

case "${1:-post-tool-use}" in
  session-start)
    exec python3 "$HERE/pipeline.py" session-start
    ;;
  post-tool-use|*)
    exec python3 "$HERE/pipeline.py" --hook-mode
    ;;
esac
