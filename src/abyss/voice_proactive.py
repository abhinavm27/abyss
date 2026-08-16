"""Grounded opening prompts for an authenticated voice session."""

from __future__ import annotations

from typing import Any


def _care_name(journey: dict[str, Any]) -> str:
    resolution = journey.get("procedure_resolution")
    if isinstance(resolution, dict):
        value = resolution.get("canonical_name")
        if isinstance(value, str) and value.strip():
            return value.strip()
    for fact in journey.get("facts") or []:
        if isinstance(fact, dict) and fact.get("name") == "requested_procedure":
            value = fact.get("value")
            if isinstance(value, str) and value.strip():
                return value.strip()
    return "care"


def proactive_voice_prompt(journey: dict[str, Any] | None) -> str:
    """Return one short next-step prompt using only persisted journey state."""
    if not journey:
        return "Hi, I'm VELA. Tell me what care you need, or ask about an existing appointment."

    care = _care_name(journey)
    stage = str(journey.get("stage") or "intake")
    questions = [
        str(question).strip()
        for question in (journey.get("onboarding_questions") or [])
        if str(question).strip()
    ]
    if stage == "intake" and questions:
        return f"Welcome back. To continue your {care} request, {questions[0]}"
    if stage == "intake":
        return f"Welcome back. I'm ready to continue your {care} request. Tell me what changed or what you need next."
    if stage in {"compare", "recommend"}:
        return f"Your current-plan options for {care} are ready. Ask me to explain them, or choose a hospital to continue."
    if stage == "verify":
        return f"You've selected a care path for {care}. I can explain it before you approve provider and network verification."
    if stage == "book":
        return f"Provider verification for {care} is complete. Tell me your preferred dates and times, and I'll find appointment slots."
    if stage == "complete":
        return f"Your {care} appointment is confirmed. You can ask me to review it or help reschedule it."
    return f"Welcome back. I'm ready to help with {care}. What would you like to do next?"
