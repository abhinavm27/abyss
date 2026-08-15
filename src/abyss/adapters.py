"""Sandbox-only action adapters with explicit receipts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class ActionReceipt:
    action: str
    status: str
    journey_id: str
    consent_scope: str
    idempotency_key: str
    recorded_at: datetime
    sandbox: bool = True


class SandboxAdapters:
    def __init__(self) -> None:
        self._receipts: dict[str, ActionReceipt] = {}

    def execute(self, action: str, journey_id: str, consent_scope: str, idempotency_key: str) -> ActionReceipt:
        if not action or not consent_scope or not idempotency_key:
            raise ValueError("sandbox action requires action, scope, and idempotency key")
        if idempotency_key in self._receipts:
            return self._receipts[idempotency_key]
        receipt = ActionReceipt(action, "sandbox_confirmed", journey_id, consent_scope,
                                idempotency_key, datetime.now(UTC))
        self._receipts[idempotency_key] = receipt
        return receipt
