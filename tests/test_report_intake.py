import json
import unittest
from datetime import UTC, datetime

from abyss.domain import ConsentAction, VerificationStatus
from abyss.report_intake import (
    ExactDocumentConsentRequired,
    ExtractedPage,
    ReportIntakeError,
    ReportIntakeService,
    ReportSchemaError,
)

NOW = datetime(2026, 8, 15, 20, 0, tzinfo=UTC)


class ReportIntakeTests(unittest.TestCase):
    def test_exact_document_consent_precedes_text_and_model_processing(self) -> None:
        calls = []
        service = ReportIntakeService(
            extractor=lambda pages: calls.append(pages) or '{"orders":[]}',
            clock=lambda: NOW,
        )
        document = service.prepare_document(
            b"Plan: MRI knee without contrast.",
            source_name="synthetic-referral.txt",
            media_type="text/plain",
        )

        with self.assertRaises(ExactDocumentConsentRequired):
            service.authorize(
                document,
                consent_scope="process a different document",
                approved=True,
                actor="demo-user",
            )
        with self.assertRaises(ExactDocumentConsentRequired):
            service.authorize(
                document,
                consent_scope=document.consent_scope,
                approved=False,
                actor="demo-user",
            )

        self.assertEqual(calls, [])
        self.assertEqual(document.consent_scope, f"process doctor report {document.source_hash}")
        self.assertFalse(document.as_dict()["raw_document_persisted"])

    def test_confirmed_source_backed_order_produces_journey_facts(self) -> None:
        report = "Plan: MRI right knee without contrast, CPT 73721."
        result = {
            "orders": [
                {
                    "service_name": "MRI right knee without contrast",
                    "service_code": "73721",
                    "source_quote": report,
                    "source_page": 1,
                    "confidence": 0.98,
                }
            ]
        }
        service = ReportIntakeService(
            extractor=lambda pages: json.dumps(result),
            clock=lambda: NOW,
        )
        document = service.prepare_document(
            report.encode(),
            source_name="synthetic-referral.txt",
            media_type="text/plain",
        )
        authorization = service.authorize(
            document,
            consent_scope=document.consent_scope,
            approved=True,
            actor="demo-user",
        )
        analysis = service.analyze_authorized(
            authorization,
            [ExtractedPage(1, report)],
            journey_id="journey-123",
        )

        self.assertTrue(analysis.requires_confirmation)
        self.assertEqual(analysis.orders[0].verification_status, VerificationStatus.SOURCE_BACKED)
        self.assertEqual(analysis.orders[0].source_location, "page 1")
        self.assertEqual(analysis.orders[0].source_quote, report)
        self.assertEqual(analysis.consent.action, ConsentAction.PROCESS_DOCUMENTS)

        confirmed = service.confirm_orders(
            analysis.analysis_id,
            ["order-1"],
            actor="demo-user",
        )

        self.assertFalse(confirmed.requires_confirmation)
        item = confirmed.confirmed_orders[0]
        self.assertEqual(item.journey_id, "journey-123")
        self.assertEqual(
            [(fact.name, fact.value) for fact in item.facts],
            [
                ("requested_procedure", "MRI right knee without contrast"),
                ("procedure_code", "73721"),
            ],
        )
        for fact in item.facts:
            self.assertEqual(fact.verification_status, VerificationStatus.VERIFIED)
            self.assertEqual(fact.consent_required, ConsentAction.PROCESS_DOCUMENTS)
            self.assertEqual(fact.confidence, 0.98)
        payload = confirmed.as_dict()
        self.assertNotIn("document", payload)
        self.assertFalse(payload["raw_document_persisted"])
        self.assertEqual(payload["confirmed_orders"][0]["source_quote"], report)

    def test_invented_code_and_unquoted_order_are_rejected(self) -> None:
        report = "Plan: MRI right knee without contrast."
        document_service = ReportIntakeService(clock=lambda: NOW)
        document = document_service.prepare_document(
            report.encode(), source_name="report.txt", media_type="text/plain"
        )

        for order in (
            {
                "service_name": "MRI right knee without contrast",
                "service_code": "73721",
                "source_quote": report,
                "source_page": 1,
                "confidence": 0.9,
            },
            {
                "service_name": "CT head",
                "service_code": None,
                "source_quote": "Plan: CT head.",
                "source_page": 1,
                "confidence": 0.9,
            },
        ):
            with self.subTest(order=order):
                service = ReportIntakeService(
                    extractor=lambda pages, order=order: json.dumps({"orders": [order]}),
                    clock=lambda: NOW,
                )
                authorization = service.authorize(
                    document,
                    consent_scope=document.consent_scope,
                    approved=True,
                    actor="demo-user",
                )
                with self.assertRaises(ReportSchemaError):
                    service.analyze_authorized(authorization, [ExtractedPage(1, report)])

    def test_an_analysis_is_private_to_its_consent_actor(self) -> None:
        report = "Plan: Complete abdominal ultrasound."
        service = ReportIntakeService(
            extractor=lambda pages: json.dumps(
                {
                    "orders": [
                        {
                            "service_name": "Complete abdominal ultrasound",
                            "service_code": None,
                            "source_quote": report,
                            "source_page": 1,
                            "confidence": 0.97,
                        }
                    ]
                }
            ),
            clock=lambda: NOW,
        )
        document = service.prepare_document(
            report.encode(), source_name="report.txt", media_type="text/plain"
        )
        authorization = service.authorize(
            document,
            consent_scope=document.consent_scope,
            approved=True,
            actor="user-1",
        )
        analysis = service.analyze_authorized(authorization, [ExtractedPage(1, report)])

        with self.assertRaises(ReportIntakeError):
            service.confirm_orders(
                analysis.analysis_id,
                ["order-1"],
                actor="user-2",
            )


if __name__ == "__main__":
    unittest.main()
