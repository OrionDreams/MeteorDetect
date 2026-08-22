#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/.." && pwd)"

if [[ $# -lt 1 ]]; then
  echo "Usage: $(basename "$0") VIDEO_FILE [detector options]" >&2
  exit 2
fi

exec python "$repo_root/detect.py" "$@"
