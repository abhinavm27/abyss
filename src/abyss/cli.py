"""Connectivity check for the ABYSS Hermes gateway."""

from __future__ import annotations

import sys

from .hermes_client import HermesClient, HermesError


def main() -> int:
    try:
        reply = HermesClient().chat(
            [{"role": "user", "content": "Reply with exactly: ABYSS HERMES READY"}],
            max_tokens=128,
        )
    except (HermesError, ValueError) as error:
        print(f"Hermes check failed: {error}", file=sys.stderr)
        return 1

    print(reply)
    return 0 if reply.strip() == "ABYSS HERMES READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())

