# ABYSS agent instructions

These instructions apply to Codex and other repository-aware coding agents.

## Mission

Build one reliable, truthful, end-to-end demo journey: a Washington user who
recently lost employer coverage needs a non-emergency MRI, compares three plans,
selects the lowest expected annual-cost path subject to medication and physician
constraints, approves sandbox enrollment and transition, verifies a provider,
and books a sandbox appointment.

## Non-negotiable rules

- Never describe ABYSS as medical advice, a licensed broker, or production enrollment.
- Never execute enrollment, coverage cancellation, or booking without the matching
  explicit consent record.
- Never end old coverage before the new effective date and first-premium conditions
  are confirmed.
- Never invent missing plan, eligibility, provider, price, or clinical facts.
- Every material fact must include value, source, timestamp, confidence,
  verification status, and consent requirement.
- Deterministic code owns cost math, eligibility gates, and consent enforcement.
  Models may extract, classify, summarize, and explain; they do not override rules.
- Use seeded synthetic data for the hackathon. Do not commit real health or insurance data.
- Never commit tokens, passwords, SSH keys, raw uploaded documents, or `.env` files.
- Reach the model only through the authenticated Hermes gateway. Do not bypass
  NemoClaw by calling vLLM port 8000 directly.

## Engineering workflow

1. Keep a complete vertical path working; mock a seam before leaving it disconnected.
2. Add or update tests for deterministic behavior.
3. Preserve the domain contracts in `src/abyss/domain.py`.
4. Make state transitions explicit and reject invalid transitions.
5. Display known, inferred, missing, and verified states distinctly.
6. Keep live-provider and enrollment adapters behind sandbox interfaces.
7. Run the complete validation matrix in `docs/BUILD_AND_DEPLOY_RUNBOOK.md`
   before handing off; use the project virtual environment for Python tests.

## New task startup and deployment contract

Every new repository-aware task must read
`docs/BUILD_AND_DEPLOY_RUNBOOK.md` before changing, testing, or deploying code.
That runbook is the source of truth for the component map, complete validation
matrix, GN100 paths, environment variables, deployment order, voice tunnel, and
post-deploy checks.

- Start from `origin/main` on a `codex/` branch unless the user explicitly names
  another base. Inspect `git status` first and never discard another task's work.
- Treat `/home/acer01/abyss-demo` as the deployed application. The legacy
  `/home/acer01/abyss` tree supplies the read-only knowledge catalog and existing
  machine-local runtime configuration; do not deploy application source there.
- Keep `/home/acer01/abyss-demo/data/abyss-state.db` writable and separate from
  `/home/acer01/abyss/services/api/abyss.db`, which is read-only catalog evidence.
- Build and test the domain package, FastAPI service, React frontend, voice path,
  authenticated Hermes path, and persistence boundaries affected by the change.
- Sync tracked source only. Never overwrite either database, runtime `.env`,
  virtual environment, uploaded documents, credentials, or machine-generated data.
- Prefer the installed systemd services. If they are not installed and sudo is
  unavailable, use the documented user-owned process fallback and report that
  operational limitation explicitly.
- A deployment is not complete until the remote revision is identified, API and
  frontend health checks pass, catalog/state separation is visible in health
  output, and the changed user flow has been exercised through the served UI.
- Handoff must include the commit/branch, validation commands and outcomes,
  deployed URLs, service mode (systemd or user-owned), and any remaining manual
  operator step.

## Hermes usage

- Configuration comes from `HERMES_BASE_URL`, `HERMES_API_KEY`, and `HERMES_MODEL`.
- Do not log request headers or the API key.
- Do not silently fall back to a hosted model.
- Treat model output as untrusted input until validated against a schema or rule.
- Keep prompts free of real patient information unless a separately approved data
  handling path exists.

## Definition of done

A judge can watch ABYSS transform the seeded request into a personalized coverage
decision and verified sandbox appointment, with quantified savings, visible sources,
and explicit approval for every material action.
