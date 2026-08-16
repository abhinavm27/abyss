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
: "${ABYSS_HERMES_HEALTH_URL:=http://127.0.0.1:8642/v1/models}"
: "${NVIDIA_ASR_URL:=http://127.0.0.1:9001}"
: "${NVIDIA_TTS_URL:=http://127.0.0.1:9002}"
: "${ABYSS_DB:=/home/acer01/abyss-demo/data/abyss-state.db}"
: "${ABYSS_KNOWLEDGE_DB:=/home/acer01/abyss/services/api/abyss.db}"

failures=0

check_url() {
  local label="$1"
  local url="$2"
  local response

  if response="$(curl --fail --silent --show-error --max-time 8 "$url" 2>&1)"; then
    if [[ "$quiet" == false ]]; then
      # Status lines go to stderr: callers capture this function's stdout via
      # command substitution to read the response body, and a status line
      # mixed into that would corrupt it.
      printf 'ok   %-18s %s\n' "$label" "$url" >&2
    fi
  else
    printf 'fail %-18s %s (%s)\n' "$label" "$url" "$response" >&2
    failures=$((failures + 1))
  fi
  printf '%s' "$response"
}

api_health="$(check_url "API" "$ABYSS_API_HEALTH_URL")"
check_url "frontend" "$ABYSS_WEB_HEALTH_URL" >/dev/null

# A readable file is not a usable catalog — an empty database is readable too,
# and reported "ready" for weeks before anyone noticed the corpus was empty.
# /api/health now reports real counts read straight from the catalog, so ask
# it rather than duplicating that query here.
if [[ ! -r "$ABYSS_KNOWLEDGE_DB" ]]; then
  printf 'fail %-18s %s is not readable\n' "knowledge catalog" "$ABYSS_KNOWLEDGE_DB" >&2
  failures=$((failures + 1))
elif catalog_status="$(printf '%s' "$api_health" | python3 -c '
import json, sys
try:
    doc = json.load(sys.stdin)
    status = doc.get("knowledge_catalog", {}).get("status")
    hospitals = doc.get("hospitals", 0)
    rates = doc.get("rates", 0)
except Exception:
    print("unavailable 0 0"); sys.exit(0)
print(f"{status} {hospitals} {rates}")
' 2>/dev/null)"; then
  read -r status hospitals rates <<<"$catalog_status"
  if [[ "$status" == "ready" && "$hospitals" -gt 0 && "$rates" -gt 0 ]]; then
    if [[ "$quiet" == false ]]; then
      printf 'ok   %-18s %s (%s hospitals, %s rates)\n' "knowledge catalog" "$ABYSS_KNOWLEDGE_DB" "$hospitals" "$rates"
    fi
  else
    printf 'fail %-18s %s reports status=%s hospitals=%s rates=%s\n' \
      "knowledge catalog" "$ABYSS_KNOWLEDGE_DB" "$status" "$hospitals" "$rates" >&2
    failures=$((failures + 1))
  fi
else
  printf 'fail %-18s could not read catalog status from %s\n' "knowledge catalog" "$ABYSS_API_HEALTH_URL" >&2
  failures=$((failures + 1))
fi

# Nemotron and the two voice NIMs are demo-critical but were invisible here:
# this script reported "healthy" with all three down, because it only probed
# the API and the web server. Hermes answers 401 without a bearer token, which
# proves it is up — only a connection failure means it is actually down.
check_reachable() {
  local label="$1"
  local url="$2"
  local code

  code="$(curl --silent --output /dev/null --max-time 8 --write-out '%{http_code}' "$url" 2>/dev/null || true)"
  if [[ "$code" == "000" || -z "$code" ]]; then
    printf 'fail %-18s %s (unreachable)\n' "$label" "$url" >&2
    failures=$((failures + 1))
  elif [[ "$quiet" == false ]]; then
    printf 'ok   %-18s %s (HTTP %s)\n' "$label" "$url" "$code"
  fi
}

check_reachable "Hermes gateway" "$ABYSS_HERMES_HEALTH_URL"
check_reachable "Parakeet ASR" "${NVIDIA_ASR_URL%/}/v1/health/ready"
check_reachable "Magpie TTS" "${NVIDIA_TTS_URL%/}/v1/health/ready"

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
