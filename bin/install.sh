#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/.." && pwd)"
cd "$repo_root"

if [[ ! -d .venv ]]; then
  python -m venv .venv
fi

shell_name="$(basename "${SHELL:-}")"
if [[ -z "$shell_name" ]]; then
  shell_name="$(basename "${0:-sh}")"
fi

if [[ "$shell_name" == "fish" ]]; then
  if [[ -f .venv/bin/activate.fish ]]; then
    exec fish -C "source .venv/bin/activate.fish"
  fi
  echo "Fish activation script not found: .venv/bin/activate.fish" >&2
  exit 1
fi

if [[ -f .venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
  exec "${SHELL:-bash}"
fi

echo "Activation script not found: .venv/bin/activate" >&2
exit 1
