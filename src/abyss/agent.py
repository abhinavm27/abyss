"""Hermes adapter for explanations grounded in ABYSS-computed evidence."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from .domain import ConsentAction, DecisionFact, VerificationStatus
from .hermes_client import HermesClient

SYSTEM_PROMPT = """You are Hermes, the explanation layer inside ABYSS.
Use only the structured evidence supplied with the question. Never invent,
recalculate, or guarantee a price, eligibility result, benefit, appointment,
or coverage change. Clearly distinguish estimates from verified facts. State
when evidence is missing. Do not provide medical advice. Keep the answer short,
plain-spoken, and suitable for a non-technical user."""

EXTRACTION_PROMPT = """You are the ABYSS onboarding extraction layer.
Extract only facts explicitly present in the supplied synthetic text. Return
JSON with exactly one top-level key, facts. Each fact must contain name,
value, source, confidence, and observed_at. confidence must be a number from
0.0 through 1.0. Do not decide eligibility, cost,
network status, or consent. Use these exact names when applicable:
requested_procedure, service_date, coverage_end_date, contrast_status.
When existing intake facts are supplied, treat the latest text as the next turn
in that conversation. Merge body area, modality, and modifiers into a complete
requested_procedure instead of replacing it with a fragment. For example,
existing "ultrasound scan" plus "abdomen complete" means
"complete abdominal ultrasound".
Do not provide medical advice."""


class AgentOutputError(ValueError):
    """The model returned output that is not safe to use."""


def _confidence_value(value: Any) -> float:
    """Normalize common model confidence encodings into the ledger contract."""
    if isinstance(value, str):
        normalized = value.strip().lower()
        labels = {"high": 0.9, "medium": 0.6, "moderate": 0.6, "low": 0.3}
        if normalized in labels:
            return labels[normalized]
        if normalized.endswith("%"):
            return float(normalized[:-1]) / 100.0
    return float(value)


def _explicit_intake_fallback(
    text: str, *, source: str, observed_at: datetime
) -> list[DecisionFact]:
    """Recover only narrow, explicit seeded facts when model JSON is unusable."""
    lowered = " ".join(text.lower().split())
    normalized = lowered.replace("-", " ")
    values: list[tuple[str, Any]] = []
    if "mri" in normalized and "knee" in normalized:
        procedure = "MRI knee"
        if "without contrast" in normalized or "no contrast" in normalized:
            procedure += " without contrast"
        elif "with contrast" in normalized:
            procedure += " with contrast"
        values.append(("requested_procedure", procedure))
    elif "mri" in normalized:
        values.append(("requested_procedure", "MRI"))
    elif (
        "ultrasound" in normalized
        and not ("complete" in normalized and ("abdomen" in normalized or "abdominal" in normalized))
    ):
        values.append(("requested_procedure", "ultrasound"))
    elif (
        ("blood test" in normalized or "lab test" in normalized)
        and not (
            ("cbc" in normalized or "complete blood count" in normalized)
            and ("differential" in normalized or " diff" in normalized)
        )
    ):
        values.append(("requested_procedure", "blood test"))

    iso_dates = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", text)
    month_pattern = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+\d{1,2}(?:,\s*\d{4})?"
    natural_dates = re.findall(rf"\b{month_pattern}\b", lowered)
    coverage_match = re.search(
        r"(?:coverage|plan)\s+(?:ends?|end(?:s|ing)?(?:\s+date)?(?:\s+is)?)\s+(\d{4}-\d{2}-\d{2})",
        lowered,
    )
    service_match = re.search(
        rf"(?:service|care|appointment)\s+date(?:\s+is)?\s+(\d{{4}}-\d{{2}}-\d{{2}}|{month_pattern})",
        lowered,
    )
    natural_coverage_match = re.search(
        rf"(?:coverage|plan)\s+(?:ends?|end(?:s|ing)?(?:\s+date)?(?:\s+is)?)\s+({month_pattern})",
        lowered,
    )
    coverage_date = coverage_match.group(1) if coverage_match else None
    if not coverage_date and natural_coverage_match:
        coverage_date = natural_coverage_match.group(1)
    service_date = service_match.group(1) if service_match else None
    if not service_date:
        service_date = next((value for value in iso_dates if value != coverage_date), None)
    if not service_date:
        service_date = next((value for value in natural_dates if value != coverage_date), None)
    if service_date:
        values.append(("service_date", service_date))
    if coverage_date:
        values.append(("coverage_end_date", coverage_date))
    if "without contrast" in normalized or "no contrast" in normalized:
        values.append(("contrast_status", "without contrast"))
    elif "with contrast" in normalized:
        values.append(("contrast_status", "with contrast"))

    return [
        DecisionFact(
            name=name,
            value=value,
            source=source,
            observed_at=observed_at,
            confidence=1.0,
            verification_status=VerificationStatus.SOURCE_BACKED,
            consent_required=ConsentAction.PROCESS_DOCUMENTS,
        )
        for name, value in values
    ]


def extract_explicit_facts(
    text: str, *, source: str, observed_at: datetime | None = None
) -> list[DecisionFact]:
    """Extract only narrow source-backed phrases that need no interpretation."""
    if not text.strip() or not source.strip():
        raise ValueError("text and source are required")
    timestamp = observed_at or datetime.now(UTC)
    facts = _explicit_intake_fallback(
        text,
        source=source,
        observed_at=timestamp,
    )
    normalized = " ".join(text.lower().replace("-", " ").split())
    procedure: str | None = None
    if (
        ("cbc" in normalized or "complete blood count" in normalized)
        and ("differential" in normalized or " diff" in normalized)
    ):
        procedure = "Complete blood count with differential"
    elif (
        "ultrasound" in normalized
        and "complete" in normalized
        and ("abdomen" in normalized or "abdominal" in normalized)
    ):
        procedure = "Complete abdominal ultrasound"
    if procedure and not any(fact.name == "requested_procedure" for fact in facts):
        facts.insert(0, DecisionFact(
            name="requested_procedure",
            value=procedure,
            source=source,
            observed_at=timestamp,
            confidence=1.0,
            verification_status=VerificationStatus.SOURCE_BACKED,
            consent_required=ConsentAction.PROCESS_DOCUMENTS,
        ))
    return facts


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


def extract_facts(text: str, *, source: str, observed_at: datetime | None = None,
                  context: dict[str, Any] | None = None,
                  client: HermesClient | None = None) -> list[DecisionFact]:
    """Extract candidate facts; deterministic validation makes them usable."""
    if not text.strip() or not source.strip():
        raise ValueError("text and source are required")
    timestamp = observed_at or datetime.now(UTC)
    hermes = client or HermesClient()
    messages = [
        {"role": "system", "content": EXTRACTION_PROMPT},
        {"role": "user", "content": (
            f"Source: {source}\n"
            "Existing synthetic intake context:\n"
            f"{json.dumps(context or {}, separators=(',', ':'), default=str)}\n"
            f"Latest user text:\n{text.strip()}"
        )},
    ]
    raw = hermes.chat(messages, max_tokens=500, temperature=0.0)
    try:
        candidate = raw.strip()
        if not candidate.startswith("{"):
            start, end = candidate.find("{"), candidate.rfind("}")
            if start < 0 or end <= start:
                raise json.JSONDecodeError("JSON object not found", candidate, 0)
            candidate = candidate[start:end + 1]
        payload = json.loads(candidate)
        entries = payload["facts"]
        if not isinstance(entries, list):
            raise TypeError
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        fallback = _explicit_intake_fallback(text, source=source, observed_at=timestamp)
        if fallback:
            return fallback
        # One bounded correction gives a model that wrapped or omitted JSON a
        # chance to comply. The corrected output is still treated as untrusted
        # and goes through the exact same schema and DecisionFact validation.
        corrected = hermes.chat(messages + [
            {"role": "assistant", "content": raw},
            {"role": "user", "content": (
                "Your response did not match the required schema. Return only "
                "a JSON object with exactly one top-level facts array. Each "
                "fact must contain name, value, source, confidence, and observed_at."
            )},
        ], max_tokens=500, temperature=0.0)
        try:
            candidate = corrected.strip()
            if not candidate.startswith("{"):
                start, end = candidate.find("{"), candidate.rfind("}")
                if start < 0 or end <= start:
                    raise json.JSONDecodeError("JSON object not found", candidate, 0)
                candidate = candidate[start:end + 1]
            payload = json.loads(candidate)
            entries = payload["facts"]
            if not isinstance(entries, list):
                raise TypeError
        except (json.JSONDecodeError, KeyError, TypeError) as retry_error:
            raise AgentOutputError("Hermes extraction did not return the required JSON schema") from retry_error
    facts: list[DecisionFact] = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) - {"name", "value", "source", "confidence", "observed_at"}:
            raise AgentOutputError("Hermes extraction contains unknown or malformed fields")
        try:
            facts.append(DecisionFact(
                name=str(entry["name"]), value=entry["value"], source=source,
                # Provenance time belongs to the orchestrator, never the model.
                # The model field is accepted for schema compatibility but is
                # intentionally not trusted as the ledger timestamp.
                observed_at=timestamp,
                confidence=_confidence_value(entry["confidence"]), verification_status=VerificationStatus.INFERRED,
                consent_required=ConsentAction.PROCESS_DOCUMENTS,
            ))
        except (KeyError, TypeError, ValueError) as error:
            fallback = _explicit_intake_fallback(text, source=source, observed_at=timestamp)
            if fallback:
                return fallback
            raise AgentOutputError("Hermes extraction contains an invalid fact") from error
    explicit = _explicit_intake_fallback(text, source=source, observed_at=timestamp)
    names = {fact.name for fact in facts}
    facts.extend(fact for fact in explicit if fact.name not in names)
    return facts
