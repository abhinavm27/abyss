#!/usr/bin/env bash
set -euo pipefail

quiet=false
if [[ "${1:-}" == "--quiet" ]]; then
  quiet=true
elif [[ $# -gt 0 ]]; then
  echo "usage: $0 [--quiet]" >&2
  exit 2
fi

: "${ABYSS_API_HEALTH_URL:=http://127.0.0.1:8011/api/health}"
: "${ABYSS_WEB_HEALTH_URL:=http://127.0.0.1:4173/}"
: "${ABYSS_DB:=/home/acer01/abyss-demo/data/abyss-state.db}"
: "${ABYSS_KNOWLEDGE_DB:=/home/acer01/abyss/services/api/abyss.db}"

failures=0

check_url() {
  local label="$1"
  local url="$2"
  local response

  if response="$(curl --fail --silent --show-error --max-time 8 "$url" 2>&1)"; then
    if [[ "$quiet" == false ]]; then
      printf 'ok   %-18s %s\n' "$label" "$url"
    fi
  else
    printf 'fail %-18s %s (%s)\n' "$label" "$url" "$response" >&2
    failures=$((failures + 1))
  fi
}

check_url "API" "$ABYSS_API_HEALTH_URL"
check_url "frontend" "$ABYSS_WEB_HEALTH_URL"

if [[ -r "$ABYSS_KNOWLEDGE_DB" ]]; then
  if [[ "$quiet" == false ]]; then
    printf 'ok   %-18s %s\n' "knowledge catalog" "$ABYSS_KNOWLEDGE_DB"
  fi
else
  printf 'fail %-18s %s is not readable\n' "knowledge catalog" "$ABYSS_KNOWLEDGE_DB" >&2
  failures=$((failures + 1))
fi

state_dir="$(dirname "$ABYSS_DB")"
if [[ -d "$state_dir" && -w "$state_dir" ]]; then
  if [[ "$quiet" == false ]]; then
    printf 'ok   %-18s %s\n' "state directory" "$state_dir"
  fi
else
  printf 'fail %-18s %s is not writable\n' "state directory" "$state_dir" >&2
  failures=$((failures + 1))
fi

if (( failures > 0 )); then
  exit 1
fi

if [[ "$quiet" == false ]]; then
  echo "ABYSS services are healthy."
fi
