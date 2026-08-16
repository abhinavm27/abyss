# ABYSS → VELA integration task board

## Objective

Keep VELA (`abyss-demo` / Git `main`) as the canonical application and selectively
integrate the production-shaped capabilities currently stranded in `/home/acer01/abyss`.
The Care Journey Agent remains the orchestrator. Deterministic code retains authority
over cost math, eligibility, state transitions, consent, and actions.

## Runtime boundaries

| Concern | Authoritative store | Access mode |
| --- | --- | --- |
| Users, memory, journeys, appointments, receipts | `ABYSS_DB` | read/write |
| Seattle hospitals and published rates | `ABYSS_KNOWLEDGE_DB` | read-only at runtime |
| Raw uploads | none | process in memory, then discard |
| Model access | authenticated Hermes gateway | validated text-only requests |

No user, journey, or session rows are copied from the legacy database. The large
catalog is mounted as evidence, not used as the application-state database.

## Parallel workstreams

All five workstreams are integrated on `codex/integrate-abyss-capabilities`.
The repository includes root-systemd service assets; installing those units on
GN100 remains an operator step because it requires that machine's sudo password.
The current test deployment runs the same API and web commands under `acer01`.

### K — Catalog adapter

Status: complete and live on GN100.

- Configure the real Seattle catalog explicitly.
- Validate path/schema/freshness at startup and health check.
- Return source-backed rate evidence without inferring network status.
- Preserve seeded catalog behavior only when no external catalog is configured.

### R — Report and referral intake

Status: complete, including PDF/text upload and camera image + browser OCR.

- Record exact document-processing consent.
- Extract text from supported PDFs/text files without persisting the raw upload.
- Send text only through Hermes and schema-validate candidate clinician orders.
- Require user confirmation before candidates become journey facts.
- Retain source quotation, location, confidence, verification state, and timestamp.

### M — Messaging adapters

Status: complete; sandbox remains the default.

- Unify preview and send behind one adapter interface.
- Keep ordinary SMS/Discord messages secure-link-only.
- Require exact channel, destination, and message-kind consent.
- Default all adapters to sandbox and persist redacted receipts.

### O — GN100 operations

Status: deployment assets complete; privileged unit installation pending operator sudo.

- Supervise API and frontend processes instead of PID files and ad-hoc `nohup`.
- Keep environment configuration outside Git.
- Separate the state and knowledge database paths.
- Add health/start/stop/status checks and automatic restart.

### U — VELA and admin interface

Status: complete and deployed.

- Present Insurance card, Summary of Benefits, Referral/order, and Bill as distinct inputs.
- Review and confirm extracted orders before starting or updating a journey.
- Show document consent, extraction, confirmation, knowledge evidence, matching, and
  delivery receipts in the admin trace.

## Shared contracts

1. A report candidate is not a journey fact until the user confirms it.
2. A published hospital rate is not proof of network participation.
3. Messaging preview is not authorization to send.
4. Models may extract and explain; deterministic services decide and act.
5. Every external action carries a journey ID, exact consent scope, and audit receipt.
6. Existing journeys and appointments must survive every migration.

## Integration sequence

1. Merge and test K, R, M, and O independently.
2. Mount backend routers and adapters through the existing authenticated API.
3. Implement U against the settled backend contracts.
4. Add state migrations without copying legacy users.
5. Run local deterministic tests and frontend build.
6. Run GN100 catalog, API, voice, document, messaging, and booking evaluations.
7. Deploy under supervision and verify restart behavior.

## Acceptance journey

An authenticated synthetic member starts a new journey, uploads a consented clinician
order for an MRI, confirms the extracted order, receives current-plan hospital options
backed by the real Seattle rate catalog, approves provider verification and sandbox
booking, and optionally sends a secure-link notification. The admin view shows every
agent handoff, evidence source, consent, and receipt.
