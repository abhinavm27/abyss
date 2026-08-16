import importlib.util
import os
import unittest
from unittest.mock import patch


FASTAPI_AVAILABLE = importlib.util.find_spec("fastapi") is not None


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI is installed in the API runtime")
class DiscordChannelTests(unittest.TestCase):
    def setUp(self) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from services.api.app.discord_routes import build_discord_router

        self.turns = []

        def get_conn():
            return None

        def handler(_conn, user_id, question):
            self.turns.append((user_id, question))
            return {"reply": "grounded", "user_id": user_id}

        app = FastAPI()
        app.include_router(build_discord_router(get_conn=get_conn, turn_handler=handler))
        self.client = TestClient(app)

    @patch.dict(os.environ, {
        "DISCORD_BOT_SECRET": "shared-secret",
        "DISCORD_ALLOWED_CHANNEL_IDS": "channel-1",
        "ABYSS_DISCORD_DEFAULT_USER_ID": "7",
    }, clear=False)
    def test_allowlisted_turn_strips_mention_and_maps_user(self) -> None:
        response = self.client.post(
            "/api/discord/turn",
            json={
                "question": "<@123> book an MRI",
                "discord_user_id": "external-1",
                "discord_channel_id": "channel-1",
            },
            headers={"X-Abyss-Discord-Secret": "shared-secret"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.turns, [(7, "book an MRI")])

    @patch.dict(os.environ, {
        "DISCORD_BOT_SECRET": "shared-secret",
        "DISCORD_ALLOWED_CHANNEL_IDS": "channel-1",
        "ABYSS_DISCORD_DEFAULT_USER_ID": "7",
    }, clear=False)
    def test_discord_route_rejects_wrong_secret_and_channel(self) -> None:
        body = {
            "question": "status",
            "discord_user_id": "external-1",
            "discord_channel_id": "other",
        }
        self.assertEqual(self.client.post(
            "/api/discord/turn", json=body,
            headers={"X-Abyss-Discord-Secret": "wrong"},
        ).status_code, 401)
        self.assertEqual(self.client.post(
            "/api/discord/turn", json=body,
            headers={"X-Abyss-Discord-Secret": "shared-secret"},
        ).status_code, 403)


if __name__ == "__main__":
    unittest.main()
