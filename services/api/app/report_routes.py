"""Mountable HTTP routes for consent-gated report and referral intake."""

from __future__ import annotations

import io
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from abyss.hermes_client import HermesError
from abyss.report_intake import (
    ConfirmationRequired,
    ExactDocumentConsentRequired,
    ExtractedPage,
    ReportIntakeError,
    ReportIntakeService,
    ReportAnalysis,
    ReportSchemaError,
)

MAX_REPORT_BYTES = 5 * 1024 * 1024
MAX_EXTRACTED_CHARACTERS = 100_000


class ConfirmOrdersIn(BaseModel):
    order_ids: list[str] = Field(min_length=1, max_length=10)
    journey_id: str | None = Field(default=None, min_length=1, max_length=200)


async def _read_upload(file: UploadFile) -> bytes:
    payload = await file.read(MAX_REPORT_BYTES + 1)
    if not payload:
        raise ReportIntakeError("the uploaded report is empty")
    if len(payload) > MAX_REPORT_BYTES:
        raise ReportIntakeError("the uploaded report exceeds the 5 MB limit")
    return payload


def _safe_name(file: UploadFile) -> str:
    return Path(file.filename or "uploaded-report").name


def _media_type(file: UploadFile) -> str:
    name = _safe_name(file).casefold()
    if name.endswith(".txt") or file.content_type == "text/plain":
        return "text/plain"
    if name.endswith(".pdf") or file.content_type == "application/pdf":
        return "application/pdf"
    if (file.content_type or "").startswith("image/"):
        return file.content_type or "image/jpeg"
    raise ReportIntakeError("upload a PDF, UTF-8 text, or image doctor report")


def _extract_pages(
    payload: bytes,
    media_type: str,
    *,
    extracted_text: str | None = None,
) -> tuple[ExtractedPage, ...]:
    if media_type == "text/plain":
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ReportIntakeError("the text report must be UTF-8") from error
        pages = (ExtractedPage(1, text),) if text.strip() else ()
    elif media_type == "application/pdf":
        import pdfplumber

        try:
            with pdfplumber.open(io.BytesIO(payload)) as pdf:
                pages = tuple(
                    ExtractedPage(index, text)
                    for index, page in enumerate(pdf.pages, start=1)
                    if (text := (page.extract_text() or "").strip())
                )
        except Exception as error:  # noqa: BLE001 - exposed as a safe client error
            raise ReportIntakeError("text could not be extracted from this PDF") from error
    else:
        text = (extracted_text or "").strip()
        pages = (ExtractedPage(1, text),) if text else ()
    if not pages:
        raise ReportIntakeError("the uploaded report contains no readable text")
    if sum(len(page.text) for page in pages) > MAX_EXTRACTED_CHARACTERS:
        raise ReportIntakeError("the extracted report exceeds the text processing limit")
    return pages


def _safe_http_error(error: Exception) -> HTTPException:
    if isinstance(error, ExactDocumentConsentRequired):
        return HTTPException(status_code=409, detail=str(error))
    if isinstance(error, HermesError):
        return HTTPException(status_code=503, detail=str(error))
    if isinstance(error, ReportSchemaError | ConfirmationRequired | ReportIntakeError):
        return HTTPException(status_code=422, detail=str(error))
    raise error


def build_report_intake_router(
    service: ReportIntakeService,
    *,
    actor_dependency: Callable[..., Any],
    confirmed_handler: Callable[[ReportAnalysis, Any], dict[str, Any]] | None = None,
) -> APIRouter:
    """Build a router whose parent supplies its authenticated-user dependency."""

    router = APIRouter(prefix="/api/report-intake", tags=["report-intake"])

    @router.post("/prepare")
    async def prepare_report(
        file: UploadFile = File(...),  # noqa: B008 - FastAPI dependency declaration
        actor: Any = Depends(actor_dependency),  # noqa: B008
    ):
        del actor  # Authentication is required; content is not inspected at this stage.
        try:
            payload = await _read_upload(file)
            document = service.prepare_document(
                payload,
                source_name=_safe_name(file),
                media_type=_media_type(file),
            )
            return document.as_dict()
        except Exception as error:
            raise _safe_http_error(error) from error

    @router.post("/analyze")
    async def analyze_report(
        file: UploadFile = File(...),  # noqa: B008 - FastAPI dependency declaration
        consent_scope: str = Form(...),
        consent_approved: bool = Form(...),
        journey_id: str | None = Form(default=None),
        extracted_text: str | None = Form(default=None),
        actor: Any = Depends(actor_dependency),  # noqa: B008
    ):
        try:
            payload = await _read_upload(file)
            document = service.prepare_document(
                payload,
                source_name=_safe_name(file),
                media_type=_media_type(file),
            )
            authorization = service.authorize(
                document,
                consent_scope=consent_scope,
                approved=consent_approved,
                actor=str(actor),
            )
            # Consent is validated above before PDF/text extraction begins.
            pages = _extract_pages(
                payload,
                document.media_type,
                extracted_text=extracted_text,
            )
            return service.analyze_authorized(
                authorization,
                pages,
                journey_id=journey_id,
            ).as_dict()
        except Exception as error:
            raise _safe_http_error(error) from error

    @router.post("/{analysis_id}/confirm")
    def confirm_orders(
        analysis_id: str,
        body: ConfirmOrdersIn,
        actor: Any = Depends(actor_dependency),  # noqa: B008
    ):
        try:
            confirmed = service.confirm_orders(
                analysis_id,
                body.order_ids,
                actor=str(actor),
                journey_id=body.journey_id,
            )
            return (
                confirmed_handler(confirmed, actor)
                if confirmed_handler is not None
                else confirmed.as_dict()
            )
        except Exception as error:
            raise _safe_http_error(error) from error

    return router


__all__ = ["build_report_intake_router"]
