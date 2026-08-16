"""Messaging route integration: preview, exact consent, and redacted receipts."""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.api.app import db


FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI is installed in the API runtime")
class MessagingRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from services.api.app.messaging_routes import build_messaging_router

        self.environment = patch.dict(os.environ, {
            "ABYSS_MESSAGING_MODE": "sandbox",
            "ABYSS_DISCORD_ALLOWLIST": "discord:eevee",
            "ABYSS_SMS_ALLOWLIST": "+15082908822",
            "ABYSS_PUBLIC_APP_URL": "https://vela.example",
        }, clear=False)
        self.environment.start()
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.connect(Path(self.tmp.name) / "messaging.db")
        db.init_db(self.conn)
        self.conn.execute(
            "INSERT INTO user (id,email,password_hash,salt,created_at) VALUES (1,'demo@test','x','y','now')"
        )
        self.conn.commit()

        def get_conn():
            return self.conn

        def require_user():
            return 1

        app = FastAPI()
        app.include_router(build_messaging_router(get_conn=get_conn, require_user=require_user))
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        self.conn.close()
        self.tmp.cleanup()
        self.environment.stop()

    def _enable(self, channel: str, destination: str) -> None:
        response = self.client.put("/api/me/messaging", json={
            "enabled": True,
            "channel": channel,
            "destination_label": destination,
        })
        self.assertEqual(response.status_code, 200, response.text)

    def test_send_requires_matching_persisted_preview(self) -> None:
        self._enable("discord", "discord:eevee")
        unpreviewed = self.client.post("/api/results/notify", json={
            "result_ref": "journey-1",
            "consent_scope": "made-up",
            "consent_approved": True,
        })
        self.assertEqual(unpreviewed.status_code, 409)

        preview = self.client.post("/api/results/notify/preview", json={
            "result_ref": "journey-1",
            "message_kind": "result_link",
        })
        self.assertEqual(preview.status_code, 200, preview.text)
        item = preview.json()
        self.assertEqual(item["body"], "Your VELA update is ready: https://vela.example/#appointments?result=journey-1")
        self.assertNotIn("discord:eevee", item["consent_scope"])

        sent = self.client.post("/api/results/notify", json={
            "result_ref": "journey-1",
            "message_kind": "result_link",
            "consent_scope": item["consent_scope"],
            "consent_approved": True,
        })
        self.assertEqual(sent.status_code, 200, sent.text)
        self.assertTrue(sent.json()["sandbox"])

        receipt = self.conn.execute("SELECT * FROM messaging_receipt").fetchone()
        self.assertEqual(receipt["destination_redacted"], "discord:ee***")
        self.assertNotIn("discord:eevee", receipt["consent_scope"])
        events = self.conn.execute(
            "SELECT payload_json FROM agent_memory_event ORDER BY id"
        ).fetchall()
        self.assertTrue(events)
        self.assertTrue(all("discord:eevee" not in row["payload_json"] for row in events))

    def test_twilio_sandbox_route_enforces_allowlist_and_redacts_receipt(self) -> None:
        denied = self.client.put("/api/me/messaging", json={
            "enabled": True,
            "channel": "twilio",
            "destination_label": "+15551234567",
        })
        self.assertEqual(denied.status_code, 403)

        self._enable("twilio", "(508) 290-8822")
        preview = self.client.post("/api/results/notify/preview", json={
            "result_ref": "appointment-42"
        }).json()
        sent = self.client.post("/api/results/notify-sms", json={
            "result_ref": "appointment-42",
            "consent_scope": preview["consent_scope"],
            "consent_approved": True,
        })
        self.assertEqual(sent.status_code, 200, sent.text)
        self.assertEqual(sent.json()["destination_redacted"], "***8822")
        receipt = self.conn.execute("SELECT * FROM messaging_receipt").fetchone()
        self.assertEqual(receipt["channel"], "twilio")
        self.assertEqual(receipt["message_kind"], "result_link")
        self.assertEqual(receipt["destination_redacted"], "***8822")
        self.assertNotIn("+15082908822", receipt["consent_scope"])


if __name__ == "__main__":
    unittest.main()
