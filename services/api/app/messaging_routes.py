"""Authenticated notification preferences, previews, and exact-consent sends."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator

from abyss.memory import PersistentMemoryStore
from abyss.messaging import (
    MessagingError,
    allowed_destinations,
    appointment_notification_preview,
    consent_destination,
    messaging_adapter,
    normalize_destination,
    notification_preview,
    provider_list_notification_preview,
    redacted_destination,
)

_MESSAGE_KIND_PATTERN = "^(result_link|appointment_confirmed|provider_list)$"


class MessagingPreferenceIn(BaseModel):
    enabled: bool
    destination_label: str = Field(default="discord:eevee", min_length=1, max_length=120)
    channel: str = Field(default="discord", pattern="^(discord|twilio)$")


class NotificationPreviewIn(BaseModel):
    """Which real record to build a notification from.

    Exactly one reference is required, matching message_kind: result_ref for
    result_link, appointment_id for appointment_confirmed, journey_id for
    provider_list. The route looks the record up itself and scopes it to the
    requesting member — none of this is trusted from the client as text.
    """

    message_kind: str = Field(default="result_link", pattern=_MESSAGE_KIND_PATTERN)
    result_ref: str | None = Field(default=None, max_length=200)
    appointment_id: str | None = Field(default=None, max_length=200)
    journey_id: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _require_matching_reference(self) -> "NotificationPreviewIn":
        needed = {
            "result_link": self.result_ref,
            "appointment_confirmed": self.appointment_id,
            "provider_list": self.journey_id,
        }[self.message_kind]
        if not needed or not needed.strip():
            raise ValueError(f"{self.message_kind} requires its matching reference field")
        return self


class NotificationIn(NotificationPreviewIn):
    consent_scope: str = Field(min_length=1, max_length=500)
    consent_approved: bool


def _preview_ref(scope: str) -> str:
    return "message-preview:" + hashlib.sha256(scope.encode("utf-8")).hexdigest()


def _fetch_appointment_dict(
    conn: sqlite3.Connection, catalog_conn: sqlite3.Connection, appointment_id: str, user_id: int
) -> dict | None:
    """A member's own appointment, with its hospital name joined from the catalog.

    `appointment.hospital_id` references the knowledge catalog's `hospital`
    table, not this state database — the two are different SQLite files with
    the same schema (see api.py's list_appointments for the identical pattern).
    """
    row = conn.execute(
        "SELECT * FROM appointment WHERE appointment_id=? AND user_id=?",
        (appointment_id, user_id),
    ).fetchone()
    if row is None:
        return None
    result = dict(row)
    hospital_name = None
    if result.get("hospital_id") is not None:
        hospital_row = catalog_conn.execute(
            "SELECT name FROM hospital WHERE id=?", (result["hospital_id"],)
        ).fetchone()
        hospital_name = hospital_row["name"] if hospital_row else None
    result["hospital"] = hospital_name or "your selected facility"
    return result


def _fetch_provider_list(
    conn: sqlite3.Connection, journey_id: str, user_id: int
) -> tuple[str, list[dict]] | None:
    """A member's own journey's procedure and priced hospital options.

    Reads the persisted snapshot rather than the process-local live journey
    registry — notifications should reflect the same durable record the
    member sees on reload, and must work after a server restart.
    """
    row = conn.execute(
        "SELECT snapshot_json FROM care_journey WHERE journey_id=? AND user_id=?",
        (journey_id, user_id),
    ).fetchone()
    if row is None:
        return None
    snapshot = json.loads(row["snapshot_json"])
    options = snapshot.get("current_plan_options") or []
    procedure = "your requested care"
    for fact in snapshot.get("facts", []):
        if fact.get("name") == "requested_procedure" and fact.get("value"):
            procedure = str(fact["value"])
            break
    return procedure, options


def build_messaging_router(*, get_conn, require_user, get_catalog_conn) -> APIRouter:
    router = APIRouter(tags=["messaging"])

    def build_preview(
        body: "NotificationPreviewIn",
        conn: sqlite3.Connection,
        catalog: sqlite3.Connection,
        user_id: int,
        pref: dict,
    ):
        if body.message_kind == "result_link":
            return notification_preview(
                body.result_ref, pref["destination_label"],
                channel=pref["channel"], message_kind="result_link",
            )
        if body.message_kind == "appointment_confirmed":
            appointment = _fetch_appointment_dict(conn, catalog, body.appointment_id, user_id)
            if appointment is None:
                raise MessagingError("that appointment was not found")
            return appointment_notification_preview(
                appointment, pref["destination_label"], channel=pref["channel"],
            )
        if body.message_kind == "provider_list":
            found = _fetch_provider_list(conn, body.journey_id, user_id)
            if found is None:
                raise MessagingError("that journey was not found")
            procedure, options = found
            return provider_list_notification_preview(
                body.journey_id, procedure, options, pref["destination_label"],
                channel=pref["channel"],
            )
        raise MessagingError("unsupported message kind")

    def preference(conn: sqlite3.Connection, user_id: int) -> dict:
        row = conn.execute(
            "SELECT * FROM messaging_preference WHERE user_id=?", (user_id,)
        ).fetchone()
        destination = next(iter(sorted(allowed_destinations("discord"))), "discord:eevee")
        return dict(row) if row else {
            "user_id": user_id,
            "channel": "discord",
            "destination_label": destination,
            "enabled": 0,
            "consent_scope": None,
            "consented_at": None,
        }

    @router.get("/api/me/messaging")
    def get_preference(
        conn: sqlite3.Connection = Depends(get_conn),
        user_id: int = Depends(require_user),
    ):
        result = preference(conn, user_id)
        result["enabled"] = bool(result["enabled"])
        result["adapter_mode"] = os.getenv("ABYSS_MESSAGING_MODE", "sandbox").lower()
        result["webhook_configured"] = bool(os.getenv("DISCORD_WEBHOOK_URL"))
        result["twilio_configured"] = all(os.getenv(name) for name in (
            "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER"
        ))
        return result

    @router.put("/api/me/messaging")
    def set_preference(
        body: MessagingPreferenceIn,
        conn: sqlite3.Connection = Depends(get_conn),
        user_id: int = Depends(require_user),
    ):
        try:
            destination = normalize_destination(body.channel, body.destination_label)
            if destination not in allowed_destinations(body.channel):
                raise MessagingError("the messaging destination is not allowlisted")
            redacted = redacted_destination(body.channel, destination)
        except MessagingError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        now = datetime.now(UTC).isoformat()
        scope = f"enable {body.channel} notifications -> {consent_destination(body.channel, destination)}"
        conn.execute(
            """INSERT INTO messaging_preference
               (user_id,channel,destination_label,enabled,consent_scope,consented_at,updated_at)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET
                 channel=excluded.channel,destination_label=excluded.destination_label,
                 enabled=excluded.enabled,consent_scope=excluded.consent_scope,
                 consented_at=excluded.consented_at,updated_at=excluded.updated_at""",
            (user_id, body.channel, destination, int(body.enabled), scope,
             now if body.enabled else None, now),
        )
        PersistentMemoryStore(conn).append_event(
            user_id,
            agent_role="messaging",
            event_type="preference_updated",
            payload={"channel": body.channel, "enabled": body.enabled,
                     "destination_redacted": redacted},
            related_ref="messaging-preference",
            commit=False,
        )
        conn.commit()
        return get_preference(conn, user_id)

    @router.post("/api/results/notify/preview")
    def preview_notification(
        body: NotificationPreviewIn,
        conn: sqlite3.Connection = Depends(get_conn),
        catalog: sqlite3.Connection = Depends(get_catalog_conn),
        user_id: int = Depends(require_user),
    ):
        pref = preference(conn, user_id)
        if not pref["enabled"]:
            raise HTTPException(status_code=409, detail="enable notifications first")
        try:
            item = build_preview(body, conn, catalog, user_id, pref)
            redacted = redacted_destination(item.channel, item.destination_label)
        except MessagingError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        PersistentMemoryStore(conn).append_event(
            user_id,
            agent_role="messaging",
            event_type="message_previewed",
            payload={
                "channel": item.channel,
                "destination_redacted": redacted,
                "message_kind": item.message_kind,
                "result_ref": item.result_ref,
            },
            related_ref=_preview_ref(item.consent_scope),
        )
        return {
            "channel": item.channel,
            "destination_label": item.destination_label,
            "destination_redacted": redacted,
            "result_ref": item.result_ref,
            "message_kind": item.message_kind,
            "body": item.body,
            "consent_scope": item.consent_scope,
        }

    def send_notification(
        body: NotificationIn,
        conn: sqlite3.Connection,
        catalog: sqlite3.Connection,
        user_id: int,
    ):
        pref = preference(conn, user_id)
        if not pref["enabled"]:
            raise HTTPException(status_code=409, detail="notifications are not enabled")
        if not body.consent_approved:
            raise HTTPException(status_code=409, detail="exact message approval is required")
        try:
            item = build_preview(body, conn, catalog, user_id, pref)
            if body.consent_scope != item.consent_scope:
                raise MessagingError("the exact channel, destination, and message kind are not approved")
            previewed = conn.execute(
                """SELECT 1 FROM agent_memory_event
                   WHERE user_id=? AND event_type='message_previewed' AND related_ref=?
                   ORDER BY id DESC LIMIT 1""",
                (user_id, _preview_ref(item.consent_scope)),
            ).fetchone()
            if not previewed:
                raise MessagingError("preview this exact notification before sending")
            receipt = messaging_adapter(item.channel).send(
                item, approved_scope=body.consent_scope
            )
        except MessagingError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        now = datetime.now(UTC).isoformat()
        destination_redacted = redacted_destination(item.channel, item.destination_label)
        conn.execute(
            """INSERT INTO messaging_receipt
               (user_id,channel,destination_redacted,message_kind,result_ref,
                confirmation_reference,sandbox,consent_scope,created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (user_id, item.channel, destination_redacted, item.message_kind, item.result_ref,
             receipt["confirmation_reference"], int(receipt["sandbox"]),
             item.consent_scope, now),
        )
        PersistentMemoryStore(conn).append_event(
            user_id,
            agent_role="messaging",
            event_type="message_sent",
            payload={"channel": item.channel, "result_ref": item.result_ref,
                     "message_kind": item.message_kind,
                     "destination_redacted": destination_redacted,
                     "sandbox": receipt["sandbox"]},
            related_ref=receipt["confirmation_reference"],
            commit=False,
        )
        conn.commit()
        return receipt

    @router.post("/api/results/notify")
    def notify(
        body: NotificationIn,
        conn: sqlite3.Connection = Depends(get_conn),
        catalog: sqlite3.Connection = Depends(get_catalog_conn),
        user_id: int = Depends(require_user),
    ):
        return send_notification(body, conn, catalog, user_id)

    # Backward-compatible endpoint name used by the previous frontend. It sends
    # through the user's configured channel rather than bypassing preferences.
    @router.post("/api/results/notify-sms")
    def notify_legacy(
        body: NotificationIn,
        conn: sqlite3.Connection = Depends(get_conn),
        catalog: sqlite3.Connection = Depends(get_catalog_conn),
        user_id: int = Depends(require_user),
    ):
        return send_notification(body, conn, catalog, user_id)

    return router
