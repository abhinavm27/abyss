"""Authenticated notification preferences, previews, and exact-consent sends."""

from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from abyss.memory import PersistentMemoryStore
from abyss.messaging import (
    DiscordMessagingAdapter,
    MessagingError,
    allowed_discord_destinations,
    notification_preview,
)


class MessagingPreferenceIn(BaseModel):
    enabled: bool
    destination_label: str = Field(default="discord:eevee", min_length=1, max_length=120)


class NotificationIn(BaseModel):
    result_ref: str = Field(min_length=1, max_length=200)
    consent_scope: str = Field(min_length=1, max_length=500)
    consent_approved: bool


class NotificationPreviewIn(BaseModel):
    result_ref: str = Field(min_length=1, max_length=200)


def build_messaging_router(*, get_conn, require_user) -> APIRouter:
    router = APIRouter(tags=["messaging"])

    def preference(conn: sqlite3.Connection, user_id: int) -> dict:
        row = conn.execute(
            "SELECT * FROM messaging_preference WHERE user_id=?", (user_id,)
        ).fetchone()
        destination = next(iter(sorted(allowed_discord_destinations())), "discord:eevee")
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
        result["webhook_configured"] = bool(os.getenv("DISCORD_WEBHOOK_URL"))
        return result

    @router.put("/api/me/messaging")
    def set_preference(
        body: MessagingPreferenceIn,
        conn: sqlite3.Connection = Depends(get_conn),
        user_id: int = Depends(require_user),
    ):
        if body.destination_label not in allowed_discord_destinations():
            raise HTTPException(status_code=403, detail="the Discord destination is not allowlisted")
        now = datetime.now(UTC).isoformat()
        scope = f"enable link-only Discord notifications -> {body.destination_label}"
        conn.execute(
            """INSERT INTO messaging_preference
               (user_id,channel,destination_label,enabled,consent_scope,consented_at,updated_at)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET
                 channel=excluded.channel,destination_label=excluded.destination_label,
                 enabled=excluded.enabled,consent_scope=excluded.consent_scope,
                 consented_at=excluded.consented_at,updated_at=excluded.updated_at""",
            (user_id, "discord", body.destination_label, int(body.enabled), scope,
             now if body.enabled else None, now),
        )
        PersistentMemoryStore(conn).append_event(
            user_id,
            agent_role="messaging",
            event_type="preference_updated",
            payload={"channel": "discord", "enabled": body.enabled,
                     "destination": body.destination_label},
            related_ref="messaging-preference",
            commit=False,
        )
        conn.commit()
        return get_preference(conn, user_id)

    @router.post("/api/results/notify/preview")
    def preview_notification(
        body: NotificationPreviewIn,
        conn: sqlite3.Connection = Depends(get_conn),
        user_id: int = Depends(require_user),
    ):
        pref = preference(conn, user_id)
        if not pref["enabled"]:
            raise HTTPException(status_code=409, detail="enable Discord notifications first")
        try:
            item = notification_preview(body.result_ref, pref["destination_label"])
        except MessagingError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "channel": item.channel, "destination_label": item.destination_label,
            "result_ref": item.result_ref, "body": item.body,
            "consent_scope": item.consent_scope,
        }

    def send_notification(
        body: NotificationIn,
        conn: sqlite3.Connection,
        user_id: int,
    ):
        pref = preference(conn, user_id)
        if not pref["enabled"]:
            raise HTTPException(status_code=409, detail="Discord notifications are not enabled")
        if not body.consent_approved:
            raise HTTPException(status_code=409, detail="exact message approval is required")
        try:
            item = notification_preview(body.result_ref, pref["destination_label"])
            receipt = DiscordMessagingAdapter().send(item, approved_scope=body.consent_scope)
        except MessagingError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        now = datetime.now(UTC).isoformat()
        conn.execute(
            """INSERT INTO messaging_receipt
               (user_id,channel,destination_redacted,message_kind,result_ref,
                confirmation_reference,sandbox,consent_scope,created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (user_id, "discord", item.destination_label, "result_link", item.result_ref,
             receipt["confirmation_reference"], int(receipt["sandbox"]),
             item.consent_scope, now),
        )
        PersistentMemoryStore(conn).append_event(
            user_id,
            agent_role="messaging",
            event_type="message_sent",
            payload={"channel": "discord", "result_ref": item.result_ref,
                     "destination": item.destination_label},
            related_ref=receipt["confirmation_reference"],
            commit=False,
        )
        conn.commit()
        return receipt

    @router.post("/api/results/notify")
    def notify(
        body: NotificationIn,
        conn: sqlite3.Connection = Depends(get_conn),
        user_id: int = Depends(require_user),
    ):
        return send_notification(body, conn, user_id)

    # Backward-compatible endpoint name used by the previous frontend.
    @router.post("/api/results/notify-sms")
    def notify_legacy(
        body: NotificationIn,
        conn: sqlite3.Connection = Depends(get_conn),
        user_id: int = Depends(require_user),
    ):
        return send_notification(body, conn, user_id)

    return router
