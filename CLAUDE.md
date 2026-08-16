# Claude Code guidance for ABYSS

Read `AGENTS.md` first; its safety, consent, data, and engineering rules are binding.

## Context to load

Before implementation work, read:

1. `docs/PROJECT_BRIEF.md`
2. `docs/ARCHITECTURE.md`
3. `docs/SECURITY.md`
4. the relevant module and tests

## Working conventions

- Prefer small vertical changes that keep the golden demo path runnable.
- Ask before changing a domain contract, consent gate, infrastructure address, or
  the boundary between working and sandboxed actions.
- Put deterministic healthcare-cost and eligibility logic in normal Python code,
  never only in prompts.
- Use `abyss.hermes_client.HermesClient` for model calls. Never call vLLM directly.
- Report assumptions and unresolved data rather than filling gaps with plausible text.
- Run the unit tests before claiming completion.

## Commands

Use `.venv/bin/python` and include `services/api` on the path — bare `python3`
lacks FastAPI and silently skips 9 tests (messaging, Discord, voice-WS, journey
start) instead of running them.

```bash
PYTHONPATH=src:services/api .venv/bin/python -m unittest discover -s tests -v
PYTHONPATH=src python3 -m abyss.cli
```
