#!/usr/bin/env bash
set -euo pipefail

app_root="/home/acer01/abyss-demo"
env_file="/etc/abyss/abyss.env"

if [[ "$(pwd -P)" != "$app_root" ]]; then
  echo "Run this command from $app_root." >&2
  exit 1
fi

if ! sudo test -r "$env_file"; then
  echo "$env_file is missing; run scripts/gn100-install-services.sh first." >&2
  exit 1
fi

sudo systemctl start abyss-api.service abyss-web.service abyss-healthcheck.timer

for attempt in {1..15}; do
  if sudo -u acer01 env \
    ABYSS_API_HEALTH_URL=http://127.0.0.1:8011/api/health \
    ABYSS_WEB_HEALTH_URL=http://127.0.0.1:4173/ \
    ABYSS_DB=/home/acer01/abyss-demo/data/abyss-state.db \
    ABYSS_KNOWLEDGE_DB=/home/acer01/abyss/services/api/abyss.db \
    "$app_root/scripts/gn100-health.sh" --quiet; then
    echo "ABYSS API and frontend are ready."
    exit 0
  fi
  sleep 2
done

echo "Services did not become healthy within 30 seconds." >&2
sudo systemctl --no-pager --full status abyss-api.service abyss-web.service || true
exit 1
