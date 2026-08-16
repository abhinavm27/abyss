#!/usr/bin/env bash
set -euo pipefail

sudo systemctl stop abyss-healthcheck.timer abyss-web.service abyss-api.service
echo "ABYSS API, frontend, and periodic health check are stopped."
