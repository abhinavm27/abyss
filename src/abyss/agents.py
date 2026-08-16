"""Bounded ABYSS agent roles.

These are orchestration boundaries, not autonomous authorities. Every result is
validated data that the CareJourney or deterministic engine must still accept.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .agent import AgentOutputError, explain, extract_explicit_facts, extract_facts
from .domain import DecisionFact
from .evaluation import PathEvaluation
from .hermes_client import HermesClient
from .procedures import ProcedureResolution


class ChatModel(Protocol):
    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str: ...


@dataclass(frozen=True, slots=True)
class FactProposal:
    facts: tuple[DecisionFact, ...]
    missing: tuple[str, ...] = ()
    questions: tuple[str, ...] = ()


class OnboardingAgent:
    """Extracts candidate facts; it cannot verify or decide."""

    def __init__(self, client: HermesClient | ChatModel | None = None) -> None:
        self.client = client

    def extract(
        self,
        text: str,
        *,
        source: str,
        context: dict[str, Any] | None = None,
        prefer_explicit: bool = False,
    ) -> FactProposal:
        facts = extract_explicit_facts(text, source=source) if prefer_explicit else []
        if not facts:
            facts = extract_facts(
                text, source=source, context=context, client=self.client
            )  # type: ignore[arg-type]
        names = {fact.name for fact in facts}
        # service_date and coverage_end_date are still extracted and recorded
        # when a member volunteers them, but neither gates intake: service_date
        # already has a hardcoded booking fallback, and coverage_end_date has
        # no downstream consumer — SEP eligibility is a seeded plan-catalog
        # boolean, not computed from this date. Requiring them just added
        # questions that bought nothing.
        required = {
            "requested_procedure": "What care or procedure are you trying to arrange?",
        }
        missing = tuple(name for name in required if name not in names)
        return FactProposal(tuple(facts), missing, tuple(required[name] for name in missing))


class KnowledgeAgent:
    """Explains an engine result without changing it."""

    def __init__(self, client: HermesClient | ChatModel | None = None) -> None:
        self.client = client

    def explain_result(self, evaluations: list[PathEvaluation], *, question: str) -> str:
        evidence = {
            "evaluations": [
                {"plan_id": item.plan_id, "plan_name": item.plan_name, "feasible": item.feasible,
                 "annual_total": item.annual_total, "hard_failures": list(item.hard_failures)}
                for item in evaluations
            ]
        }
        return explain(question, evidence, client=self.client)  # type: ignore[arg-type]

    def propose_procedure(self, phrase: str, *, confirmed_code: str | None = None) -> ProcedureResolution:
        """Return a catalog candidate; deterministic catalog remains authoritative."""
        from .procedures import ProcedureCatalog
        return ProcedureCatalog().resolve(phrase, confirmed_code=confirmed_code)


@dataclass(frozen=True, slots=True)
class MatchingRequest:
    plan_ids: tuple[str, ...]
    provider_id: str


class MatchingAgent:
    """Requests deterministic evaluation; it has no ranking authority."""

    def __init__(self, client: HermesClient | ChatModel | None = None) -> None:
        self.client = client

    def request_evaluation(self, plan_ids: list[str], *, provider_id: str) -> MatchingRequest:
        if not plan_ids or not provider_id.strip():
            raise ValueError("plan_ids and provider_id are required")
        return MatchingRequest(tuple(plan_ids), provider_id)

    def reason_about_evaluation(
        self,
        evaluations: list[PathEvaluation],
        *,
        question: str,
        care_path_context: dict[str, Any] | None = None,
    ) -> str:
        """Ask Nemotron to explain deterministic outcomes, never to choose them."""
        if not evaluations:
            raise ValueError("evaluations are required")
        evidence = {
            "authority": "deterministic_engine",
            "evaluations": [
                {"plan_id": item.plan_id, "plan_name": item.plan_name, "feasible": item.feasible,
                 "annual_total": item.annual_total, "hard_failures": list(item.hard_failures)}
                for item in evaluations
            ],
        }
        if care_path_context is not None:
            evidence["care_path_context"] = care_path_context
        return explain(question, evidence, client=self.client)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class BookingProposal:
    provider_id: str
    facility_id: str
    date: str
    time: str
    consent_scope: str


class SchedulerAgent:
    """Prepares a booking proposal; the engine must execute it after consent."""

    def propose(self, *, provider_id: str, facility_id: str, date: str, time: str) -> BookingProposal:
        for value in (provider_id, facility_id, date, time):
            if not value.strip():
                raise ValueError("booking proposal fields are required")
        scope = f"{provider_id} / {facility_id} / {date} {time}"
        return BookingProposal(provider_id, facility_id, date, time, scope)


class ReviewAgent:
    """Produces a read-only summary of already recorded journey evidence."""

    def summarize(self, *, stage: str, events: list[dict[str, Any]], receipts: list[dict[str, Any]]) -> dict[str, Any]:
        return {"stage": stage, "event_count": len(events), "receipt_count": len(receipts), "events": events, "receipts": receipts}


class VoiceInboxAgent:
    """Converts channel text to a closed intent; it never invokes tools."""

    ALLOWED_INTENTS = frozenset({"compare_coverage_for_care", "explain_recommendation", "approve_action"})

    def normalize(self, *, intent: str, text: str) -> dict[str, str]:
        if intent not in self.ALLOWED_INTENTS:
            raise AgentOutputError("voice/inbox intent is not allowed")
        if not text.strip():
            raise ValueError("voice/inbox text is required")
        return {"intent": intent, "text": text.strip()}
