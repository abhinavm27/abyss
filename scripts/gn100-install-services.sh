#!/usr/bin/env bash
set -euo pipefail

app_root="/home/acer01/abyss-demo"
unit_source="$app_root/deploy/systemd"
env_template="$app_root/deploy/abyss.env.template"
env_dir="/etc/abyss"
env_file="$env_dir/abyss.env"
unit_dir="/etc/systemd/system"

if [[ "$(id -un)" != "acer01" ]]; then
  echo "Run this script as acer01; it will use sudo only for system files." >&2
  exit 1
fi

for required in \
  "$app_root/services/api/app/api.py" \
  "$app_root/apps/web/package-lock.json" \
  "$app_root/.venv/bin/python" \
  "$env_template" \
  "$unit_source/abyss-api.service" \
  "$unit_source/abyss-web.service" \
  "$unit_source/abyss-healthcheck.service" \
  "$unit_source/abyss-healthcheck.timer"; do
  if [[ ! -e "$required" ]]; then
    echo "Required path is missing: $required" >&2
    exit 1
  fi
done

if [[ ! -x /usr/bin/npm ]]; then
  echo "/usr/bin/npm is required (Node.js 22 or newer)." >&2
  exit 1
fi

node_major="$(/usr/bin/node --version | sed -E 's/^v([0-9]+).*/\1/')"
if [[ ! "$node_major" =~ ^[0-9]+$ ]] || (( node_major < 22 )); then
  echo "Node.js 22 or newer is required; found $(/usr/bin/node --version)." >&2
  exit 1
fi

sudo install -d -m 0755 -o acer01 -g acer01 "$app_root/data"
sudo install -d -m 0755 -o acer01 -g acer01 "$app_root/apps/web/dist"
sudo install -d -m 0755 -o acer01 -g acer01 "$app_root/apps/web/node_modules/.vite-temp"
sudo install -d -m 0750 -o root -g acer01 "$env_dir"

if ! sudo test -e "$env_file"; then
  sudo install -m 0600 -o root -g acer01 "$env_template" "$env_file"
  echo "Created $env_file. Add HERMES_API_KEY before starting the API."
else
  echo "Preserving existing $env_file."
fi

for unit in abyss-api.service abyss-web.service abyss-healthcheck.service abyss-healthcheck.timer; do
  sudo install -m 0644 "$unit_source/$unit" "$unit_dir/$unit"
done

sudo systemd-analyze verify \
  "$unit_dir/abyss-api.service" \
  "$unit_dir/abyss-web.service" \
  "$unit_dir/abyss-healthcheck.service" \
  "$unit_dir/abyss-healthcheck.timer"
sudo systemctl daemon-reload
sudo systemctl enable abyss-api.service abyss-web.service abyss-healthcheck.timer

resolved_venv="$(readlink -f "$app_root/.venv")"
if [[ "$resolved_venv" == "/home/acer01/abyss/.venv" ]]; then
  echo "Note: .venv still resolves to the shared /home/acer01/abyss/.venv runtime."
fi

echo "Services installed but not started. Review $env_file, then run scripts/gn100-start.sh."
