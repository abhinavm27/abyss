import importlib.util
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


if __name__ == "__main__":
    unittest.main()
