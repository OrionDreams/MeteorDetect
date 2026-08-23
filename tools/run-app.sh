#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/.." && pwd)"

configuration="${CONFIGURATION:-Release}"
dotnet_cmd="${DOTNET:-dotnet}"
app_project="$repo_root/src/MeteorDetect.App/MeteorDetect.App.csproj"
build_before_run="${BUILD_BEFORE_RUN:-1}"

if [[ "$build_before_run" != "0" ]]; then
  "$dotnet_cmd" build "$repo_root/MeteorDetect.slnx" \
    -c "$configuration"
fi

exec "$dotnet_cmd" run \
  --project "$app_project" \
  -c "$configuration" \
  --no-build \
  -- "$@"
