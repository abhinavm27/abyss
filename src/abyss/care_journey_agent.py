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

from .agent import AgentOutputError
from .hermes_client import HermesClient


class JourneyIntent(StrEnum):
    NEW_CARE_REQUEST = "new_care_request"
    CONTINUE_JOURNEY = "continue_journey"
    RESCHEDULE_APPOINTMENT = "reschedule_appointment"
    JOURNEY_STATUS = "journey_status"
    LIST_JOURNEYS = "list_journeys"
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
        }


SUPERVISOR_PROMPT = """You are the bounded ABYSS Care Journey Agent.
Classify the user's message using only the supplied synthetic user-care context.
Return only JSON with these exact keys:
intent, target_journey_id, target_appointment_id, steps, reuse, refresh, missing.
intent must be one of new_care_request, continue_journey,
reschedule_appointment, journey_status, list_journeys, unknown.
Use only journey and appointment IDs present in context. Plan read-only or
permissioned steps; never claim an action was completed, never grant consent,
never choose coverage, and never provide medical advice."""


class CareJourneyAgent:
    """Classifies and plans; deterministic application code executes the plan."""

    def __init__(self, client: HermesClient | JourneyPlanningModel | None = None) -> None:
        self.client = client

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
        try:
            client = self.client or HermesClient()
            raw = client.chat([
                {"role": "system", "content": SUPERVISOR_PROMPT},
                {"role": "user", "content": json.dumps({
                    "message": text.strip(),
                    "active_journey_id": active_journey_id,
                    "user_care_context": context,
                }, separators=(",", ":"), default=str)},
            ], max_tokens=350, temperature=0.0)
            payload = self._parse(raw)
            return self._validate(
                payload, context, utterance, correlation, "hermes", 0.9
            )
        except (AgentOutputError, ValueError, TypeError, json.JSONDecodeError):
            payload = self._fallback(text, context, active_journey_id)
        return self._validate(
            payload, context, utterance, correlation,
            "deterministic_fallback", 1.0,
        )

    @staticmethod
    def _parse(raw: str) -> dict:
        candidate = raw.strip()
        if not candidate.startswith("{"):
            start, end = candidate.find("{"), candidate.rfind("}")
            if start < 0 or end < start:
                raise AgentOutputError("Care Journey Agent did not return JSON")
            candidate = candidate[start:end + 1]
        payload = json.loads(candidate)
        expected = {
            "intent", "target_journey_id", "target_appointment_id", "steps",
            "reuse", "refresh", "missing",
        }
        if not isinstance(payload, dict) or set(payload) != expected:
            raise AgentOutputError("Care Journey Agent returned an invalid schema")
        return payload

    @staticmethod
    def _fallback(text: str, context: dict, active_journey_id: str | None) -> dict:
        lowered = " ".join(text.lower().split())
        journeys = context.get("journeys", [])
        appointments = context.get("appointments", [])
        target = active_journey_id
        if target not in {item.get("journey_id") for item in journeys}:
            target = journeys[0].get("journey_id") if journeys else None
        appointment = next(
            (item for item in appointments if item.get("journey_id") == target and item.get("status") == "confirmed"),
            next((item for item in appointments if item.get("status") == "confirmed"), None),
        )
        if re.search(r"\b(reschedule|move|change).{0,30}\b(appointment|scan|mri|booking|it)\b", lowered):
            intent = JourneyIntent.RESCHEDULE_APPOINTMENT.value
            target = appointment.get("journey_id") if appointment else target
            steps = ["load_confirmed_appointment", "search_replacement_slots", "request_exact_consents"]
            reuse = ["procedure_code", "selected_care_path", "current_plan", "provider_verification"]
            refresh = ["appointment_availability"]
            missing = [] if appointment else ["confirmed_appointment"]
        elif "list" in lowered and "journey" in lowered or "all my journeys" in lowered:
            intent, steps, reuse, refresh, missing = JourneyIntent.LIST_JOURNEYS.value, ["read_journey_index"], [], [], []
        elif any(term in lowered for term in ("status", "what happened", "where are we")):
            intent, steps, reuse, refresh, missing = JourneyIntent.JOURNEY_STATUS.value, ["read_journey_status"], [], [], []
        elif any(term in lowered for term in ("i need", "i want", "set up", "setup", "arrange")):
            intent, target = JourneyIntent.NEW_CARE_REQUEST.value, None
            steps, reuse, refresh, missing = ["start_journey", "onboard_request"], [], [], []
        elif target:
            intent, steps, reuse, refresh, missing = JourneyIntent.CONTINUE_JOURNEY.value, ["continue_active_stage"], [], [], []
        else:
            intent, steps, reuse, refresh, missing = JourneyIntent.UNKNOWN.value, ["ask_clarification"], [], [], ["intent"]
        return {
            "intent": intent,
            "target_journey_id": target,
            "target_appointment_id": appointment.get("appointment_id") if appointment else None,
            "steps": steps,
            "reuse": reuse,
            "refresh": refresh,
            "missing": missing,
        }

    @staticmethod
    def _validate(
        payload: dict,
        context: dict,
        utterance_id: str,
        correlation_id: str,
        source: str,
        confidence: float,
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
            source, confidence,
        )
