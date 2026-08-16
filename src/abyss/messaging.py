"""Consent-bound, allowlisted, link-only messaging adapters.

Sandbox delivery is the default. Live Discord or Twilio delivery must be selected
explicitly with ``ABYSS_MESSAGING_MODE=live`` and valid channel credentials.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


class MessagingError(RuntimeError):
    """A safe messaging failure that never includes credentials or destinations."""


@dataclass(frozen=True, slots=True)
class MessagePreview:
    channel: str
    destination_label: str
    result_ref: str
    body: str
    consent_scope: str
    message_kind: str = "result_link"
    secure_link: str = ""


class MessagingAdapter(Protocol):
    """Channel adapter contract shared by sandbox and explicit live adapters."""

    def send(self, preview: MessagePreview, *, approved_scope: str) -> dict[str, Any]: ...


def _csv_env(name: str, default: str = "") -> set[str]:
    return {item.strip() for item in os.getenv(name, default).split(",") if item.strip()}


def normalize_phone(value: str) -> str:
    raw = value.strip()
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 10:
        digits = "1" + digits
    if len(digits) != 11 or not digits.startswith("1"):
        raise MessagingError("a valid US SMS destination is required")
    return "+" + digits


def normalize_destination(channel: str, value: str) -> str:
    selected = channel.strip().lower()
    if selected == "discord":
        destination = value.strip()
        if not destination.lower().startswith("discord:") or len(destination) > 120:
            raise MessagingError("a valid Discord destination label is required")
        return destination
    if selected == "twilio":
        return normalize_phone(value)
    raise MessagingError("unsupported messaging channel")


def redacted_destination(channel: str, value: str) -> str:
    destination = normalize_destination(channel, value)
    if channel == "twilio":
        return f"***{destination[-4:]}"
    label = destination.removeprefix("discord:")
    return f"discord:{label[:2]}***" if label else "discord:***"


def consent_destination(channel: str, value: str) -> str:
    """Identify one exact destination without exposing it in stored consent."""

    destination = normalize_destination(channel, value)
    fingerprint = hashlib.sha256(destination.encode("utf-8")).hexdigest()[:10]
    return f"{redacted_destination(channel, destination)}#{fingerprint}"


def allowed_destinations(channel: str) -> set[str]:
    selected = channel.strip().lower()
    if selected == "discord":
        default = os.getenv("DISCORD_DESTINATION_LABEL", "discord:eevee").strip()
        raw = _csv_env("ABYSS_DISCORD_ALLOWLIST", default)
    elif selected == "twilio":
        raw = _csv_env("ABYSS_SMS_ALLOWLIST")
    else:
        raise MessagingError("unsupported messaging channel")
    allowed: set[str] = set()
    for item in raw:
        try:
            allowed.add(normalize_destination(selected, item))
        except MessagingError:
            continue
    return allowed


def allowed_discord_destinations() -> set[str]:
    """Backward-compatible Discord allowlist accessor."""

    return allowed_destinations("discord")


def _validate_preview(preview: MessagePreview, approved_scope: str, channel: str) -> None:
    if preview.channel != channel:
        raise MessagingError("the approved channel does not match the adapter")
    if approved_scope != preview.consent_scope:
        raise MessagingError("the exact message scope is not approved")
    if preview.destination_label not in allowed_destinations(channel):
        raise MessagingError("the messaging destination is not allowlisted")
    expected = f"Your VELA update is ready: {preview.secure_link}"
    if not preview.secure_link or preview.body != expected:
        raise MessagingError("ordinary notifications must contain only the approved secure link")


def notification_preview(
    result_ref: str,
    destination_label: str,
    *,
    channel: str | None = None,
    message_kind: str = "result_link",
) -> MessagePreview:
    reference = result_ref.strip()
    selected = (channel or ("discord" if destination_label.lower().startswith("discord:") else "twilio")).lower()
    if not reference or len(reference) > 200:
        raise MessagingError("a short result reference is required")
    if message_kind != "result_link":
        raise MessagingError("unsupported message kind")
    destination = normalize_destination(selected, destination_label)
    if destination not in allowed_destinations(selected):
        raise MessagingError("the messaging destination is not allowlisted")
    public_url = os.getenv("ABYSS_PUBLIC_APP_URL", "http://100.102.193.84:4173").rstrip("/")
    link = f"{public_url}/#appointments?result={quote(reference, safe='')}"
    body = f"Your VELA update is ready: {link}"
    scope = f"send {selected}:{message_kind}:{reference} -> {consent_destination(selected, destination)}"
    return MessagePreview(selected, destination, reference, body, scope, message_kind, link)


class _SandboxAdapter:
    channel: str

    def send(self, preview: MessagePreview, *, approved_scope: str) -> dict[str, Any]:
        _validate_preview(preview, approved_scope, self.channel)
        stamp = int(datetime.now(UTC).timestamp() * 1000)
        return {
            "ok": True,
            "channel": self.channel,
            "confirmation_reference": f"sandbox-{self.channel}-{stamp}",
            "destination_redacted": redacted_destination(self.channel, preview.destination_label),
            "message_kind": preview.message_kind,
            "sandbox": True,
        }


class DiscordSandboxAdapter(_SandboxAdapter):
    channel = "discord"


class TwilioSandboxAdapter(_SandboxAdapter):
    channel = "twilio"


class DiscordMessagingAdapter:
    """Explicit-live Discord webhook adapter retained for compatibility."""

    def __init__(self, webhook_url: str | None = None) -> None:
        self.webhook_url = (webhook_url or os.getenv("DISCORD_WEBHOOK_URL", "")).strip()
        if not self.webhook_url.startswith((
            "https://discord.com/api/webhooks/",
            "https://discordapp.com/api/webhooks/",
        )):
            raise MessagingError("a valid Discord webhook is not configured")

    def send(self, preview: MessagePreview, *, approved_scope: str) -> dict[str, Any]:
        _validate_preview(preview, approved_scope, "discord")
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
            "destination_redacted": redacted_destination("discord", preview.destination_label),
            "message_kind": preview.message_kind,
            "sandbox": False,
        }


class TwilioMessagingAdapter:
    """Explicit-live Twilio SMS adapter; sandbox remains the default factory mode."""

    def __init__(
        self,
        account_sid: str | None = None,
        auth_token: str | None = None,
        from_number: str | None = None,
    ) -> None:
        self.account_sid = (account_sid or os.getenv("TWILIO_ACCOUNT_SID", "")).strip()
        self.auth_token = (auth_token or os.getenv("TWILIO_AUTH_TOKEN", "")).strip()
        raw_from = (from_number or os.getenv("TWILIO_FROM_NUMBER", "")).strip()
        if not self.account_sid.startswith("AC") or not self.auth_token or not raw_from:
            raise MessagingError("valid Twilio credentials are not configured")
        self.from_number = normalize_phone(raw_from)

    def send(self, preview: MessagePreview, *, approved_scope: str) -> dict[str, Any]:
        _validate_preview(preview, approved_scope, "twilio")
        endpoint = f"https://api.twilio.com/2010-04-01/Accounts/{quote(self.account_sid, safe='')}/Messages.json"
        credentials = base64.b64encode(f"{self.account_sid}:{self.auth_token}".encode()).decode()
        request = Request(
            endpoint,
            data=urlencode({
                "To": preview.destination_label,
                "From": self.from_number,
                "Body": preview.body,
            }).encode(),
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=15) as response:
                payload = json.load(response)
        except HTTPError as exc:
            raise MessagingError(f"Twilio Messages API returned HTTP {exc.code}") from exc
        except (URLError, TimeoutError) as exc:
            raise MessagingError("cannot reach the Twilio Messages API") from exc
        except json.JSONDecodeError as exc:
            raise MessagingError("Twilio returned invalid JSON") from exc
        sid = str(payload.get("sid") or "")
        if not sid:
            raise MessagingError("Twilio did not return a message reference")
        return {
            "ok": True,
            "channel": "twilio",
            "confirmation_reference": sid,
            "destination_redacted": redacted_destination("twilio", preview.destination_label),
            "message_kind": preview.message_kind,
            "sandbox": False,
        }


def messaging_adapter(channel: str, *, mode: str | None = None) -> MessagingAdapter:
    """Select a channel adapter, defaulting to non-delivering sandbox mode."""

    selected = channel.strip().lower()
    selected_mode = (mode or os.getenv("ABYSS_MESSAGING_MODE", "sandbox")).strip().lower()
    if selected_mode not in {"sandbox", "live"}:
        raise MessagingError("unsupported messaging mode")
    if selected == "discord":
        return DiscordSandboxAdapter() if selected_mode == "sandbox" else DiscordMessagingAdapter()
    if selected == "twilio":
        return TwilioSandboxAdapter() if selected_mode == "sandbox" else TwilioMessagingAdapter()
    raise MessagingError("unsupported messaging channel")
