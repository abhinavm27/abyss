"""Shared, deterministic domain contracts for ABYSS."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class VerificationStatus(StrEnum):
    UNKNOWN = "unknown"
    INFERRED = "inferred"
    SOURCE_BACKED = "source_backed"
    VERIFIED = "verified"
    CONFLICTING = "conflicting"


class ConsentAction(StrEnum):
    PROCESS_DOCUMENTS = "process_documents"
    ENROLL_PLAN = "enroll_plan"
    TRANSITION_COVERAGE = "transition_coverage"
    SHARE_WITH_PROVIDER = "share_with_provider"
    BOOK_APPOINTMENT = "book_appointment"


@dataclass(frozen=True, slots=True)
class DecisionFact:
    """A fact cannot enter a decision without provenance and uncertainty."""

    name: str
    value: Any
    source: str
    observed_at: datetime
    confidence: float
    verification_status: VerificationStatus
    consent_required: ConsentAction | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("fact name is required")
        if not self.source.strip():
            raise ValueError("fact source is required")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class ConsentRecord:
    action: ConsentAction
    approved: bool
    actor: str
    recorded_at: datetime
    scope: str

    def __post_init__(self) -> None:
        if not self.actor.strip() or not self.scope.strip():
            raise ValueError("consent actor and scope are required")
        if self.recorded_at.tzinfo is None:
            raise ValueError("recorded_at must be timezone-aware")


@dataclass(slots=True)
class CareState:
    session_id: str
    facts: dict[str, DecisionFact] = field(default_factory=dict)
    consents: list[ConsentRecord] = field(default_factory=list)

    def add_fact(self, fact: DecisionFact) -> None:
        self.facts[fact.name] = fact

    def record_consent(
        self,
        action: ConsentAction,
        *,
        approved: bool,
        actor: str,
        scope: str,
        recorded_at: datetime | None = None,
    ) -> ConsentRecord:
        record = ConsentRecord(
            action=action,
            approved=approved,
            actor=actor,
            scope=scope,
            recorded_at=recorded_at or datetime.now(UTC),
        )
        self.consents.append(record)
        return record

    def has_consent(self, action: ConsentAction, scope: str | None = None) -> bool:
        matching = [record for record in self.consents if record.action == action]
        if not matching or not matching[-1].approved:
            return False
        return scope is None or matching[-1].scope == scope
