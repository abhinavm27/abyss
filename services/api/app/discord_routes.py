"""Allowlisted inbound Discord turns routed into the current care engine."""

from __future__ import annotations

import os
import re
import sqlite3
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field


_MENTION = re.compile(r"<@!?\d+>")


class DiscordTurnIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    discord_user_id: str = Field(min_length=1, max_length=64)
    discord_channel_id: str = Field(min_length=1, max_length=64)
    discord_guild_id: str | None = Field(default=None, max_length=64)


def _items(name: str) -> set[str]:
    return {item.strip() for item in os.getenv(name, "").split(",") if item.strip()}


def _user_map() -> dict[str, int]:
    result: dict[str, int] = {}
    for item in os.getenv("DISCORD_USER_MAP", "").split(","):
        if ":" not in item:
            continue
        external, internal = item.split(":", 1)
        if internal.strip().isdigit():
            result[external.strip()] = int(internal.strip())
    return result


def _resolve_user(discord_user_id: str) -> int | None:
    mapped = _user_map().get(discord_user_id)
    if mapped is not None:
        return mapped
    fallback = os.getenv("ABYSS_DISCORD_DEFAULT_USER_ID", "").strip()
    return int(fallback) if fallback.isdigit() else None


def build_discord_router(*, get_conn, turn_handler: Callable) -> APIRouter:
    router = APIRouter(prefix="/api/discord", tags=["discord"])

    def authorize(
        x_abyss_discord_secret: Annotated[str | None, Header()] = None,
    ) -> None:
        expected = os.getenv("DISCORD_BOT_SECRET", "").strip()
        if not expected:
            raise HTTPException(status_code=503, detail="Discord bot is not configured")
        if x_abyss_discord_secret != expected:
            raise HTTPException(status_code=401, detail="invalid Discord bot secret")

    @router.post("/turn")
    def discord_turn(
        body: DiscordTurnIn,
        conn: sqlite3.Connection = Depends(get_conn),
        _: None = Depends(authorize),
    ):
        channels = _items("DISCORD_ALLOWED_CHANNEL_IDS")
        guilds = _items("DISCORD_ALLOWED_GUILD_IDS")
        if channels and body.discord_channel_id not in channels:
            raise HTTPException(status_code=403, detail="channel not allowlisted")
        if guilds and body.discord_guild_id not in guilds:
            raise HTTPException(status_code=403, detail="guild not allowlisted")
        user_id = _resolve_user(body.discord_user_id)
        if user_id is None:
            raise HTTPException(status_code=403, detail="Discord user is not mapped")
        question = re.sub(r"\s+", " ", _MENTION.sub(" ", body.question)).strip()
        if not question:
            raise HTTPException(status_code=422, detail="question is empty")
        return turn_handler(conn, user_id, question)

    return router
