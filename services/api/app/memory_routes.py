"""Authenticated member-memory ledger and redacted Hermes snapshot routes."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from abyss.domain import DecisionFact, VerificationStatus
from abyss.memory import PersistentMemoryStore


class UserFactIn(BaseModel):
    fact_name: str = Field(min_length=1, max_length=120)
    value: object
    source: str = Field(min_length=1, max_length=200)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)


class AgentEventIn(BaseModel):
    agent_role: str = Field(min_length=1, max_length=80)
    event_type: str = Field(min_length=1, max_length=80)
    payload: dict = Field(default_factory=dict)
    related_ref: str | None = Field(default=None, max_length=200)


def build_memory_router(*, get_conn, require_user) -> APIRouter:
    router = APIRouter(prefix="/api/me/memory", tags=["memory"])

    @router.get("")
    def get_memory(
        conn: sqlite3.Connection = Depends(get_conn),
        user_id: int = Depends(require_user),
    ):
        return PersistentMemoryStore(conn).view(user_id)

    @router.get("/hermes-snapshot")
    def get_hermes_snapshot(
        conn: sqlite3.Connection = Depends(get_conn),
        user_id: int = Depends(require_user),
    ):
        return PersistentMemoryStore(conn).hermes_snapshot(user_id)

    @router.post("/facts")
    def record_fact(
        body: UserFactIn,
        conn: sqlite3.Connection = Depends(get_conn),
        user_id: int = Depends(require_user),
    ):
        try:
            return PersistentMemoryStore(conn).record_fact(
                user_id,
                DecisionFact(
                    name=body.fact_name,
                    value=body.value,
                    source=body.source,
                    observed_at=datetime.now(UTC),
                    confidence=body.confidence,
                    verification_status=VerificationStatus.SOURCE_BACKED,
                ),
            )
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/agent-events")
    def record_agent_event(
        body: AgentEventIn,
        conn: sqlite3.Connection = Depends(get_conn),
        user_id: int = Depends(require_user),
    ):
        return PersistentMemoryStore(conn).append_event(
            user_id,
            agent_role=body.agent_role,
            event_type=body.event_type,
            payload=body.payload,
            related_ref=body.related_ref,
        )

    return router
