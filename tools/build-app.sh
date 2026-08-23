#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/.." && pwd)"

configuration="${CONFIGURATION:-Release}"
dotnet_cmd="${DOTNET:-dotnet}"

exec "$dotnet_cmd" build "$repo_root/MeteorDetect.slnx" \
  -c "$configuration" \
  "$@"
