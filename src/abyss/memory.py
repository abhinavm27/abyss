"""Versioned fact and user-memory ledger with explicit provenance."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from .domain import DecisionFact, VerificationStatus


@dataclass(frozen=True, slots=True)
class UserMemoryRecord:
    user_id: str
    fact_id: str
    version: int
    fact: DecisionFact
    effective_at: datetime | None = None
    ends_at: datetime | None = None
    superseded_by: str | None = None


class FactLedger:
    def __init__(self) -> None:
        self._records: list[UserMemoryRecord] = []

    def append(self, user_id: str, fact_id: str, fact: DecisionFact, *, effective_at: datetime | None = None) -> UserMemoryRecord:
        previous = [record for record in self._records if record.user_id == user_id and record.fact.name == fact.name]
        record = UserMemoryRecord(user_id, fact_id, len(previous) + 1, fact, effective_at)
        self._records.append(record)
        return record

    def records(self, user_id: str) -> tuple[UserMemoryRecord, ...]:
        return tuple(record for record in self._records if record.user_id == user_id)

    def current(self, user_id: str, name: str) -> UserMemoryRecord | None:
        matches = [record for record in self.records(user_id) if record.fact.name == name and record.superseded_by is None]
        return matches[-1] if matches else None

    def mark_verified(self, fact_id: str) -> UserMemoryRecord:
        for index, record in enumerate(self._records):
            if record.fact_id == fact_id:
                verified = DecisionFact(record.fact.name, record.fact.value, record.fact.source,
                                        record.fact.observed_at, record.fact.confidence,
                                        VerificationStatus.VERIFIED, record.fact.consent_required)
                updated = UserMemoryRecord(record.user_id, record.fact_id, record.version, verified,
                                           record.effective_at, record.ends_at, record.superseded_by)
                self._records[index] = updated
                return updated
        raise KeyError(fact_id)
