import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from abyss.domain import DecisionFact, VerificationStatus
from abyss.memory import PersistentMemoryStore
from abyss.messaging import (
    DiscordMessagingAdapter,
    DiscordSandboxAdapter,
    MessagingError,
    TwilioMessagingAdapter,
    TwilioSandboxAdapter,
    messaging_adapter,
    notification_preview,
)

from services.api.app import db


class _Response:
    def __init__(self, payload: dict | None = None) -> None:
        self.payload = payload or {"id": "discord-message-1"}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


class MemoryMessagingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = db.connect(Path(self.tmp.name) / "memory.db")
        db.init_db(self.conn)
        self.conn.execute(
            "INSERT INTO user (id,email,password_hash,salt,created_at) VALUES (1,'demo@test','x','y','now')"
        )
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()
        self.tmp.cleanup()

    def test_memory_supersedes_prior_value_and_redacts_events(self) -> None:
        store = PersistentMemoryStore(self.conn)
        for value in ("first", "second"):
            store.record_fact(1, DecisionFact(
                "preferred_facility", value, "user_request", datetime.now(UTC),
                1.0, VerificationStatus.SOURCE_BACKED,
            ))
        store.append_event(
            1, agent_role="test", event_type="safe_event",
            payload={"token": "must-not-persist", "status": "ok"},
        )
        view = store.view(1)
        self.assertEqual(view["current_facts"][0]["value"], "second")
        self.assertEqual(view["agent_events"][0]["payload"]["token"], "[redacted]")

    @patch.dict("os.environ", {
        "ABYSS_DISCORD_ALLOWLIST": "discord:eevee",
        "ABYSS_PUBLIC_APP_URL": "https://vela.example",
    })
    def test_notification_preview_is_link_only_and_scope_exact(self) -> None:
        preview = notification_preview("journey-1", "discord:eevee")
        self.assertEqual(preview.body, "Your VELA update is ready: https://vela.example/#appointments?result=journey-1")
        self.assertNotIn("MRI", preview.body)
        self.assertIn("journey-1", preview.consent_scope)

    @patch.dict("os.environ", {"ABYSS_DISCORD_ALLOWLIST": "discord:eevee"})
    @patch("abyss.messaging.urlopen", return_value=_Response())
    def test_discord_send_requires_the_preview_scope(self, _open) -> None:
        preview = notification_preview("receipt-1", "discord:eevee")
        adapter = DiscordMessagingAdapter("https://discord.com/api/webhooks/1/token")
        with self.assertRaises(MessagingError):
            adapter.send(preview, approved_scope="some other message")
        receipt = adapter.send(preview, approved_scope=preview.consent_scope)
        self.assertEqual(receipt["confirmation_reference"], "discord-message-1")

    @patch.dict("os.environ", {
        "ABYSS_DISCORD_ALLOWLIST": "discord:eevee",
        "ABYSS_SMS_ALLOWLIST": "+15082908822",
    }, clear=False)
    def test_channel_factories_default_to_sandbox_and_redact(self) -> None:
        discord = messaging_adapter("discord")
        twilio = messaging_adapter("twilio")
        self.assertIsInstance(discord, DiscordSandboxAdapter)
        self.assertIsInstance(twilio, TwilioSandboxAdapter)

        preview = notification_preview(
            "receipt-2", "+15082908822", channel="twilio"
        )
        receipt = twilio.send(preview, approved_scope=preview.consent_scope)
        self.assertTrue(receipt["sandbox"])
        self.assertEqual(receipt["destination_redacted"], "***8822")
        self.assertNotIn("+15082908822", preview.consent_scope)

    @patch.dict("os.environ", {"ABYSS_SMS_ALLOWLIST": "+15082908822"}, clear=False)
    def test_adapter_rejects_non_link_only_body(self) -> None:
        preview = notification_preview("receipt-3", "+15082908822", channel="twilio")
        unsafe = type(preview)(
            preview.channel,
            preview.destination_label,
            preview.result_ref,
            "Your MRI is ready: " + preview.secure_link,
            preview.consent_scope,
            preview.message_kind,
            preview.secure_link,
        )
        with self.assertRaises(MessagingError):
            TwilioSandboxAdapter().send(unsafe, approved_scope=unsafe.consent_scope)

    @patch.dict("os.environ", {"ABYSS_SMS_ALLOWLIST": "+15082908822"}, clear=False)
    @patch("abyss.messaging.urlopen", return_value=_Response({"sid": "SM-synthetic-1"}))
    def test_explicit_live_twilio_posts_link_only_and_returns_sanitized_receipt(self, opened) -> None:
        preview = notification_preview("receipt-4", "+15082908822", channel="twilio")
        adapter = TwilioMessagingAdapter("ACsynthetic", "secret-token", "+15085550100")
        receipt = adapter.send(preview, approved_scope=preview.consent_scope)
        request = opened.call_args.args[0]
        self.assertIn(b"To=%2B15082908822", request.data)
        self.assertIn(b"Body=Your+VELA+update+is+ready%3A+", request.data)
        self.assertIn(b"result%3Dreceipt-4", request.data)
        self.assertEqual(receipt["confirmation_reference"], "SM-synthetic-1")
        self.assertFalse(receipt["sandbox"])
        self.assertNotIn("secret-token", str(receipt))
        self.assertNotIn("+15082908822", str(receipt))


if __name__ == "__main__":
    unittest.main()
