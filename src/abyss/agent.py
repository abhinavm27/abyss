"""Hermes adapter for explanations grounded in ABYSS-computed evidence."""

from __future__ import annotations

import json
from typing import Any

from .hermes_client import HermesClient

SYSTEM_PROMPT = """You are Hermes, the explanation layer inside ABYSS.
Use only the structured evidence supplied with the question. Never invent,
recalculate, or guarantee a price, eligibility result, benefit, appointment,
or coverage change. Clearly distinguish estimates from verified facts. State
when evidence is missing. Do not provide medical advice. Keep the answer short,
plain-spoken, and suitable for a non-technical user."""


def explain(question: str, evidence: dict[str, Any], client: HermesClient | None = None) -> str:
    """Explain evidence without delegating calculations or decisions to the model."""
    if not question.strip():
        raise ValueError("question is required")
    hermes = client or HermesClient()
    return hermes.chat(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Question: {question.strip()}\n\n"
                    "ABYSS evidence (authoritative JSON):\n"
                    f"{json.dumps(evidence, sort_keys=True, separators=(',', ':'))}"
                ),
            },
        ],
        max_tokens=320,
        temperature=0.0,
    )
