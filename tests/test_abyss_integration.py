"""Cross-workstream integration tests for catalog, report intake, and messaging."""

from __future__ import annotations

import json
import importlib.util
import tempfile
import unittest
from dataclasses import fields, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from abyss.domain import ConsentAction, VerificationStatus
from abyss.knowledge import (
    KnowledgeCatalogError,
    SeededHospitalKnowledgeCatalog,
)
from abyss.report_intake import ExtractedPage, ReportIntakeService
from services.api.app import db
from services.api.app.config import hospital_knowledge_catalog


NOW = datetime(2026, 8, 15, 20, 0, tzinfo=UTC)
REPORT = "Plan: MRI right knee without contrast, CPT 73721."
DESTINATION = "+15082908822"
FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None


def _contains_bytes(value: object, seen: set[int] | None = None) -> bool:
    """Walk retained intake state and detect any raw byte payload."""

    if isinstance(value, bytes):
        return True
    if value is None or isinstance(value, (str, int, float, bool, datetime)):
        return False
    visited = seen if seen is not None else set()
    identity = id(value)
    if identity in visited:
        return False
    visited.add(identity)
    if is_dataclass(value) and not isinstance(value, type):
        return any(_contains_bytes(getattr(value, item.name), visited) for item in fields(value))
    if isinstance(value, dict):
        return any(
            _contains_bytes(key, visited) or _contains_bytes(item, visited)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_contains_bytes(item, visited) for item in value)
    return False


class _FakeSandboxAdapter:
    def __init__(self) -> None:
        self.calls = []

    def send(self, preview, *, approved_scope: str):
        self.calls.append((preview, approved_scope))
        if approved_scope != preview.consent_scope:
            raise AssertionError("route passed non-exact consent to the adapter")
        return {
            "ok": True,
            "channel": "twilio",
            "confirmation_reference": "sandbox-twilio-integration-1",
            "destination_redacted": "***8822",
            "message_kind": preview.message_kind,
            "sandbox": True,
        }


class AbyssCrossWorkstreamIntegrationTests(unittest.TestCase):
    def test_unconfigured_catalog_uses_explicit_synthetic_fixture(self) -> None:
        catalog = hospital_knowledge_catalog({})

        self.assertIsInstance(catalog, SeededHospitalKnowledgeCatalog)
        rates = catalog.prices_for_code("73721")
        self.assertEqual(len(rates), 1)
        self.assertEqual(rates[0].catalog_source, catalog.source_name)
        self.assertIn("synthetic", rates[0].verification_status)
        self.assertEqual(rates[0].network_status, "unknown")

    def test_configured_missing_catalog_fails_without_synthetic_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "configured-but-missing.db"

            with self.assertRaises(KnowledgeCatalogError):
                hospital_knowledge_catalog({"ABYSS_KNOWLEDGE_DB": str(missing)})

            self.assertFalse(missing.exists())

    def test_report_consent_analysis_and_confirmation_retains_no_raw_bytes(self) -> None:
        extractor_calls = []

        def fake_hermes(pages):
            extractor_calls.append(tuple(pages))
            return json.dumps({
                "orders": [{
                    "service_name": "MRI right knee without contrast",
                    "service_code": "73721",
                    "source_quote": REPORT,
                    "source_page": 1,
                    "confidence": 0.99,
                }]
            })

        service = ReportIntakeService(extractor=fake_hermes, clock=lambda: NOW)
        raw_document = REPORT.encode("utf-8")
        prepared = service.prepare_document(
            raw_document,
            source_name="synthetic-referral.txt",
            media_type="text/plain",
        )
        self.assertEqual(extractor_calls, [])
        self.assertFalse(_contains_bytes(prepared))

        authorization = service.authorize(
            prepared,
            consent_scope=prepared.consent_scope,
            approved=True,
            actor="synthetic-user",
        )
        analysis = service.analyze_authorized(
            authorization,
            [ExtractedPage(1, REPORT)],
            journey_id="journey-integration-1",
        )
        confirmed = service.confirm_orders(
            analysis.analysis_id,
            [analysis.orders[0].order_id],
            actor="synthetic-user",
        )

        self.assertEqual(len(extractor_calls), 1)
        self.assertTrue(authorization.consent.approved)
        self.assertEqual(authorization.consent.action, ConsentAction.PROCESS_DOCUMENTS)
        self.assertEqual(confirmed.journey_id, "journey-integration-1")
        facts = confirmed.confirmed_orders[0].facts
        self.assertEqual(
            [(fact.name, fact.value) for fact in facts],
            [
                ("requested_procedure", "MRI right knee without contrast"),
                ("procedure_code", "73721"),
            ],
        )
        self.assertTrue(
            all(fact.verification_status is VerificationStatus.VERIFIED for fact in facts)
        )
        self.assertFalse(confirmed.as_dict()["raw_document_persisted"])
        self.assertFalse(_contains_bytes(service._analyses))

    @unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI is installed in the API runtime")
    def test_message_requires_persisted_preview_and_exact_consent_then_redacts(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from services.api.app.messaging_routes import build_messaging_router

        fake_adapter = _FakeSandboxAdapter()
        environment = {
            "ABYSS_MESSAGING_MODE": "sandbox",
            "ABYSS_SMS_ALLOWLIST": DESTINATION,
            "ABYSS_PUBLIC_APP_URL": "https://vela.example",
        }
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            "os.environ", environment, clear=False
        ):
            conn = db.connect(Path(directory) / "integration.db")
            self.addCleanup(conn.close)
            db.init_db(conn)
            conn.execute(
                "INSERT INTO user (id,email,password_hash,salt,created_at) "
                "VALUES (1,'integration@test','x','y','now')"
            )
            conn.commit()

            app = FastAPI()
            app.include_router(
                build_messaging_router(
                    get_conn=lambda: conn, require_user=lambda: 1,
                    get_catalog_conn=lambda: conn,
                )
            )
            with TestClient(app) as client, patch(
                "services.api.app.messaging_routes.messaging_adapter",
                return_value=fake_adapter,
            ):
                enabled = client.put("/api/me/messaging", json={
                    "enabled": True,
                    "channel": "twilio",
                    "destination_label": DESTINATION,
                })
                self.assertEqual(enabled.status_code, 200, enabled.text)

                before_preview = client.post("/api/results/notify", json={
                    "result_ref": "appointment-integration-1",
                    "message_kind": "result_link",
                    "consent_scope": "not-the-exact-scope",
                    "consent_approved": True,
                })
                self.assertEqual(before_preview.status_code, 409, before_preview.text)
                self.assertEqual(fake_adapter.calls, [])

                preview = client.post("/api/results/notify/preview", json={
                    "result_ref": "appointment-integration-1",
                    "message_kind": "result_link",
                })
                self.assertEqual(preview.status_code, 200, preview.text)
                preview_body = preview.json()
                self.assertEqual(preview_body["destination_redacted"], "***8822")
                self.assertNotIn(DESTINATION, preview_body["consent_scope"])

                wrong_consent = client.post("/api/results/notify", json={
                    "result_ref": "appointment-integration-1",
                    "message_kind": "result_link",
                    "consent_scope": preview_body["consent_scope"] + "-changed",
                    "consent_approved": True,
                })
                self.assertEqual(wrong_consent.status_code, 409, wrong_consent.text)
                self.assertEqual(fake_adapter.calls, [])

                sent = client.post("/api/results/notify", json={
                    "result_ref": "appointment-integration-1",
                    "message_kind": "result_link",
                    "consent_scope": preview_body["consent_scope"],
                    "consent_approved": True,
                })
                self.assertEqual(sent.status_code, 200, sent.text)
                self.assertTrue(sent.json()["sandbox"])
                self.assertEqual(len(fake_adapter.calls), 1)

            receipt = conn.execute(
                "SELECT destination_redacted, consent_scope FROM messaging_receipt"
            ).fetchone()
            self.assertEqual(receipt["destination_redacted"], "***8822")
            self.assertNotIn(DESTINATION, receipt["consent_scope"])
            persisted = " ".join(
                row["payload_json"]
                for row in conn.execute("SELECT payload_json FROM agent_memory_event")
            )
            self.assertNotIn(DESTINATION, persisted)


if __name__ == "__main__":
    unittest.main()
