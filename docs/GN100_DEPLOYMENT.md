# GN100 deployment

All coding tasks must first follow `docs/BUILD_AND_DEPLOY_RUNBOOK.md`. This file
contains the additional systemd installation, health timer, and virtual
environment migration details.

This deployment keeps the current VELA application in `/home/acer01/abyss-demo`
and reads the Seattle hospital catalog from the original `/home/acer01/abyss`
tree. It does not merge runtime state, credentials, or virtual environments into
Git.

## Runtime layout

| Purpose | Path |
| --- | --- |
| Application checkout | `/home/acer01/abyss-demo` |
| Application state | `/home/acer01/abyss-demo/data/abyss-state.db` |
| Read-only knowledge catalog | `/home/acer01/abyss/services/api/abyss.db` |
| Runtime environment | `/etc/abyss/abyss.env` |
| API | `http://100.102.193.84:8011` |
| Frontend | `http://100.102.193.84:4173` |

`ABYSS_DB` must never point at the catalog database. It contains user accounts,
sessions, journeys, appointments, consent records, and receipts. The Knowledge
Agent opens `ABYSS_KNOWLEDGE_DB` for hospital evidence. Keeping the paths distinct
prevents application migrations from modifying the 947 MB catalog.

## First installation

Connect to GN100, update the integration checkout, and install deterministic
dependencies:

```bash
ssh gn100-75f8.local
cd /home/acer01/abyss-demo
git pull --ff-only
/home/acer01/abyss-demo/.venv/bin/python -m pip install -e . -e services/api
npm --prefix apps/web ci
./scripts/gn100-install-services.sh
```

If mDNS is unavailable, use the NVIDIA Sync identity through Tailscale:

```bash
ssh -i "$HOME/Library/Application Support/NVIDIA/Sync/config/nvsync.key" \
  acer01@100.102.193.84
```

The installer creates `/etc/abyss/abyss.env` once, with mode `0600`, and never
overwrites it on later runs. Edit that file with `sudoedit` and populate
`HERMES_API_KEY` from the authenticated GN100 Hermes gateway. Do not print the
key, put it in shell history, or copy it into the checkout.

```bash
sudoedit /etc/abyss/abyss.env
```

If the GN100 Tailscale address changes, update `ABYSS_CORS_ORIGINS`,
`VITE_API_URL`, and `VITE_WS_URL`. Vite values are embedded during the supervised
build, so restart the web service afterward.

## Operations

Run these commands from `/home/acer01/abyss-demo`:

```bash
./scripts/gn100-start.sh
./scripts/gn100-status.sh
./scripts/gn100-health.sh
./scripts/gn100-stop.sh
```

Restart after a code or environment update:

```bash
sudo systemctl restart abyss-api.service abyss-web.service
./scripts/gn100-health.sh
```

Inspect recent logs without exposing the environment file:

```bash
journalctl -u abyss-api.service -u abyss-web.service --since "15 minutes ago" --no-pager
journalctl -u abyss-healthcheck.service -n 20 --no-pager
```

The API is supervised on port `8011`. The web service builds with the configured
public API/WebSocket endpoints and serves the resulting bundle with Vite preview
on port `4173`. Both restart after unexpected failures. A systemd timer checks
the API, frontend, state directory, and knowledge catalog every minute.

## Health and failure behavior

The manual and periodic checks require:

- `GET /api/health` to return successfully on port `8011`;
- the Vite preview root to return successfully on port `4173`;
- `ABYSS_KNOWLEDGE_DB` to remain readable;
- the parent directory of `ABYSS_DB` to remain writable by `acer01`.

The timer records failures in the journal but does not mutate databases or hide
a missing catalog. Systemd restarts a service only when its own process exits
unexpectedly. `gn100-start.sh` waits up to 30 seconds and reports service status
if either endpoint does not become ready.

## Current shared virtual environment and migration

Today `/home/acer01/abyss-demo/.venv` resolves to
`/home/acer01/abyss/.venv`. The units intentionally execute through the demo
path so this remains compatible during integration, but the shared environment
couples two checkouts and is not the long-term layout.

Migrate without changing the unit files:

```bash
cd /home/acer01/abyss-demo
./scripts/gn100-stop.sh
mv .venv .venv.shared-link
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e . -e services/api
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
./scripts/gn100-start.sh
```

After a successful start and end-to-end check, remove only the saved symlink:

```bash
rm .venv.shared-link
```

Do not remove `/home/acer01/abyss/.venv`; the original checkout may still use it.
Rollback is recoverable: stop the services, move the new `.venv` aside, restore
`.venv.shared-link` to `.venv`, and start again.

## Updating service definitions

After pulling changes under `deploy/systemd` or `scripts/gn100-*.sh`, rerun:

```bash
./scripts/gn100-install-services.sh
sudo systemctl restart abyss-api.service abyss-web.service abyss-healthcheck.timer
./scripts/gn100-status.sh
```

The installer validates all unit files before enabling them. It does not start
services, overwrite `/etc/abyss/abyss.env`, fetch credentials, or alter either
SQLite database.
