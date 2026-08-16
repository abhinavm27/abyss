"""Versioned fact and user-memory ledger with explicit provenance."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .domain import ConsentAction, DecisionFact, VerificationStatus


@dataclass(frozen=True, slots=True)
class UserMemoryRecord:
    user_id: str
    fact_id: str
    version: int
    fact: DecisionFact
    effective_at: datetime | None = None
    ends_at: datetime | None = None
    superseded_by: str | None = None


class FactLedger:
    def __init__(self) -> None:
        self._records: list[UserMemoryRecord] = []

    def append(self, user_id: str, fact_id: str, fact: DecisionFact, *, effective_at: datetime | None = None) -> UserMemoryRecord:
        previous = [record for record in self._records if record.user_id == user_id and record.fact.name == fact.name]
        record = UserMemoryRecord(user_id, fact_id, len(previous) + 1, fact, effective_at)
        self._records.append(record)
        return record

    def records(self, user_id: str) -> tuple[UserMemoryRecord, ...]:
        return tuple(record for record in self._records if record.user_id == user_id)

    def current(self, user_id: str, name: str) -> UserMemoryRecord | None:
        matches = [record for record in self.records(user_id) if record.fact.name == name and record.superseded_by is None]
        return matches[-1] if matches else None

    def mark_verified(self, fact_id: str) -> UserMemoryRecord:
        for index, record in enumerate(self._records):
            if record.fact_id == fact_id:
                verified = DecisionFact(record.fact.name, record.fact.value, record.fact.source,
                                        record.fact.observed_at, record.fact.confidence,
                                        VerificationStatus.VERIFIED, record.fact.consent_required)
                updated = UserMemoryRecord(record.user_id, record.fact_id, record.version, verified,
                                           record.effective_at, record.ends_at, record.superseded_by)
                self._records[index] = updated
                return updated
        raise KeyError(fact_id)


class PersistentMemoryStore:
    """SQLite-backed, user-scoped memory projection for every channel."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def record_fact(
        self,
        user_id: int,
        fact: DecisionFact,
        *,
        supersede_prior: bool = True,
    ) -> dict[str, Any]:
        current = self.conn.execute(
            """SELECT * FROM user_memory_fact
               WHERE user_id=? AND fact_name=? AND superseded_by IS NULL
               ORDER BY id DESC LIMIT 1""",
            (user_id, fact.name),
        ).fetchone()
        encoded = json.dumps(fact.value, separators=(",", ":"), default=str)
        if current and current["value_json"] == encoded and current["source"] == fact.source:
            return self._fact_row(current)
        now = datetime.now(UTC).isoformat()
        cursor = self.conn.execute(
            """INSERT INTO user_memory_fact
               (user_id,fact_name,value_json,source,observed_at,confidence,
                verification_status,consent_requirement,superseded_by,created_at)
               VALUES (?,?,?,?,?,?,?,?,NULL,?)""",
            (
                user_id,
                fact.name,
                encoded,
                fact.source,
                fact.observed_at.isoformat(),
                fact.confidence,
                fact.verification_status.value,
                fact.consent_required.value if fact.consent_required else None,
                now,
            ),
        )
        fact_id = int(cursor.lastrowid)
        if current and supersede_prior:
            self.conn.execute(
                "UPDATE user_memory_fact SET superseded_by=? WHERE id=?",
                (fact_id, current["id"]),
            )
        self.append_event(
            user_id,
            agent_role="memory",
            event_type="fact_recorded",
            payload={"fact_name": fact.name, "source": fact.source},
            related_ref=f"memory-fact:{fact_id}",
            commit=False,
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT * FROM user_memory_fact WHERE id=?", (fact_id,)
        ).fetchone()
        return self._fact_row(row)

    def sync_journey_facts(self, user_id: int, facts: list[dict[str, Any]]) -> None:
        for item in facts:
            try:
                consent = item.get("consent_requirement")
                self.record_fact(
                    user_id,
                    DecisionFact(
                        name=str(item["name"]),
                        value=item.get("value"),
                        source=str(item["source"]),
                        observed_at=datetime.fromisoformat(str(item["observed_at"])),
                        confidence=float(item["confidence"]),
                        verification_status=VerificationStatus(
                            str(item["verification_status"])
                        ),
                        consent_required=None if not consent else ConsentAction(str(consent)),
                    ),
                )
            except (KeyError, TypeError, ValueError):
                continue

    def append_event(
        self,
        user_id: int,
        *,
        agent_role: str,
        event_type: str,
        payload: dict[str, Any],
        related_ref: str | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        safe_payload = self._redact(payload)
        created_at = datetime.now(UTC).isoformat()
        cursor = self.conn.execute(
            """INSERT INTO agent_memory_event
               (user_id,agent_role,event_type,payload_json,related_ref,created_at)
               VALUES (?,?,?,?,?,?)""",
            (
                user_id,
                agent_role[:80],
                event_type[:80],
                json.dumps(safe_payload, separators=(",", ":"), default=str),
                related_ref,
                created_at,
            ),
        )
        if commit:
            self.conn.commit()
        return {
            "id": int(cursor.lastrowid),
            "agent_role": agent_role,
            "event_type": event_type,
            "payload": safe_payload,
            "related_ref": related_ref,
            "created_at": created_at,
        }

    def view(self, user_id: int) -> dict[str, Any]:
        facts = [self._fact_row(row) for row in self.conn.execute(
            """SELECT * FROM user_memory_fact
               WHERE user_id=? AND superseded_by IS NULL ORDER BY id DESC""",
            (user_id,),
        ).fetchall()]
        history = [self._event_row(row) for row in self.conn.execute(
            """SELECT * FROM agent_memory_event WHERE user_id=?
               ORDER BY id DESC LIMIT 100""",
            (user_id,),
        ).fetchall()]
        plan = self.conn.execute(
            """SELECT id,label,payer_name,qhp_plan_id,deductible,deductible_met,
                      coinsurance_pct,copay,oop_max,oop_met
               FROM plan WHERE user_id=? AND is_active=1 ORDER BY id DESC LIMIT 1""",
            (user_id,),
        ).fetchone()
        return {
            "user_id": str(user_id),
            "current_facts": facts,
            "active_plan": dict(plan) if plan else None,
            "agent_events": history,
        }

    def hermes_snapshot(self, user_id: int) -> dict[str, Any]:
        view = self.view(user_id)
        plan = view["active_plan"]
        return {
            "facts": [
                {
                    "name": item["name"],
                    "value": item["value"],
                    "source": item["source"],
                    "confidence": item["confidence"],
                    "verification_status": item["verification_status"],
                }
                for item in view["current_facts"]
            ],
            "active_plan": None if not plan else {
                key: plan.get(key) for key in (
                    "label", "payer_name", "deductible", "deductible_met",
                    "coinsurance_pct", "copay", "oop_max", "oop_met",
                )
            },
        }

    @staticmethod
    def _fact_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "name": row["fact_name"],
            "value": json.loads(row["value_json"]),
            "source": row["source"],
            "observed_at": row["observed_at"],
            "confidence": float(row["confidence"]),
            "verification_status": row["verification_status"],
            "consent_requirement": row["consent_requirement"],
            "superseded_by": row["superseded_by"],
        }

    @staticmethod
    def _event_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "agent_role": row["agent_role"],
            "event_type": row["event_type"],
            "payload": json.loads(row["payload_json"]),
            "related_ref": row["related_ref"],
            "created_at": row["created_at"],
        }

    @classmethod
    def _redact(cls, value: Any) -> Any:
        secret_keys = {"token", "password", "api_key", "authorization", "member_id"}
        if isinstance(value, dict):
            return {
                str(key): "[redacted]" if str(key).lower() in secret_keys else cls._redact(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [cls._redact(item) for item in value]
        return value
