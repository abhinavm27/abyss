#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="${repo_root}/.venv/bin/python"

if [[ ! -x "${python_bin}" ]]; then
  echo "VELA virtual environment is missing: ${python_bin}" >&2
  exit 1
fi

export PYTHONPATH="${repo_root}/src:${repo_root}/services"
export ABYSS_API_BASE_URL="${ABYSS_API_BASE_URL:-http://127.0.0.1:8011}"
exec "${python_bin}" -m discord_bot.bot "$@"
