"""Redacted, append-only journey events for receipts and audit history."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class JourneyEvent:
    sequence: int
    journey_id: str
    event_type: str
    actor: str
    payload: dict[str, Any]
    recorded_at: datetime


class AuditLedger:
    def __init__(self) -> None:
        self._events: list[JourneyEvent] = []

    def append(self, journey_id: str, event_type: str, *, actor: str, payload: dict[str, Any] | None = None) -> JourneyEvent:
        safe_payload = {key: value for key, value in (payload or {}).items() if key not in {"api_key", "authorization", "raw_document"}}
        event = JourneyEvent(len(self._events) + 1, journey_id, event_type, actor, safe_payload, datetime.now(UTC))
        self._events.append(event)
        return event

    def for_journey(self, journey_id: str) -> tuple[JourneyEvent, ...]:
        return tuple(event for event in self._events if event.journey_id == journey_id)
