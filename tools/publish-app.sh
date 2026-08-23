#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/.." && pwd)"

configuration="${CONFIGURATION:-Release}"
dotnet_cmd="${DOTNET:-dotnet}"
app_project="$repo_root/src/MeteorDetect.App/MeteorDetect.App.csproj"

detect_rid() {
  local os arch
  os="$(uname -s)"
  arch="$(uname -m)"

  case "$os" in
    Linux*) os="linux" ;;
    Darwin*) os="osx" ;;
    MINGW*|MSYS*|CYGWIN*) os="win" ;;
    *)
      echo "Unsupported OS from uname: $os" >&2
      return 1
      ;;
  esac

  case "$arch" in
    x86_64|amd64) arch="x64" ;;
    aarch64|arm64) arch="arm64" ;;
    *)
      echo "Unsupported architecture from uname: $arch" >&2
      return 1
      ;;
  esac

  printf '%s-%s\n' "$os" "$arch"
}

runtime_identifier="${RUNTIME_IDENTIFIER:-$(detect_rid)}"
output_dir="${OUTPUT_DIR:-$repo_root/artifacts/publish/$runtime_identifier}"

exec "$dotnet_cmd" publish "$app_project" \
  -c "$configuration" \
  -r "$runtime_identifier" \
  -o "$output_dir" \
  "$@"
