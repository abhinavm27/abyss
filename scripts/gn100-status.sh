#!/usr/bin/env bash
set -euo pipefail

systemctl --no-pager --full status abyss-api.service abyss-web.service abyss-healthcheck.timer || true

if systemctl is-active --quiet abyss-api.service && systemctl is-active --quiet abyss-web.service; then
  exec /home/acer01/abyss-demo/scripts/gn100-health.sh
fi

echo "One or more ABYSS services are not active." >&2
exit 1
