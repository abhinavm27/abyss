"""Consent-gated referral and doctor-report intake for care journeys.

The model is limited to transcribing candidate orders from source text. This
module validates every candidate against an exact quote, derives provenance in
deterministic code, and waits for user confirmation before producing facts that
may be attached to a journey.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from .domain import (
    ConsentAction,
    ConsentRecord,
    DecisionFact,
    VerificationStatus,
)
from .hermes_client import HermesClient


class ReportIntakeError(RuntimeError):
    """The report cannot safely advance through intake."""


class ExactDocumentConsentRequired(ReportIntakeError):
    """Processing consent is missing or does not identify the exact upload."""


class ReportSchemaError(ReportIntakeError):
    """Hermes output failed the deterministic candidate-order schema."""


class ConfirmationRequired(ReportIntakeError):
    """No source-backed order was explicitly confirmed by the user."""


REPORT_ORDER_PROMPT = """Extract only tests, imaging, procedures, or referrals that the
clinician explicitly ordered or listed in the plan, orders, or referral section.

Return one JSON object with exactly this shape:
{"orders":[{"service_name":"text copied exactly from the source quote",
"service_code":"a CPT/HCPCS code printed in that quote or null",
"source_quote":"the complete source sentence or line",
"source_page":1,"confidence":0.0}]}

Rules:
- Do not diagnose, recommend, infer a service from symptoms, or add an order.
- Do not infer, translate, or complete a billing code.
- service_name and any service_code must appear verbatim in source_quote.
- source_page is the page marker containing source_quote.
- Return an empty orders array when no explicit order is present.
- Return JSON only.
"""


def _normalise(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReportSchemaError(f"candidate {field_name} must be non-empty text")
    return value.strip()


def _json_object(raw: str) -> dict[str, Any]:
    candidate = raw.strip()
    if not candidate.startswith("{"):
        start, end = candidate.find("{"), candidate.rfind("}")
        if start < 0 or end <= start:
            raise ReportSchemaError("Hermes did not return a JSON object")
        candidate = candidate[start : end + 1]
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as error:
        raise ReportSchemaError("Hermes returned invalid JSON") from error
    if not isinstance(payload, dict) or set(payload) != {"orders"}:
        raise ReportSchemaError("Hermes output must contain only an orders array")
    if not isinstance(payload["orders"], list):
        raise ReportSchemaError("Hermes orders must be an array")
    return payload


@dataclass(frozen=True, slots=True)
class PreparedDocument:
    source_name: str
    media_type: str
    byte_count: int
    source_hash: str
    consent_scope: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_name": self.source_name,
            "media_type": self.media_type,
            "byte_count": self.byte_count,
            "source_hash": self.source_hash,
            "consent_action": ConsentAction.PROCESS_DOCUMENTS.value,
            "consent_scope": self.consent_scope,
            "raw_document_persisted": False,
        }


@dataclass(frozen=True, slots=True)
class DocumentAuthorization:
    document: PreparedDocument
    consent: ConsentRecord


@dataclass(frozen=True, slots=True)
class ExtractedPage:
    number: int
    text: str

    def __post_init__(self) -> None:
        if self.number < 1 or not self.text.strip():
            raise ValueError("an extracted page needs a positive number and readable text")


@dataclass(frozen=True, slots=True)
class CandidateOrder:
    order_id: str
    service_name: str
    service_code: str | None
    source_quote: str
    source_location: str
    source: str
    observed_at: datetime
    confidence: float
    verification_status: VerificationStatus = VerificationStatus.SOURCE_BACKED
    confirmed: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "service_name": self.service_name,
            "service_code": self.service_code,
            "source_quote": self.source_quote,
            "source_location": self.source_location,
            "source": self.source,
            "observed_at": self.observed_at.isoformat(),
            "confidence": self.confidence,
            "verification_status": self.verification_status.value,
            "confirmed": self.confirmed,
        }


@dataclass(frozen=True, slots=True)
class ConfirmedOrder:
    order: CandidateOrder
    confirmed_at: datetime
    confirmed_by: str
    journey_id: str | None
    facts: tuple[DecisionFact, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "order_id": self.order.order_id,
            "journey_id": self.journey_id,
            "source_quote": self.order.source_quote,
            "source_location": self.order.source_location,
            "confirmed_at": self.confirmed_at.isoformat(),
            "confirmed_by": self.confirmed_by,
            "facts": [
                {
                    "name": fact.name,
                    "value": fact.value,
                    "source": fact.source,
                    "observed_at": fact.observed_at.isoformat(),
                    "confidence": fact.confidence,
                    "verification_status": fact.verification_status.value,
                    "consent_requirement": (
                        fact.consent_required.value if fact.consent_required else None
                    ),
                }
                for fact in self.facts
            ],
        }


@dataclass(frozen=True, slots=True)
class ReportAnalysis:
    analysis_id: str
    owner: str
    source_name: str
    source_hash: str
    observed_at: datetime
    consent: ConsentRecord
    journey_id: str | None
    orders: tuple[CandidateOrder, ...]
    confirmed_orders: tuple[ConfirmedOrder, ...] = ()

    @property
    def requires_confirmation(self) -> bool:
        return not self.confirmed_orders

    def as_dict(self) -> dict[str, Any]:
        return {
            "analysis_id": self.analysis_id,
            "source_name": self.source_name,
            "source_hash": self.source_hash,
            "observed_at": self.observed_at.isoformat(),
            "journey_id": self.journey_id,
            "orders": [order.as_dict() for order in self.orders],
            "confirmed_orders": [item.as_dict() for item in self.confirmed_orders],
            "requires_confirmation": self.requires_confirmation,
            "consent": {
                "action": self.consent.action.value,
                "approved": self.consent.approved,
                "actor": self.consent.actor,
                "scope": self.consent.scope,
                "recorded_at": self.consent.recorded_at.isoformat(),
            },
            "raw_document_persisted": False,
        }


class HermesOrderExtractor:
    """Text-only extraction through the authenticated Hermes gateway."""

    def __init__(self, client: HermesClient | None = None) -> None:
        self._client = client

    def __call__(self, pages: Sequence[ExtractedPage]) -> str:
        client = self._client or HermesClient()
        source = "\n\n".join(f"--- PAGE {page.number} ---\n{page.text}" for page in pages)
        return client.chat(
            [
                {"role": "system", "content": REPORT_ORDER_PROMPT},
                {"role": "user", "content": source},
            ],
            max_tokens=900,
            temperature=0.0,
        )


class ReportIntakeService:
    """In-memory intake state; only derived evidence is retained, never raw files."""

    def __init__(
        self,
        *,
        extractor: Callable[[Sequence[ExtractedPage]], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._extractor = extractor or HermesOrderExtractor()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._analyses: dict[str, ReportAnalysis] = {}

    @staticmethod
    def prepare_document(payload: bytes, *, source_name: str, media_type: str) -> PreparedDocument:
        if not payload:
            raise ReportIntakeError("the uploaded report is empty")
        safe_name = source_name.strip()
        if not safe_name or not media_type.strip():
            raise ReportIntakeError("source name and media type are required")
        digest = hashlib.sha256(payload).hexdigest()
        source_hash = f"sha256:{digest}"
        return PreparedDocument(
            source_name=safe_name,
            media_type=media_type.strip(),
            byte_count=len(payload),
            source_hash=source_hash,
            consent_scope=f"process doctor report {source_hash}",
        )

    def authorize(
        self,
        document: PreparedDocument,
        *,
        consent_scope: str,
        approved: bool,
        actor: str,
    ) -> DocumentAuthorization:
        if not approved or consent_scope != document.consent_scope:
            raise ExactDocumentConsentRequired(
                "approve processing for the exact uploaded report before extraction"
            )
        if not actor.strip():
            raise ReportIntakeError("the consent actor is required")
        consent = ConsentRecord(
            action=ConsentAction.PROCESS_DOCUMENTS,
            approved=True,
            actor=actor.strip(),
            recorded_at=self._clock(),
            scope=document.consent_scope,
        )
        return DocumentAuthorization(document=document, consent=consent)

    def analyze_authorized(
        self,
        authorization: DocumentAuthorization,
        pages: Sequence[ExtractedPage],
        *,
        journey_id: str | None = None,
    ) -> ReportAnalysis:
        if authorization.consent.scope != authorization.document.consent_scope:
            raise ExactDocumentConsentRequired("document authorization scope does not match")
        if not pages:
            raise ReportIntakeError("the uploaded report contains no readable text")
        if journey_id is not None and not journey_id.strip():
            raise ReportIntakeError("journey_id cannot be blank")
        raw = self._extractor(tuple(pages))
        orders = self._validated_orders(raw, pages, authorization.document)
        analysis = ReportAnalysis(
            analysis_id=f"report-{uuid.uuid4().hex}",
            owner=authorization.consent.actor,
            source_name=authorization.document.source_name,
            source_hash=authorization.document.source_hash,
            observed_at=self._clock(),
            consent=authorization.consent,
            journey_id=journey_id,
            orders=orders,
        )
        self._analyses[analysis.analysis_id] = analysis
        return analysis

    def confirm_orders(
        self,
        analysis_id: str,
        order_ids: Sequence[str],
        *,
        actor: str,
        journey_id: str | None = None,
    ) -> ReportAnalysis:
        analysis = self._analysis_for(analysis_id, actor)
        selected = set(order_ids)
        if not selected:
            raise ConfirmationRequired("confirm at least one source-backed order")
        known = {order.order_id for order in analysis.orders}
        unknown = selected - known
        if unknown:
            raise ReportIntakeError(f"unknown candidate order ids: {sorted(unknown)!r}")
        target_journey = journey_id if journey_id is not None else analysis.journey_id
        if target_journey is not None and not target_journey.strip():
            raise ReportIntakeError("journey_id cannot be blank")
        confirmed_at = self._clock()
        updated_orders = tuple(
            replace(order, confirmed=order.order_id in selected) for order in analysis.orders
        )
        confirmed = tuple(
            self._confirmed_order(
                order,
                actor=actor,
                confirmed_at=confirmed_at,
                journey_id=target_journey,
            )
            for order in updated_orders
            if order.confirmed
        )
        updated = replace(
            analysis,
            journey_id=target_journey,
            orders=updated_orders,
            confirmed_orders=confirmed,
        )
        self._analyses[analysis_id] = updated
        return updated

    def _validated_orders(
        self,
        raw: str,
        pages: Sequence[ExtractedPage],
        document: PreparedDocument,
    ) -> tuple[CandidateOrder, ...]:
        payload = _json_object(raw)
        by_number = {page.number: page for page in pages}
        observed_at = self._clock()
        orders: list[CandidateOrder] = []
        allowed = {
            "service_name",
            "service_code",
            "source_quote",
            "source_page",
            "confidence",
        }
        for index, item in enumerate(payload["orders"]):
            if not isinstance(item, dict) or set(item) != allowed:
                raise ReportSchemaError(f"candidate order {index + 1} has an invalid shape")
            name = _required_text(item["service_name"], "service_name")
            quote = _required_text(item["source_quote"], "source_quote")
            page_number = item["source_page"]
            if isinstance(page_number, bool) or not isinstance(page_number, int):
                raise ReportSchemaError("candidate source_page must be an integer")
            page = by_number.get(page_number)
            if page is None or _normalise(quote) not in _normalise(page.text):
                raise ReportSchemaError("candidate source_quote was not found on its source page")
            if _normalise(name) not in _normalise(quote):
                raise ReportSchemaError("candidate service_name was not copied from its quote")
            code_value = item["service_code"]
            if code_value is not None:
                code = _required_text(code_value, "service_code")
                if _normalise(code) not in _normalise(quote):
                    raise ReportSchemaError("candidate service_code was not printed in its quote")
            else:
                code = None
            confidence_value = item["confidence"]
            if isinstance(confidence_value, bool):
                raise ReportSchemaError("candidate confidence must be a number")
            try:
                confidence = float(confidence_value)
            except (TypeError, ValueError) as error:
                raise ReportSchemaError("candidate confidence must be a number") from error
            if not 0.0 <= confidence <= 1.0:
                raise ReportSchemaError("candidate confidence must be between 0 and 1")
            orders.append(
                CandidateOrder(
                    order_id=f"order-{len(orders) + 1}",
                    service_name=name,
                    service_code=code,
                    source_quote=quote,
                    source_location=f"page {page_number}",
                    source=f"uploaded_report:{document.source_hash}",
                    observed_at=observed_at,
                    confidence=confidence,
                )
            )
        return tuple(orders)

    def _confirmed_order(
        self,
        order: CandidateOrder,
        *,
        actor: str,
        confirmed_at: datetime,
        journey_id: str | None,
    ) -> ConfirmedOrder:
        source = f"{order.source}#{order.source_location.replace(' ', '=')}"
        facts = [
            DecisionFact(
                name="requested_procedure",
                value=order.service_name,
                source=source,
                observed_at=confirmed_at,
                confidence=order.confidence,
                verification_status=VerificationStatus.VERIFIED,
                consent_required=ConsentAction.PROCESS_DOCUMENTS,
            )
        ]
        if order.service_code:
            facts.append(
                DecisionFact(
                    name="procedure_code",
                    value=order.service_code,
                    source=source,
                    observed_at=confirmed_at,
                    confidence=order.confidence,
                    verification_status=VerificationStatus.VERIFIED,
                    consent_required=ConsentAction.PROCESS_DOCUMENTS,
                )
            )
        return ConfirmedOrder(
            order=order,
            confirmed_at=confirmed_at,
            confirmed_by=actor,
            journey_id=journey_id,
            facts=tuple(facts),
        )

    def _analysis_for(self, analysis_id: str, actor: str) -> ReportAnalysis:
        try:
            analysis = self._analyses[analysis_id]
        except KeyError as error:
            raise ReportIntakeError(f"unknown report analysis {analysis_id!r}") from error
        if analysis.owner != actor:
            raise ReportIntakeError("report analysis does not belong to this user")
        return analysis


__all__ = [
    "CandidateOrder",
    "ConfirmationRequired",
    "DocumentAuthorization",
    "ExactDocumentConsentRequired",
    "ExtractedPage",
    "HermesOrderExtractor",
    "PreparedDocument",
    "ReportAnalysis",
    "ReportIntakeError",
    "ReportIntakeService",
    "ReportSchemaError",
]
