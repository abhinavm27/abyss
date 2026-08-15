# ABYSS

ABYSS is a permissioned healthcare-navigation prototype for NVIDIA Spark Hack
Seattle. It turns a request for care into an evidence-backed coverage decision
and a sandboxed appointment booking workflow.

> **Prototype boundary:** ABYSS does not provide medical advice, perform real
> insurance enrollment, guarantee prices, or change coverage without explicit
> approval. The weekend demo uses controlled data and sandbox execution.

## Golden path

1. Read a seeded insurance card and MRI referral.
2. Build a Personal Care Twin with facts, sources, confidence, and consent state.
3. Compare the current plan with two eligible Washington alternatives.
4. Rank complete care paths by expected annual cost and user constraints.
5. Request separate approval for enrollment and coverage transition.
6. Verify a selected imaging provider through a controlled voice endpoint.
7. Book the MRI in a sandbox and show savings, evidence, and consent history.

## Architecture

```text
Codex / Claude Code / ABYSS app
              |
              | OpenAI-compatible API over a private SSH tunnel
              v
      NemoClaw Hermes gateway (GN100)
              |
              | https://inference.local
              v
  vLLM + nvidia/Qwen3.6-35B-A3B-NVFP4 (GB10 GPU)
```

NemoClaw is the trust boundary. Clients do not call vLLM on port 8000 directly,
and the repository never stores the Hermes bearer token, GN100 password, patient
documents, or private SSH keys.

## Start here

1. Read [docs/PROJECT_BRIEF.md](docs/PROJECT_BRIEF.md).
2. Read [docs/SECURITY.md](docs/SECURITY.md) before handling any document.
3. Follow [docs/HERMES_CONNECTION.md](docs/HERMES_CONNECTION.md) to connect.
4. Copy `.env.example` to `.env` and populate secrets only in your local shell or
   ignored `.env` file.
5. Run the connectivity check:

   ```bash
   PYTHONPATH=src python3 -m abyss.cli
   ```

6. Run tests:

   ```bash
   PYTHONPATH=src python3 -m unittest discover -s tests -v
   ```

## Repository map

```text
AGENTS.md                  Codex operating contract
CLAUDE.md                  Claude Code operating contract
docs/                      Product, architecture, security, and demo truth
src/abyss/hermes_client.py Authenticated client for the NemoClaw gateway
src/abyss/domain.py        Shared fact, consent, and care-state contracts
src/abyss/workflow.py      Permissioned golden-path state machine
scripts/tunnel-hermes.sh   Private GN100 dashboard/API forwarding
tests/                     Deterministic unit tests; no live PHI or credentials
```

## Current infrastructure

- Host: Acer Veriton GN100 / NVIDIA GB10
- Tailscale node: `gn100-75f8`
- NemoClaw sandbox: `hermes`
- Hermes dashboard remote port: `18791`
- Hermes API remote port: `8642`
- Local model: `nvidia/Qwen3.6-35B-A3B-NVFP4`

These are defaults, not secrets. Each collaborator needs their own authorized
Tailscale identity and SSH access.
