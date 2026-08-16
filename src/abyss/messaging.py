"""Consent-bound, link-only messaging adapters for member notifications."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


class MessagingError(RuntimeError):
    """A safe messaging failure that never includes credentials."""


@dataclass(frozen=True, slots=True)
class MessagePreview:
    channel: str
    destination_label: str
    result_ref: str
    body: str
    consent_scope: str


def allowed_discord_destinations() -> set[str]:
    default = os.getenv("DISCORD_DESTINATION_LABEL", "discord:eevee").strip()
    raw = os.getenv("ABYSS_DISCORD_ALLOWLIST", default)
    return {item.strip() for item in raw.split(",") if item.strip()}


def notification_preview(result_ref: str, destination_label: str) -> MessagePreview:
    reference = result_ref.strip()
    destination = destination_label.strip()
    if not reference or len(reference) > 200:
        raise MessagingError("a short result reference is required")
    if destination not in allowed_discord_destinations():
        raise MessagingError("the Discord destination is not allowlisted")
    public_url = os.getenv("ABYSS_PUBLIC_APP_URL", "http://100.102.193.84:4173").rstrip("/")
    link = f"{public_url}/#appointments?result={quote(reference, safe='')}"
    body = f"Your VELA update is ready: {link}"
    scope = f"send result link:{reference} -> {destination}"
    return MessagePreview("discord", destination, reference, body, scope)


class DiscordMessagingAdapter:
    """Post an approved generic secure-link notice to a Discord webhook."""

    def __init__(self, webhook_url: str | None = None) -> None:
        self.webhook_url = (webhook_url or os.getenv("DISCORD_WEBHOOK_URL", "")).strip()
        if not self.webhook_url.startswith((
            "https://discord.com/api/webhooks/",
            "https://discordapp.com/api/webhooks/",
        )):
            raise MessagingError("a valid Discord webhook is not configured")

    def send(self, preview: MessagePreview, *, approved_scope: str) -> dict[str, Any]:
        if approved_scope != preview.consent_scope:
            raise MessagingError("the exact Discord message scope is not approved")
        request = Request(
            self.webhook_url + ("&" if "?" in self.webhook_url else "?") + "wait=true",
            data=json.dumps({
                "content": preview.body[:1900],
                "username": os.getenv("DISCORD_WEBHOOK_USERNAME", "vela")[:80],
                "allowed_mentions": {"parse": []},
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=15) as response:
                payload = json.load(response)
        except HTTPError as exc:
            raise MessagingError(f"Discord webhook returned HTTP {exc.code}") from exc
        except (URLError, TimeoutError) as exc:
            raise MessagingError("cannot reach the Discord webhook") from exc
        except json.JSONDecodeError as exc:
            raise MessagingError("Discord returned invalid JSON") from exc
        return {
            "ok": True,
            "channel": "discord",
            "confirmation_reference": str(payload.get("id") or f"discord-{int(datetime.now(UTC).timestamp())}"),
            "destination_redacted": preview.destination_label,
            "sandbox": False,
        }
