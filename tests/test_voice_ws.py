import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from services.api.app import db


FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI is installed in the API runtime")
class VoiceJourneySnapshotTests(unittest.TestCase):
    def test_spoken_mri_intake_prioritizes_body_area_over_dates(self) -> None:
        from services.api.app.api import _intake_reply

        journey = SimpleNamespace(onboarding_questions=(
            "What date do you expect to receive this care?",
            "When does your current coverage end?",
            "What body area is the MRI for, and was it ordered with or without contrast?",
        ))
        reply = _intake_reply(journey, continuing=False, voice=True)
        self.assertIn("What body area", reply)

    def test_reads_the_persisted_snapshot_column(self) -> None:
        from services.api.app.ws import _voice_journey_snapshot

        with tempfile.TemporaryDirectory() as directory:
            conn = db.connect(Path(directory) / "voice.db")
            db.init_db(conn)
            conn.execute(
                "INSERT INTO user (id,email,password_hash,salt,created_at) VALUES (1,'voice@test','x','y','now')"
            )
            snapshot = {"stage": "book", "onboarding_questions": []}
            conn.execute(
                """INSERT INTO care_journey
                   (journey_id,user_id,title,stage,status,snapshot_json,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                ("journey-1", 1, "MRI", "book", "active", json.dumps(snapshot), "now", "now"),
            )
            conn.commit()
            self.assertEqual(_voice_journey_snapshot(conn, 1, "journey-1"), snapshot)
            conn.close()


if __name__ == "__main__":
    unittest.main()
