#!/usr/bin/env bash
set -euo pipefail

: "${GN100_SSH_HOST:=gn100-75f8}"
: "${GN100_SSH_USER:=acer01}"
: "${HERMES_API_PORT:=8642}"
: "${HERMES_DASHBOARD_PORT:=18791}"

echo "Opening private Hermes tunnel to ${GN100_SSH_USER}@${GN100_SSH_HOST}"
echo "API:       http://127.0.0.1:${HERMES_API_PORT}/v1"
echo "Dashboard: http://127.0.0.1:${HERMES_DASHBOARD_PORT}/"
echo "Keep this process open; press Ctrl-C to disconnect."

exec ssh -N \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -L "127.0.0.1:${HERMES_API_PORT}:127.0.0.1:8642" \
  -L "127.0.0.1:${HERMES_DASHBOARD_PORT}:127.0.0.1:18791" \
  "${GN100_SSH_USER}@${GN100_SSH_HOST}"

