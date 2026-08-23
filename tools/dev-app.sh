#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/.." && pwd)"

configuration="${CONFIGURATION:-Debug}"
dotnet_cmd="${DOTNET:-dotnet}"
app_project="$repo_root/src/MeteorDetect.App/MeteorDetect.App.csproj"

"$dotnet_cmd" build "$repo_root/MeteorDetect.slnx" \
  -c "$configuration"

exec "$dotnet_cmd" run \
  --project "$app_project" \
  -c "$configuration" \
  --no-build \
  -- "$@"
