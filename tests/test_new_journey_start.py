import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI is installed in the API runtime")
class NewJourneyStartTests(unittest.TestCase):
    def test_empty_started_journey_is_reused_for_first_care_request(self) -> None:
        from fastapi.testclient import TestClient
        from services.api.app.api import _journeys, app

        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {"ABYSS_DB": str(Path(directory) / "new-journey.db")},
            clear=False,
        ):
            _journeys.clear()
            with TestClient(app) as client:
                signup = client.post(
                    "/api/auth/signup",
                    json={"email": "new-journey@example.test", "password": "synthetic-only-123"},
                )
                self.assertEqual(signup.status_code, 200)
                headers = {"authorization": f"Bearer {signup.json()['token']}"}

                started = client.post("/api/journeys", json={"empty": True}, headers=headers)
                self.assertEqual(started.status_code, 200)
                started_id = started.json()["journey_id"]
                self.assertEqual(started.json()["facts"], [])

                first_turn = client.post(
                    "/api/care-agent/messages",
                    json={
                        "text": "I want to book an MRI scan",
                        "active_journey_id": started_id,
                    },
                    headers=headers,
                )
                self.assertEqual(first_turn.status_code, 200)
                self.assertEqual(first_turn.json()["journey"]["journey_id"], started_id)

                context = client.get("/api/care-context", headers=headers)
                self.assertEqual(context.status_code, 200)
                self.assertEqual(
                    [item["journey_id"] for item in context.json()["journeys"]],
                    [started_id],
                )
            _journeys.clear()

    def test_confirmed_report_facts_attach_to_one_owned_journey(self) -> None:
        from abyss.report_intake import ExtractedPage, ReportIntakeService
        from services.api.app import db
        from services.api.app.api import _attach_confirmed_report, _journeys

        report = "Plan: MRI right knee without contrast, CPT 73721."
        extracted = json.dumps({"orders": [{
            "service_name": "MRI right knee without contrast",
            "service_code": "73721",
            "source_quote": report,
            "source_page": 1,
            "confidence": 0.99,
        }]})
        service = ReportIntakeService(extractor=lambda _pages: extracted)

        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {"ABYSS_DB": str(Path(directory) / "report-journey.db")},
            clear=False,
        ):
            conn = db.connect()
            db.init_db(conn)
            conn.execute(
                """INSERT INTO user (id,email,password_hash,salt,created_at)
                   VALUES (7,'report-journey@example.test','x','y','now')"""
            )
            conn.commit()
            conn.close()

            document = service.prepare_document(
                report.encode(), source_name="synthetic-referral.txt", media_type="text/plain"
            )
            authorization = service.authorize(
                document,
                consent_scope=document.consent_scope,
                approved=True,
                actor="7",
            )
            analysis = service.analyze_authorized(
                authorization, [ExtractedPage(1, report)]
            )
            confirmed = service.confirm_orders(
                analysis.analysis_id, ["order-1"], actor="7"
            )
            result = _attach_confirmed_report(confirmed, 7)

            self.assertEqual(result["analysis"]["source_hash"], document.source_hash)
            self.assertEqual(len(_journeys), 1)
            fact_names = {fact["name"] for fact in result["journey"]["facts"]}
            self.assertIn("requested_procedure", fact_names)
            self.assertIn("procedure_code", fact_names)
            # requested_procedure and procedure_code are already confirmed
            # from the report; service_date and coverage_end_date are no
            # longer required (see agents.py / journey.py), so intake has
            # nothing left to ask for.
            self.assertEqual(result["journey"]["onboarding_missing"], [])
            self.assertEqual(result["journey"]["onboarding_questions"], [])
            self.assertTrue(any(
                event["type"] == "report_orders_confirmed"
                for event in result["journey"]["events"]
            ))
            _journeys.clear()


if __name__ == "__main__":
    unittest.main()
