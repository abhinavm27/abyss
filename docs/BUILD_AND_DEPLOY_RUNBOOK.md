# ABYSS build and deployment runbook

This is the required startup and handoff guide for every new coding task. It
covers the complete ABYSS application deployed on GN100, including the care
journey engine, API, web UI, persistence, knowledge catalog, Hermes reasoning,
NVIDIA speech services, and sandbox adapters.

## 1. Start safely

Use a clean worktree when the current checkout contains user changes. Never
reset, clean, or overwrite an existing dirty checkout.

```bash
git fetch origin
git status --short --branch
git switch -c codex/<task-name> origin/main
```

Read `AGENTS.md`, this runbook, and the contracts relevant to the change before
editing. The deployed application is `/home/acer01/abyss-demo`. Do not replace it
with source from the legacy `/home/acer01/abyss` checkout.

## 2. Component and ownership map

| Component | Source/runtime | Responsibility |
| --- | --- | --- |
| Domain and agents | `src/abyss` | Journey orchestration, onboarding, knowledge, matching, consent, booking, receipts, and deterministic rules |
| API | `services/api/app` | FastAPI routes, authentication, persistence wiring, Hermes gateway, speech WebSocket, messaging adapters |
| Web app | `apps/web` | Chat, voice, scan/upload, journey controls, admin visibility, and API/WebSocket clients |
| State database | `/home/acer01/abyss-demo/data/abyss-state.db` | Writable users, sessions, facts, journeys, appointments, consents, and receipts |
| Knowledge database | `/home/acer01/abyss/services/api/abyss.db` | Read-only hospital catalog and published-rate evidence |
| Hermes | `HERMES_BASE_URL` through the authenticated NemoClaw gateway | Model extraction, classification, summaries, and explanations; never deterministic authority |
| NVIDIA speech | `NVIDIA_ASR_URL` and `NVIDIA_TTS_URL` | VAD-delimited speech recognition and streamed speech synthesis |
| Sandbox adapters | API/domain adapter modules | Provider verification, booking, enrollment, reminders, Discord/Twilio notifications |

The state and knowledge databases are intentionally different files. Never set
`ABYSS_DB` to the knowledge database and never run application migrations
against the knowledge database.

## 3. Validate locally before integration

Install deterministic dependencies when needed:

```bash
test -x .venv/bin/python || python3 -m venv .venv
.venv/bin/python -m pip install -e . -e services/api
npm --prefix apps/web ci
```

Run the complete validation matrix from the repository root:

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
PYTHONPATH=src:services/api .venv/bin/python -m unittest discover -s services/api/tests -v
npm --prefix apps/web test -- --run
npm --prefix apps/web run typecheck
npm --prefix apps/web run build
```

Add targeted tests for any changed state transition, consent gate, model schema,
voice lifecycle, upload path, or UI interaction. Model output is untrusted until
schema validation succeeds. A model explanation must not modify deterministic
eligibility, annual-cost math, consent, or booking rules.

Before committing:

```bash
git diff --check
git status --short
```

Do not stage `.env` files, credentials, SQLite databases, uploads, recordings,
node modules, virtual environments, or generated runtime logs.

## 4. Integrate and sync tracked source

Push the task branch and merge only after validation. Confirm that `main` contains
the intended commit before deploying. Use tracked source when transferring a
revision so local secrets and generated files cannot leak into the deployment:

```bash
git archive --format=tar HEAD | ssh -i "$HOME/Library/Application Support/NVIDIA/Sync/config/nvsync.key" \
  acer01@100.102.193.84 'tar -xf - -C /home/acer01/abyss-demo'
```

This updates tracked files in place and preserves untracked runtime files. It
does not remove obsolete tracked files; when a deletion matters, inspect the
exact remote target and remove only that path deliberately. Never delete or
overwrite these runtime assets:

- `/home/acer01/abyss-demo/data/abyss-state.db`
- `/home/acer01/abyss/services/api/abyss.db`
- `/home/acer01/abyss/.env` or `/etc/abyss/abyss.env`
- `/home/acer01/abyss-demo/.venv`
- uploaded documents, credentials, or logs

SSH can use either host route:

```bash
ssh gn100-75f8.local
ssh -i "$HOME/Library/Application Support/NVIDIA/Sync/config/nvsync.key" acer01@100.102.193.84
```

## 5. GN100 runtime configuration

The preferred installed environment is `/etc/abyss/abyss.env`. On the current
user-owned fallback, source `/home/acer01/abyss/.env` and apply the same runtime
overrides without printing secret values.

Required backend values:

```bash
PYTHONPATH=/home/acer01/abyss-demo/src
ABYSS_DB=/home/acer01/abyss-demo/data/abyss-state.db
ABYSS_KNOWLEDGE_DB=/home/acer01/abyss/services/api/abyss.db
NVIDIA_ASR_URL=http://127.0.0.1:9001
NVIDIA_TTS_URL=http://127.0.0.1:9002
ABYSS_API_BASE_URL=http://127.0.0.1:8011
ABYSS_PUBLIC_APP_URL=http://100.102.193.84:4173
```

Keep the existing `HERMES_BASE_URL`, `HERMES_API_KEY`, `HERMES_MODEL`, CORS,
Discord, Twilio, and allowlist values in the protected runtime environment. Do
not call vLLM port 8000 directly and do not echo the environment.

Required frontend build values:

```bash
VITE_API_URL=http://100.102.193.84:8011
VITE_WS_URL=ws://100.102.193.84:8011/ws
VITE_LIVE_MODE=true
VITE_DEMO_MODE=false
VITE_SECURE_APP_URL=http://localhost:4174
```

Vite embeds these values at build time. A backend environment change alone does
not update the browser bundle.

## 6. Build and restart on GN100

From `/home/acer01/abyss-demo`:

```bash
.venv/bin/python -m pip install -e . -e services/api
npm --prefix apps/web ci
VITE_API_URL=http://100.102.193.84:8011 \
VITE_WS_URL=ws://100.102.193.84:8011/ws \
VITE_LIVE_MODE=true \
VITE_DEMO_MODE=false \
VITE_SECURE_APP_URL=http://localhost:4174 \
npm --prefix apps/web run build
```

If the systemd units are installed, use the supervised path:

```bash
sudo systemctl restart abyss-api.service abyss-web.service abyss-healthcheck.timer
./scripts/gn100-status.sh
./scripts/gn100-health.sh
```

Installing or updating units is an operator action because it requires sudo:

```bash
./scripts/gn100-install-services.sh
```

If sudo or the units are unavailable, preserve the existing user-owned process
mode. Stop only the exact API and web PIDs owned by `acer01`, then start:

```bash
cd /home/acer01/abyss-demo
set -a
source /home/acer01/abyss/.env
set +a
export PYTHONPATH=/home/acer01/abyss-demo/src
export ABYSS_DB=/home/acer01/abyss-demo/data/abyss-state.db
export ABYSS_KNOWLEDGE_DB=/home/acer01/abyss/services/api/abyss.db
export NVIDIA_ASR_URL=http://127.0.0.1:9001
export NVIDIA_TTS_URL=http://127.0.0.1:9002
nohup .venv/bin/python -m uvicorn app.api:app --app-dir services/api \
  --host 0.0.0.0 --port 8011 > /tmp/abyss-api.log 2>&1 &
nohup npm --prefix apps/web run preview -- --host 0.0.0.0 --port 4173 --strictPort \
  > /tmp/abyss-web.log 2>&1 &
```

Never use a broad `pkill`, kill an unknown user's process, or start a second
listener on the same port. Resolve listeners first with `ss -ltnp` or `lsof`.
Report user-owned mode as a temporary operational limitation; do not claim the
systemd installation completed.

## 7. Voice access

Browser microphone capture requires a secure context. The public HTTP UI remains
available for chat, while local voice testing uses an SSH tunnel and the secure
app redirect configured at build time:

```bash
ssh -N -L 4174:127.0.0.1:4173 \
  -i "$HOME/Library/Application Support/NVIDIA/Sync/config/nvsync.key" \
  acer01@100.102.193.84
```

Open `http://localhost:4174/` for voice. Verify browser microphone permission,
the API WebSocket, ASR on port 9001, and TTS on port 9002. Exercise at least two
turns so journey state persistence and VAD stop/processing feedback are tested.

## 8. Required post-deploy verification

Run remote checks without exposing environment secrets:

```bash
curl --fail --silent http://127.0.0.1:8011/api/health
curl --fail --silent --output /dev/null http://127.0.0.1:4173/
ss -ltn | grep -E ':(4173|8011|9001|9002)[[:space:]]'
```

The API health response must report `state_database: ready` and a knowledge
catalog with `status: ready` and `access: read_only`. Confirm the configured
state and catalog paths separately from the process configuration without
printing secret environment values. Then test the changed path through the
served UI, not only through direct API calls. For care journeys, verify that
facts survive follow-up turns, no clarification loops occur, consent gates are
shown before actions, and receipts/appointments persist after refresh.

Inspect only relevant recent logs:

```bash
journalctl -u abyss-api.service -u abyss-web.service --since '15 minutes ago' --no-pager
tail -n 100 /tmp/abyss-api.log
tail -n 100 /tmp/abyss-web.log
```

Use the log source matching the active service mode. Do not include tokens,
headers, patient data, or full protected environment output in the handoff.

## 9. Definition of deployed

A task is complete only when the handoff records:

- merged/deployed commit and branch;
- local and remote validation results;
- service mode: systemd or user-owned fallback;
- API URL: `http://100.102.193.84:8011`;
- web URL: `http://100.102.193.84:4173`;
- voice URL through the tunnel: `http://localhost:4174`;
- the UI flow exercised and its result;
- any operator-only sudo, credential, or external-service action still pending.

See `docs/GN100_DEPLOYMENT.md` for the systemd installation, health timer, and
virtual-environment migration details.
