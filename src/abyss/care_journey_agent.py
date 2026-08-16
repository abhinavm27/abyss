"""Bounded supervisor for routing messages across a user's care journeys.

The model may classify intent and propose a plan.  It cannot mutate state,
choose an insurance plan, calculate costs, grant consent, or execute actions.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from .agent import AgentOutputError, extract_explicit_facts
from .hermes_client import HermesClient


class JourneyIntent(StrEnum):
    NEW_CARE_REQUEST = "new_care_request"
    CONTINUE_JOURNEY = "continue_journey"
    RESCHEDULE_APPOINTMENT = "reschedule_appointment"
    JOURNEY_STATUS = "journey_status"
    LIST_JOURNEYS = "list_journeys"
    COMPARE_PLANS = "compare_plans"
    FIND_PLANS = "find_plans"
    UNKNOWN = "unknown"


class JourneyPlanningModel(Protocol):
    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str: ...


@dataclass(frozen=True, slots=True)
class JourneyPlan:
    intent: JourneyIntent
    correlation_id: str
    utterance_id: str
    target_journey_id: str | None
    target_appointment_id: str | None
    steps: tuple[str, ...]
    reuse: tuple[str, ...]
    refresh: tuple[str, ...]
    missing: tuple[str, ...]
    source: str
    confidence: float
    attempt_count: int = 1
    normalizations: tuple[str, ...] = ()
    validation_errors: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "intent": self.intent.value,
            "correlation_id": self.correlation_id,
            "utterance_id": self.utterance_id,
            "target_journey_id": self.target_journey_id,
            "target_appointment_id": self.target_appointment_id,
            "steps": list(self.steps),
            "reuse": list(self.reuse),
            "refresh": list(self.refresh),
            "missing": list(self.missing),
            "source": self.source,
            "confidence": self.confidence,
            "attempt_count": self.attempt_count,
            "normalizations": list(self.normalizations),
            "validation_errors": list(self.validation_errors),
        }


SUPERVISOR_PROMPT = """You are the bounded ABYSS Care Journey Agent.
Classify the user's message using only the supplied synthetic user-care context.
Return only JSON with these exact keys:
intent, target_journey_id, target_appointment_id, steps, reuse, refresh, missing.
intent must be one of new_care_request, continue_journey,
reschedule_appointment, journey_status, list_journeys, compare_plans, find_plans,
unknown.
Use only journey and appointment IDs present in context. Plan read-only or
permissioned steps; never claim an action was completed, never grant consent,
never choose coverage, and never provide medical advice.
Use JSON null when there is no target ID. steps, reuse, refresh, and missing
must always be JSON arrays, including when they are empty. A request to book or
arrange a different kind of care is new_care_request even when another journey
is active. Resolve short replies against the active journey's pending_questions
and intake_facts. If the message answers a pending question, use
continue_journey and target that journey. Use journey_status only when the user
is actually asking for status; words that are part of a procedure description,
such as "complete" in "abdominal ultrasound, complete", are not status requests.
Use compare_plans when the user asks to compare cost, price, or coverage across
their insurance plans — for example "compare my plans", "which plan is
cheaper", or "what would this cost on my other plan". This only requests a
comparison; it never selects a plan, states a price, or invents a second plan
that was not already uploaded.
Use find_plans when the user asks to find, browse, or see available insurance
plans in general — for example "show me some insurance plans", "what plans are
available", or "find me a marketplace plan in Texas". This only lists real or
clearly-labeled sample plan options; it never selects, links, or activates a
plan for the member."""


class CareJourneyAgent:
    """Classifies and plans; deterministic application code executes the plan."""

    def __init__(self, client: HermesClient | JourneyPlanningModel | None = None) -> None:
        self.client = client

    @staticmethod
    def pending_reply_plan(
        context: dict,
        active_journey_id: str | None,
        *,
        utterance_id: str,
        correlation_id: str,
    ) -> JourneyPlan | None:
        """Correlate an explicit UI reply with its open intake question.

        This is transport/orchestration state, not semantic interpretation. The
        Onboarding Agent still extracts the answer and the deterministic catalog
        still validates it. Requests without an exact active pending journey go
        through normal model planning.
        """
        if not active_journey_id:
            return None
        active = next(
            (
                item for item in context.get("journeys", [])
                if item.get("journey_id") == active_journey_id
            ),
            None,
        )
        if not active or active.get("stage") != "intake" or not active.get("pending_fields"):
            return None
        return JourneyPlan(
            intent=JourneyIntent.CONTINUE_JOURNEY,
            correlation_id=correlation_id,
            utterance_id=utterance_id,
            target_journey_id=active_journey_id,
            target_appointment_id=None,
            steps=("extract_pending_answer", "refresh_intake_state"),
            reuse=("pending_questions", "intake_facts"),
            refresh=("pending_fields",),
            missing=(),
            source="explicit_pending_reply",
            confidence=1.0,
        )

    @classmethod
    def explicit_pending_reply_plan(
        cls,
        text: str,
        context: dict,
        active_journey_id: str | None,
        *,
        utterance_id: str,
        correlation_id: str,
    ) -> JourneyPlan | None:
        """Use the low-latency path only for a source-backed spoken answer.

        Voice has no button metadata proving that an utterance answers the open
        question. A narrow deterministic extraction check keeps ambiguous
        speech on the normal Hermes planning path while exact intake details
        avoid an unnecessary model round trip.
        """
        plan = cls.pending_reply_plan(
            context,
            active_journey_id,
            utterance_id=utterance_id,
            correlation_id=correlation_id,
        )
        if plan is None:
            return None
        facts = extract_explicit_facts(text, source="voice_transcript")
        return plan if facts else None

    @staticmethod
    def explicit_new_care_plan(
        text: str,
        *,
        utterance_id: str,
        correlation_id: str,
    ) -> JourneyPlan | None:
        """Skip semantic replanning for an unmistakable literal care request.

        This only classifies transport intent. Onboarding records literal user
        facts and the deterministic procedure catalog decides whether a code
        can be resolved or a clarification is required. Existing-care actions
        remain with Hermes because they require journey selection.
        """
        normalized = " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())
        tokens = set(normalized.split())
        care_terms = {"mri", "ultrasound", "xray", "ct", "blood", "cbc", "lab"}
        request_terms = {
            "appointment", "book", "schedule", "scan", "test", "care",
            "check", "need", "want", "find", "arrange",
        }
        existing_action_terms = {
            "reschedule", "move", "cancel", "status", "existing", "confirmed",
        }
        if not (tokens & care_terms and tokens & request_terms):
            return None
        if tokens & existing_action_terms or "my appointment" in normalized:
            return None
        return JourneyPlan(
            intent=JourneyIntent.NEW_CARE_REQUEST,
            correlation_id=correlation_id,
            utterance_id=utterance_id,
            target_journey_id=None,
            target_appointment_id=None,
            steps=("start_journey", "extract_literal_facts", "resolve_procedure"),
            reuse=("member_profile", "current_plan"),
            refresh=("procedure_resolution", "pending_fields"),
            missing=(),
            source="explicit_new_care_request",
            confidence=1.0,
        )

    def plan(
        self,
        text: str,
        *,
        context: dict,
        active_journey_id: str | None = None,
        utterance_id: str | None = None,
        correlation_id: str | None = None,
    ) -> JourneyPlan:
        if not text.strip():
            raise ValueError("a user message is required")
        utterance = utterance_id or f"utterance-{uuid.uuid4().hex[:12]}"
        correlation = correlation_id or f"correlation-{uuid.uuid4().hex[:12]}"
        client = self.client or HermesClient()
        messages = [
            {"role": "system", "content": SUPERVISOR_PROMPT},
            {"role": "user", "content": json.dumps({
                "message": text.strip(),
                "active_journey_id": active_journey_id,
                "user_care_context": context,
            }, separators=(",", ":"), default=str)},
        ]
        errors: list[str] = []
        all_normalizations: list[str] = []
        for attempt in range(1, 3):
            raw = client.chat(messages, max_tokens=350, temperature=0.0)
            try:
                payload, normalizations = self._parse_and_normalize(raw)
                all_normalizations.extend(normalizations)
                return self._validate(
                    payload, context, utterance, correlation,
                    "hermes" if attempt == 1 else "hermes_schema_retry",
                    0.9 if attempt == 1 else 0.8,
                    attempt_count=attempt,
                    normalizations=tuple(all_normalizations),
                    validation_errors=tuple(errors),
                )
            except (AgentOutputError, ValueError, TypeError, json.JSONDecodeError) as exc:
                errors.append(str(exc))
                if attempt == 1:
                    messages.extend([
                        {"role": "assistant", "content": raw},
                        {"role": "user", "content": (
                            "Your prior answer could not be accepted: "
                            f"{exc}. Return the corrected JSON object only. "
                            "Use null for absent IDs and arrays for steps, reuse, "
                            "refresh, and missing."
                        )},
                    ])

        # Invalid model formatting must never cause an unrelated journey to be
        # selected. Ask the user to clarify and preserve structural diagnostics.
        payload = {
            "intent": JourneyIntent.UNKNOWN.value,
            "target_journey_id": None,
            "target_appointment_id": None,
            "steps": ["ask_clarification"],
            "reuse": [],
            "refresh": [],
            "missing": ["intent"],
        }
        return self._validate(
            payload, context, utterance, correlation,
            "safe_clarification", 0.0,
            attempt_count=2,
            normalizations=tuple(all_normalizations),
            validation_errors=tuple(errors),
        )

    @classmethod
    def _parse_and_normalize(cls, raw: str) -> tuple[dict, tuple[str, ...]]:
        candidate = raw.strip()
        if not candidate.startswith("{"):
            start, end = candidate.find("{"), candidate.rfind("}")
            if start < 0 or end < start:
                raise AgentOutputError("Care Journey Agent did not return JSON")
            candidate = candidate[start:end + 1]
        payload = json.loads(candidate)
        if not isinstance(payload, dict):
            raise AgentOutputError("Care Journey Agent did not return a JSON object")
        expected = {
            "intent", "target_journey_id", "target_appointment_id", "steps",
            "reuse", "refresh", "missing",
        }
        if set(payload) - expected or "intent" not in payload:
            raise AgentOutputError("Care Journey Agent returned an invalid schema")
        normalized = {name: payload.get(name) for name in expected}
        changes: list[str] = []
        for name in ("target_journey_id", "target_appointment_id"):
            if isinstance(normalized[name], str) and not normalized[name].strip():
                normalized[name] = None
                changes.append(f"{name}:empty_string_to_null")
        for name in ("steps", "reuse", "refresh", "missing"):
            if normalized[name] is None or normalized[name] is False:
                normalized[name] = []
                changes.append(f"{name}:empty_value_to_array")
        return normalized, tuple(changes)

    @staticmethod
    def _validate(
        payload: dict,
        context: dict,
        utterance_id: str,
        correlation_id: str,
        source: str,
        confidence: float,
        *,
        attempt_count: int = 1,
        normalizations: tuple[str, ...] = (),
        validation_errors: tuple[str, ...] = (),
    ) -> JourneyPlan:
        try:
            intent = JourneyIntent(str(payload["intent"]))
            collections = ("steps", "reuse", "refresh", "missing")
            if any(not isinstance(payload[name], list) for name in collections):
                raise TypeError
            valid_journeys = {item.get("journey_id") for item in context.get("journeys", [])}
            appointment_map = {
                item.get("appointment_id"): item
                for item in context.get("appointments", [])
            }
            valid_appointments = set(appointment_map)
            journey_id = payload.get("target_journey_id")
            appointment_id = payload.get("target_appointment_id")
            if intent == JourneyIntent.NEW_CARE_REQUEST and (
                journey_id is not None or appointment_id is not None
            ):
                raise ValueError("a new care request cannot target an existing journey")
            if intent == JourneyIntent.CONTINUE_JOURNEY and journey_id is None:
                raise ValueError("continuing care requires a target journey")
            if intent == JourneyIntent.RESCHEDULE_APPOINTMENT and appointment_id is None:
                raise ValueError("rescheduling requires a target appointment")
            if journey_id is not None and journey_id not in valid_journeys:
                raise ValueError("agent referenced an unauthorized journey")
            if appointment_id is not None and appointment_id not in valid_appointments:
                raise ValueError("agent referenced an unauthorized appointment")
            if appointment_id is not None:
                appointment_journey = appointment_map[appointment_id].get("journey_id")
                if journey_id is None:
                    journey_id = appointment_journey
                elif appointment_journey != journey_id:
                    raise ValueError("appointment does not belong to the target journey")
        except (KeyError, TypeError, ValueError) as exc:
            raise AgentOutputError("Care Journey Agent plan failed validation") from exc
        return JourneyPlan(
            intent, correlation_id, utterance_id, journey_id, appointment_id,
            tuple(map(str, payload["steps"])), tuple(map(str, payload["reuse"])),
            tuple(map(str, payload["refresh"])), tuple(map(str, payload["missing"])),
            source, confidence, attempt_count, normalizations, validation_errors,
        )
