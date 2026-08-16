import json
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.report_routes import build_report_intake_router
from fastapi import FastAPI
from fastapi.testclient import TestClient

from abyss.report_intake import ReportIntakeService


class ReportIntakeRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.report = "Plan: MRI right knee without contrast, CPT 73721."
        self.extractor_calls = []
        self.service = ReportIntakeService(extractor=self._extract)
        app = FastAPI()
        app.include_router(
            build_report_intake_router(
                self.service,
                actor_dependency=lambda: "demo-user",
            )
        )
        self.client = TestClient(app)

    def _extract(self, pages):
        self.extractor_calls.append(pages)
        return json.dumps(
            {
                "orders": [
                    {
                        "service_name": "MRI right knee without contrast",
                        "service_code": "73721",
                        "source_quote": self.report,
                        "source_page": 1,
                        "confidence": 0.99,
                    }
                ]
            }
        )

    def test_prepare_analyze_and_confirm_contract(self) -> None:
        upload = {"file": ("synthetic-referral.txt", self.report, "text/plain")}
        prepared = self.client.post("/api/report-intake/prepare", files=upload)
        self.assertEqual(prepared.status_code, 200, prepared.text)
        consent_scope = prepared.json()["consent_scope"]
        self.assertEqual(prepared.json()["consent_action"], "process_documents")
        self.assertFalse(prepared.json()["raw_document_persisted"])
        self.assertEqual(self.extractor_calls, [])

        analyzed = self.client.post(
            "/api/report-intake/analyze",
            files=upload,
            data={
                "consent_scope": consent_scope,
                "consent_approved": "true",
                "journey_id": "journey-123",
            },
        )
        self.assertEqual(analyzed.status_code, 200, analyzed.text)
        self.assertEqual(len(self.extractor_calls), 1)
        body = analyzed.json()
        self.assertTrue(body["requires_confirmation"])
        self.assertEqual(body["orders"][0]["source_location"], "page 1")
        self.assertEqual(body["orders"][0]["verification_status"], "source_backed")

        confirmed = self.client.post(
            f"/api/report-intake/{body['analysis_id']}/confirm",
            json={"order_ids": ["order-1"]},
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        facts = confirmed.json()["confirmed_orders"][0]["facts"]
        self.assertEqual(
            [fact["name"] for fact in facts],
            ["requested_procedure", "procedure_code"],
        )
        self.assertTrue(all(fact["verification_status"] == "verified" for fact in facts))
        self.assertEqual(confirmed.json()["journey_id"], "journey-123")

    def test_wrong_or_refused_consent_never_extracts_the_document(self) -> None:
        upload = {"file": ("synthetic-referral.txt", self.report, "text/plain")}
        with patch("app.report_routes._extract_pages") as extract_pages:
            response = self.client.post(
                "/api/report-intake/analyze",
                files=upload,
                data={
                    "consent_scope": "process a different report",
                    "consent_approved": "true",
                },
            )
            self.assertEqual(response.status_code, 409, response.text)
            extract_pages.assert_not_called()
        self.assertEqual(self.extractor_calls, [])

    def test_pdf_pages_are_extracted_without_retaining_the_upload(self) -> None:
        class FakePage:
            def extract_text(self):
                return self_text

        class FakePdf:
            pages = [FakePage()]

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        self_text = self.report
        upload = {"file": ("synthetic-referral.pdf", b"%PDF synthetic", "application/pdf")}
        prepared = self.client.post("/api/report-intake/prepare", files=upload)
        fake_pdfplumber = SimpleNamespace(open=lambda source: FakePdf())
        with patch.dict(sys.modules, {"pdfplumber": fake_pdfplumber}):
            analyzed = self.client.post(
                "/api/report-intake/analyze",
                files=upload,
                data={
                    "consent_scope": prepared.json()["consent_scope"],
                    "consent_approved": "true",
                },
            )
        self.assertEqual(analyzed.status_code, 200, analyzed.text)
        self.assertFalse(analyzed.json()["raw_document_persisted"])


if __name__ == "__main__":
    unittest.main()
