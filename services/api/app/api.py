"""FastAPI service: price lookup, estimation, providers, booking, plan.

Runs on :8010 by default.
"""

from __future__ import annotations

import io
import json
import os
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Event, Thread

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from abyss.agent import explain, phrase_intake_request
from abyss.adapters import ActionReceipt
from abyss.booking import BookingSlot
from abyss.care_journey_agent import CareJourneyAgent, JourneyIntent
from abyss.care_paths import CarePathSelection
from abyss.catalogs import SeededCatalog
from abyss.hermes_client import HermesError
from abyss.domain import ConsentAction, DecisionFact, VerificationStatus
from abyss.journey import CareJourney
from abyss.memory import PersistentMemoryStore
from abyss.procedures import ProcedureResolution
from abyss.report_intake import ReportAnalysis, ReportIntakeService
from abyss.workflow import WorkflowStage

from . import auth, db, retrieval
from .config import hospital_knowledge_catalog
from .memory_routes import build_memory_router
from .messaging_routes import build_messaging_router
from .report_routes import build_report_intake_router
from .discord_routes import build_discord_router
from .ingest import sbc
from .estimator import Plan, estimate
from .plan_comparison import (
    EVENT_BUNDLES,
    PricedService,
    simulate_annual_scenario,
    worst_case_scenario,
)
from .ws import voice_endpoint

app = FastAPI(title="VELA", version="0.1.0")

# The journey store is intentionally process-local for the sandbox demo. A
# production deployment would persist the same events and receipts in the
# application database; it must never silently turn a sandbox receipt into a
# production action.
_journeys: dict[str, CareJourney] = {}
_booking_worker_stop = Event()
_care_journey_agent = CareJourneyAgent()
_hospital_knowledge = hospital_knowledge_catalog()
_report_intake = ReportIntakeService()


def _booking_task_worker() -> None:
    while not _booking_worker_stop.wait(1.0):
        for journey in tuple(_journeys.values()):
            try:
                journey.process_booking_tasks()
            except Exception:
                # A single synthetic journey must not stop the task worker.
                continue


@app.on_event("startup")
def start_booking_task_worker() -> None:
    _booking_worker_stop.clear()
    Thread(target=_booking_task_worker, name="booking-task-worker", daemon=True).start()


@app.on_event("shutdown")
def stop_booking_task_worker() -> None:
    _booking_worker_stop.set()


def _journey_dependencies() -> dict:
    """Build adapters without coupling the journey domain to FastAPI."""
    return {"hospital_knowledge": _hospital_knowledge}


@app.websocket("/ws")
async def voice(ws: WebSocket):
    await voice_endpoint(ws, care_turn=_voice_care_turn)

# The Vite dev server proxies /api, but Capacitor serves the built app from
# capacitor://localhost, which is a distinct origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin for origin in os.getenv(
        "ABYSS_CORS_ORIGINS", "http://localhost:5173,capacitor://localhost,http://localhost"
    ).split(",") if origin],
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_conn():
    conn = db.connect()
    db.init_db(conn)
    try:
        yield conn
    finally:
        conn.close()


def get_catalog_conn():
    """The hospital knowledge catalog, as a plain connection for `retrieval.py`.

    `retrieval.py`'s SQL is schema-compatible with the catalog but was written
    against a raw `sqlite3.Connection`, not `HospitalKnowledgeCatalog`. Raises
    rather than silently falling back to the empty state database, so a
    misconfigured catalog fails loudly instead of reporting fabricated results.
    """
    knowledge_db = os.environ.get("ABYSS_KNOWLEDGE_DB")
    conn = db.connect_catalog(knowledge_db)
    if conn is None:
        raise HTTPException(
            status_code=503,
            detail="Hospital price catalog is not configured on this server "
                   "(ABYSS_KNOWLEDGE_DB is unset or unreadable).",
        )
    try:
        yield conn
    finally:
        conn.close()


def get_catalog_conn_optional():
    """The hospital knowledge catalog, or None if it isn't configured.

    For endpoints where pricing/catalog data is only *one* of several things
    they can do (care_agent_message handles status checks, rescheduling, etc.
    too) — those must not hard-fail just because pricing happens to be
    unavailable. Callers that reach a catalog-dependent branch with `None`
    here are expected to say so honestly, not silently substitute the empty
    state database (which is what get_catalog_conn's hard failure exists to
    prevent in the first place).
    """
    knowledge_db = os.environ.get("ABYSS_KNOWLEDGE_DB")
    conn = db.connect_catalog(knowledge_db)
    try:
        yield conn
    finally:
        if conn is not None:
            conn.close()


# --- authentication ---------------------------------------------------------


def optional_user(
    authorization: str | None = Header(default=None),
    conn: sqlite3.Connection = Depends(get_conn),
) -> int | None:
    """The signed-in member, or None. For routes that work either way."""
    return auth.user_for_token(conn, auth.bearer(authorization))


def require_user(user_id: int | None = Depends(optional_user)) -> int:
    """The signed-in member. Anything that touches personal data uses this."""
    if user_id is None:
        raise auth.Unauthorized()
    return user_id


app.include_router(build_memory_router(get_conn=get_conn, require_user=require_user))
app.include_router(build_messaging_router(
    get_conn=get_conn, require_user=require_user, get_catalog_conn=get_catalog_conn,
))


class AgentChatIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    evidence: dict = Field(default_factory=dict)


class JourneyStartIn(BaseModel):
    procedure: str = Field(default="MRI knee without contrast", min_length=1)
    provider: str = Field(default="Dr. Lee", min_length=1)
    facility: str = Field(default="Seattle General", min_length=1)
    empty: bool = False


class JourneyOnboardIn(BaseModel):
    text: str = Field(min_length=1, max_length=10000)
    source: str = Field(default="user_request", min_length=1, max_length=200)


class JourneyConsentIn(BaseModel):
    action: ConsentAction
    scope: str = Field(min_length=1, max_length=500)
    approved: bool


class JourneyActionIn(BaseModel):
    action: ConsentAction
    scope: str = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=200)
    new_effective_date: str | None = None
    first_premium_confirmed: bool = False


class JourneySelectionIn(BaseModel):
    hospital_id: int = Field(gt=0)


class JourneyBookingPreferencesIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class CareAgentMessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=10000)
    active_journey_id: str | None = None
    utterance_id: str | None = Field(default=None, max_length=200)
    correlation_id: str | None = Field(default=None, max_length=200)
    channel: str = Field(default="chat", pattern="^(chat|voice|discord)$")
    reply_to_pending: bool = False


class JourneyRescheduleIn(BaseModel):
    booking_scope: str = Field(min_length=1, max_length=500)
    cancellation_scope: str = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=200)


def _journey_payload(journey: CareJourney) -> dict:
    journey.process_booking_tasks()
    plan_name = journey.catalogs.plan(journey.current_plan_id).name
    payload = {
        "journey_id": journey.journey_id,
        "stage": journey.stage.value,
        "onboarding_missing": list(journey.onboarding_missing),
        "onboarding_questions": list(journey.onboarding_questions),
        "procedure_resolution": ({"code": journey.procedure_resolution.code,
                                  "canonical_name": journey.procedure_resolution.canonical_name,
                                  "confidence": journey.procedure_resolution.confidence,
                                  "candidates": list(journey.procedure_resolution.candidates),
                                  "needs_confirmation": journey.procedure_resolution.needs_confirmation}
                                 if journey.procedure_resolution else None),
        "evaluations": [
            {"plan_id": item.plan_id, "plan_name": item.plan_name, "feasible": item.feasible,
             "annual_total": item.annual_total, "annual_premium": item.annual_premium,
             "hard_failures": list(item.hard_failures)} for item in journey.evaluations
        ],
        "hospital_rates": [item.as_dict() for item in journey.hospital_rates],
        "current_plan": journey.catalogs.plan(journey.current_plan_id).plan_id,
        "current_plan_name": journey.catalogs.plan(journey.current_plan_id).name,
        "current_plan_options": [item.as_dict() for item in journey.current_plan_options],
        "alternative_plan": (
            journey.alternative_plan.as_dict() if journey.alternative_plan else None
        ),
        "selected_care_path": (
            journey.selected_care_path.as_dict() if journey.selected_care_path else None
        ),
        "booking_preferences": (
            journey.booking_preferences.as_dict() if journey.booking_preferences else None
        ),
        "booking_slots": [item.as_dict(plan_name) for item in journey.booking_slots],
        "selected_booking_slot": (
            journey.selected_booking_slot.as_dict(plan_name)
            if journey.selected_booking_slot else None
        ),
        "booking_consent_scope": journey.booking_consent_scope,
        "cancellation_consent_scope": journey.cancellation_consent_scope,
        "reschedule_original_slot": (
            journey.reschedule_original_slot.as_dict(plan_name)
            if journey.reschedule_original_slot else None
        ),
        "reschedule_pending": journey.reschedule_pending,
        "booking_tasks": [
            item.as_dict()
            for item in journey.booking_service.tasks_for_journey(journey.journey_id)
        ],
        "notifications": [
            item.as_dict()
            for item in journey.booking_service.notifications_for_journey(journey.journey_id)
        ],
        "receipts": [
            {"action": receipt.action, "status": receipt.status, "sandbox": receipt.sandbox,
             "scope": receipt.consent_scope, "idempotency_key": receipt.idempotency_key,
             "recorded_at": receipt.recorded_at.isoformat()} for receipt in journey.receipts
        ],
        "events": [
            {"sequence": event.sequence, "type": event.event_type, "actor": event.actor,
             "payload": event.payload, "recorded_at": event.recorded_at.isoformat()}
            for event in journey.audit.for_journey(journey.journey_id)
        ],
        "facts": [
            {"name": fact.name, "value": fact.value, "source": fact.source,
             "observed_at": fact.observed_at.isoformat(), "confidence": fact.confidence,
             "verification_status": fact.verification_status.value,
             "consent_requirement": fact.consent_required.value if fact.consent_required else None}
            for fact in journey.workflow.care_state.facts.values()
        ],
        "consents": [
            {"action": consent.action.value, "approved": consent.approved,
             "actor": consent.actor, "scope": consent.scope,
             "recorded_at": consent.recorded_at.isoformat()}
            for consent in journey.workflow.care_state.consents
        ],
    }
    _persist_journey_projection(journey, payload)
    return payload


def _journey_user_id(journey: CareJourney) -> int:
    return int(journey.workflow.care_state.session_id.rsplit(":", 1)[-1])


def _persist_journey_projection(journey: CareJourney, payload: dict) -> None:
    """Persist a user-scoped projection without making it action authority."""
    conn = db.connect()
    try:
        db.init_db(conn)
        user_id = _journey_user_id(journey)
        now = datetime.now(timezone.utc).isoformat()
        procedure = journey.workflow.care_state.facts.get("requested_procedure")
        title = str(procedure.value) if procedure else "Care journey"
        status = "complete" if journey.stage.value == "complete" else "active"
        conn.execute(
            """INSERT INTO care_journey
               (journey_id,user_id,title,stage,status,snapshot_json,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(journey_id) DO UPDATE SET
                 title=excluded.title, stage=excluded.stage, status=excluded.status,
                 snapshot_json=excluded.snapshot_json, updated_at=excluded.updated_at""",
            (journey.journey_id, user_id, title, journey.stage.value, status,
             json.dumps(payload, default=str, separators=(",", ":")), now, now),
        )
        memory = PersistentMemoryStore(conn)
        memory.sync_journey_facts(user_id, payload.get("facts", []))
        memory.append_event(
            user_id,
            agent_role="care_journey",
            event_type="journey_projected",
            payload={"journey_id": journey.journey_id, "stage": journey.stage.value},
            related_ref=journey.journey_id,
            commit=False,
        )
        selected = journey.selected_booking_slot
        confirmed = selected and journey.booking_service.slot(selected.slot_id)
        if confirmed and confirmed.status == "booked":
            appointment_id = f"appointment-{journey.journey_id}-{confirmed.slot_id}"
            # `appointment.hospital_id` carries a foreign key into *this* state
            # database's `hospital` table, which is empty — real hospitals live
            # in the separate read-only knowledge catalog. Resolving the id
            # against the catalog and then storing it here raises
            # `IntegrityError: FOREIGN KEY constraint failed` and bricks the
            # journey, because this projection re-runs on every later request.
            # The hospital is still identified by name in `description`, so
            # nothing user-visible is lost by leaving the cross-database id out.
            local_hospital_id = None
            conn.execute(
                """INSERT INTO appointment
                   (appointment_id,user_id,journey_id,slot_id,hospital_id,code,description,
                    booked_for,estimated_cost,note,status,source,updated_at,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(appointment_id) DO UPDATE SET
                    status='confirmed', booked_for=excluded.booked_for,
                    updated_at=excluded.updated_at""",
                (appointment_id, user_id, journey.journey_id, confirmed.slot_id,
                 local_hospital_id, confirmed.procedure_code,
                 f"Synthetic appointment at {confirmed.hospital}", confirmed.starts_at,
                 journey.selected_care_path.estimated_member_cost if journey.selected_care_path else None,
                 "Sandbox booking receipt", "confirmed", "sandbox_booking", now, now),
            )
            if any(item.action == ConsentAction.CANCEL_APPOINTMENT.value for item in journey.receipts):
                conn.execute(
                    """UPDATE appointment SET status='cancelled', updated_at=?
                       WHERE user_id=? AND journey_id=? AND appointment_id<>? AND status='confirmed'""",
                    (now, user_id, journey.journey_id, appointment_id),
                )
        conn.commit()
    finally:
        conn.close()


def _user_care_context(conn: sqlite3.Connection, user_id: int) -> dict:
    journey_rows = conn.execute(
        """SELECT journey_id,title,stage,status,snapshot_json,created_at,updated_at
           FROM care_journey WHERE user_id=? ORDER BY updated_at DESC""",
        (user_id,),
    ).fetchall()
    journeys = []
    for row in journey_rows:
        snapshot = json.loads(row["snapshot_json"])
        intake_facts = {
            item["name"]: {
                "value": item.get("value"),
                "source": item.get("source"),
                "verification_status": item.get("verification_status"),
            }
            for item in snapshot.get("facts", [])
            if item.get("name") in {
                "requested_procedure", "procedure_code", "service_date",
                "coverage_end_date", "contrast_status", "preferred_provider",
                "preferred_facility",
            }
        }
        journeys.append({
            "journey_id": row["journey_id"], "title": row["title"],
            "stage": row["stage"], "status": row["status"],
            "selected_care_path": snapshot.get("selected_care_path"),
            "pending_fields": snapshot.get("onboarding_missing", []),
            "pending_questions": snapshot.get("onboarding_questions", []),
            "intake_facts": intake_facts,
            "updated_at": row["updated_at"],
        })
    appointments = [dict(row) for row in conn.execute(
        """SELECT appointment_id,journey_id,slot_id,hospital_id,code,description,
                  booked_for,status,source,updated_at
           FROM appointment WHERE user_id=? ORDER BY booked_for DESC, id DESC""",
        (user_id,),
    ).fetchall()]
    active_plan = _active_plan_row(conn, user_id)
    plan = None if active_plan is None else {
        "plan_id": active_plan["id"], "label": active_plan["label"],
        "payer_name": active_plan["payer_name"], "is_active": bool(active_plan["is_active"]),
    }
    return {
        "user": {"user_id": str(user_id)},
        "current_plan": plan,
        "member_memory": PersistentMemoryStore(conn).hermes_snapshot(user_id),
        "journeys": journeys,
        "appointments": appointments,
        "scheduled_tasks": [
            task for journey in _journeys.values()
            if _journey_user_id(journey) == user_id
            for task in (item.as_dict() for item in journey.booking_service.tasks_for_journey(journey.journey_id))
            if task["status"] in {"scheduled", "needs_user_action"}
        ],
    }


def _owned_journey(journey_id: str | None, user_id: int) -> CareJourney | None:
    journey = _journeys.get(journey_id or "")
    if journey is None or _journey_user_id(journey) != user_id:
        return None
    return journey


def _prepare_chat_care_options(journey: CareJourney) -> bool:
    """Advance a complete chat-only intake through read-only comparison.

    service_date and coverage_end_date are no longer required here, matching
    journey.py's onboarding gate — neither is consumed by comparison/pricing;
    see the note on journey.py's refresh_onboarding_requirements.
    """
    required = {"requested_procedure", "procedure_code"}
    if (
        journey.stage.value != "intake"
        or journey.onboarding_missing
        or not required.issubset(journey.workflow.care_state.facts)
    ):
        return False
    journey.prepare_chat_care_options()
    return True


def _care_options_reply(journey: CareJourney, *, voice: bool = False) -> str:
    """Lead with the useful result and the next safe action."""
    count = len(journey.current_plan_options)
    plan_name = journey.catalogs.plan(journey.current_plan_id).name
    if not count:
        if voice:
            return (
                f"I matched the order to your current {plan_name}, but I don't have "
                "published hospital rates for it yet. I've kept the journey ready."
            )
        return (
            f"I resolved the order under your current {plan_name}, but the catalog has no "
            "published hospital rates for it yet. I kept the journey ready so we can add "
            "catalog coverage without changing your insurance."
        )
    best = journey.current_plan_options[0]
    if voice:
        return (
            f"I found {count} current-plan hospital options. {best.hospital} has the "
            f"lowest estimated member-cost scenario at about "
            f"${best.estimated_member_cost:,.0f}. I've opened the comparison."
        )
    return (
        f"Done — I found {count} hospital options under your current {plan_name}. "
        f"The lowest current-plan scenario is {best.hospital} at about "
        f"${best.estimated_member_cost:,.0f} member cost. I opened the comparison; "
        "network verification happens only after you choose a hospital."
    )


def _attach_confirmed_report(analysis: ReportAnalysis, actor: object) -> dict:
    """Make user-confirmed report orders authoritative journey facts."""
    user_id = int(actor)
    conn = db.connect()
    db.init_db(conn)
    try:
        journey = _owned_journey(analysis.journey_id, user_id)
        if journey is None and analysis.journey_id:
            journey = _restore_intake_journey(conn, analysis.journey_id, user_id)
        if journey is None and analysis.journey_id:
            raise HTTPException(status_code=404, detail="that care journey was not found")
        if journey is None:
            journey = _open_journey(user_id, seed_defaults=False)
        if journey.stage.value != "intake":
            raise HTTPException(
                status_code=409,
                detail="confirmed report orders can only be added during journey intake",
            )

        journey.record_consent(
            analysis.consent.action,
            approved=analysis.consent.approved,
            scope=analysis.consent.scope,
            actor=f"user:{user_id}",
        )
        order_ids: list[str] = []
        for confirmed in analysis.confirmed_orders:
            order_ids.append(confirmed.order.order_id)
            for fact in confirmed.facts:
                journey.record_fact(fact)
        journey.refresh_onboarding_requirements()
        options_ready = _prepare_chat_care_options(journey)
        journey.audit.append(
            journey.journey_id,
            "report_orders_confirmed",
            actor="user",
            payload={
                "analysis_id": analysis.analysis_id,
                "source_hash": analysis.source_hash,
                "order_ids": order_ids,
                "options_ready": options_ready,
            },
        )
        return {
            "analysis": analysis.as_dict(),
            "options_ready": options_ready,
            "journey": _journey_payload(journey),
        }
    finally:
        conn.close()


app.include_router(build_report_intake_router(
    _report_intake,
    actor_dependency=require_user,
    confirmed_handler=_attach_confirmed_report,
))


def _intake_reply(
    journey: CareJourney, *, continuing: bool, voice: bool = False
) -> str:
    """Ask for whatever intake facts are still missing, conversationally.

    Which facts are missing, and their exact wording, comes entirely from
    `journey.onboarding_questions` — deterministic app code, unchanged by this
    function. Nemotron only phrases the request; see `agent.phrase_intake_request`.
    A model outage falls back to plain concatenation, so intake never blocks.
    """
    questions = list(dict.fromkeys(journey.onboarding_questions))
    if not questions:
        return "I have the intake details. I’m checking your current-plan hospital options now."
    if voice:
        # Spoken turns ask one thing at a time — a long multi-part spoken
        # question is harder to answer than typed. Procedure specificity is
        # needed to query the catalog, so ask it before timing or coverage.
        priorities = (
            "body area",
            "body area and specific type",
            "which blood test",
            "without contrast or with contrast",
            "date do you expect",
            "coverage end",
        )
        question = next(
            (item for key in priorities for item in questions if key in item.lower()),
            questions[0],
        )
        questions = [question]
    return phrase_intake_request(questions, continuing=continuing)


def _restore_completed_journey(
    conn: sqlite3.Connection, journey_id: str | None, user_id: int
) -> CareJourney | None:
    """Restore only a receipt-backed confirmed appointment for rescheduling."""
    if not journey_id:
        return None
    row = conn.execute(
        """SELECT snapshot_json FROM care_journey
           WHERE journey_id=? AND user_id=? AND stage='complete'""",
        (journey_id, user_id),
    ).fetchone()
    appointment = conn.execute(
        """SELECT slot_id FROM appointment
           WHERE journey_id=? AND user_id=? AND status='confirmed'
             AND source='sandbox_booking'
           ORDER BY id DESC LIMIT 1""",
        (journey_id, user_id),
    ).fetchone()
    if row is None or appointment is None:
        return None
    snapshot = json.loads(row["snapshot_json"])
    path_data = snapshot.get("selected_care_path")
    slot_data = snapshot.get("selected_booking_slot")
    confirmed_receipt = any(
        item.get("action") == ConsentAction.BOOK_APPOINTMENT.value
        and item.get("status") == "sandbox_confirmed"
        for item in snapshot.get("receipts", [])
    )
    if (
        not path_data or not slot_data or not confirmed_receipt
        or slot_data.get("slot_id") != appointment["slot_id"]
    ):
        return None
    journey = CareJourney.open(
        journey_id, user_id=str(user_id), **_journey_dependencies()
    )
    journey.workflow.stage = WorkflowStage.COMPLETE
    journey.current_plan_id = str(path_data["plan_id"])
    journey.selected_care_path = CarePathSelection(**path_data)
    slot = BookingSlot(
        slot_id=slot_data["slot_id"], hospital_id=slot_data["hospital_id"],
        hospital=slot_data["hospital"], procedure_code=slot_data["procedure_code"],
        starts_at=slot_data["starts_at"], duration_minutes=slot_data["duration_minutes"],
        status="booked", source=slot_data.get("source", "seeded sandbox schedule"),
        retry_demo=bool(slot_data.get("retry_demo")),
    )
    journey.selected_booking_slot = journey.booking_service.restore_confirmed_slot(slot)
    journey.booking_slots = [journey.selected_booking_slot]
    for receipt in snapshot.get("receipts", []):
        journey.receipts.append(ActionReceipt(
            receipt["action"], receipt["status"], journey_id, receipt["scope"],
            receipt["idempotency_key"], datetime.fromisoformat(receipt["recorded_at"]),
            bool(receipt.get("sandbox", True)),
        ))
    _journeys[journey_id] = journey
    return journey


def _restore_intake_journey(
    conn: sqlite3.Connection, journey_id: str | None, user_id: int
) -> CareJourney | None:
    """Restore a persisted user-owned intake journey after an API restart."""
    if not journey_id:
        return None
    row = conn.execute(
        """SELECT snapshot_json FROM care_journey
           WHERE journey_id=? AND user_id=? AND stage='intake' AND status='active'""",
        (journey_id, user_id),
    ).fetchone()
    if row is None:
        return None
    snapshot = json.loads(row["snapshot_json"])
    journey = CareJourney.open(
        journey_id, user_id=str(user_id), **_journey_dependencies()
    )
    for item in snapshot.get("facts", []):
        consent = item.get("consent_requirement")
        journey.record_fact(DecisionFact(
            name=str(item["name"]), value=item.get("value"),
            source=str(item["source"]),
            observed_at=datetime.fromisoformat(item["observed_at"]),
            confidence=float(item["confidence"]),
            verification_status=VerificationStatus(item["verification_status"]),
            consent_required=ConsentAction(consent) if consent else None,
        ))
    resolution = snapshot.get("procedure_resolution")
    if resolution:
        journey.procedure_resolution = ProcedureResolution(
            code=resolution.get("code"),
            canonical_name=resolution.get("canonical_name"),
            confidence=str(resolution["confidence"]),
            candidates=tuple(map(str, resolution.get("candidates", []))),
            needs_confirmation=bool(resolution.get("needs_confirmation")),
        )
    journey.onboarding_missing = tuple(map(str, snapshot.get("onboarding_missing", [])))
    journey.onboarding_questions = tuple(map(str, snapshot.get("onboarding_questions", [])))
    _journeys[journey_id] = journey
    return journey


def _restore_recommend_journey(
    conn: sqlite3.Connection, journey_id: str | None, user_id: int
) -> CareJourney | None:
    """Restore a persisted comparison-stage journey after an API restart.

    `_journeys` is process-local, but `_user_care_context` lists journeys from
    the database — so without this, every journey sitting at `compare` or
    `recommend` still renders in the UI and in the model's context while every
    action against it fails. `recommend` is where a journey lands as soon as
    care options are computed, so this is the common case, not an edge one.

    The comparison itself is not read back from the snapshot: the facts are
    restored and the deterministic engine re-runs `prepare_chat_care_options`,
    so the rebuilt options come from the same code path (and the same live
    catalog) that produced them originally rather than from stored output.
    Consents are deliberately not restored as action authority, matching
    `_restore_booking_journey`.
    """
    if not journey_id:
        return None
    row = conn.execute(
        """SELECT snapshot_json FROM care_journey
           WHERE journey_id=? AND user_id=? AND stage IN ('compare','recommend')
             AND status='active'""",
        (journey_id, user_id),
    ).fetchone()
    if row is None:
        return None
    snapshot = json.loads(row["snapshot_json"])
    journey = CareJourney.open(
        journey_id, user_id=str(user_id), **_journey_dependencies()
    )
    for item in snapshot.get("facts", []):
        consent = item.get("consent_requirement")
        journey.record_fact(DecisionFact(
            name=str(item["name"]), value=item.get("value"),
            source=str(item["source"]),
            observed_at=datetime.fromisoformat(item["observed_at"]),
            confidence=float(item["confidence"]),
            verification_status=VerificationStatus(item["verification_status"]),
            consent_required=ConsentAction(consent) if consent else None,
        ))
    resolution = snapshot.get("procedure_resolution")
    if resolution:
        journey.procedure_resolution = ProcedureResolution(
            code=resolution.get("code"),
            canonical_name=resolution.get("canonical_name"),
            confidence=str(resolution["confidence"]),
            candidates=tuple(map(str, resolution.get("candidates", []))),
            needs_confirmation=bool(resolution.get("needs_confirmation")),
        )
    journey.refresh_onboarding_requirements()
    try:
        journey.prepare_chat_care_options()
    except RuntimeError:
        # The snapshot no longer satisfies the intake prerequisites. Hand back
        # the journey at intake rather than None, so the caller can continue
        # the conversation instead of reporting the journey as missing.
        pass
    _journeys[journey_id] = journey
    return journey


def _restore_booking_journey(
    conn: sqlite3.Connection, journey_id: str | None, user_id: int
) -> CareJourney | None:
    """Restore a selected, verified sandbox care path after an API restart.

    Persisted consent records are deliberately not restored as action
    authority. The user must still grant the exact booking approval in the
    current runtime before an adapter can execute.
    """
    if not journey_id:
        return None
    row = conn.execute(
        """SELECT snapshot_json FROM care_journey
           WHERE journey_id=? AND user_id=? AND stage='book' AND status='active'""",
        (journey_id, user_id),
    ).fetchone()
    if row is None:
        return None
    snapshot = json.loads(row["snapshot_json"])
    path_data = snapshot.get("selected_care_path")
    if not path_data or path_data.get("network_status") != "sandbox_verified":
        return None
    journey = CareJourney.open(
        journey_id, user_id=str(user_id), **_journey_dependencies()
    )
    journey.workflow.stage = WorkflowStage.BOOK
    journey.current_plan_id = str(path_data["plan_id"])
    journey.selected_care_path = CarePathSelection(**path_data)
    for item in snapshot.get("facts", []):
        consent = item.get("consent_requirement")
        journey.record_fact(DecisionFact(
            name=str(item["name"]), value=item.get("value"),
            source=str(item["source"]),
            observed_at=datetime.fromisoformat(item["observed_at"]),
            confidence=float(item["confidence"]),
            verification_status=VerificationStatus(item["verification_status"]),
            consent_required=ConsentAction(consent) if consent else None,
        ))
    restored_slots: list[BookingSlot] = []
    for item in snapshot.get("booking_slots", []):
        slot = BookingSlot(
            slot_id=str(item["slot_id"]), hospital_id=int(item["hospital_id"]),
            hospital=str(item["hospital"]), procedure_code=str(item["procedure_code"]),
            starts_at=str(item["starts_at"]), duration_minutes=int(item["duration_minutes"]),
            status="available", source=str(item.get("source", "seeded sandbox schedule")),
            retry_demo=bool(item.get("retry_demo")),
        )
        restored_slots.append(journey.booking_service.restore_available_slot(slot))
    journey.booking_slots = restored_slots
    selected = snapshot.get("selected_booking_slot")
    if selected:
        journey.selected_booking_slot = next(
            (slot for slot in restored_slots if slot.slot_id == selected.get("slot_id")),
            None,
        )
    _journeys[journey_id] = journey
    return journey


def _member_preference(
    conn: sqlite3.Connection, user_id: int, name: str, default: str
) -> tuple[str, str]:
    """A member's own recorded preference if one exists, else the seed default.

    Returns (value, source) so the caller can record accurate provenance —
    "member_memory" for a real recalled fact promoted from a prior journey
    (see _persist_journey_projection), "seeded_user_profile" for the demo
    fallback used the first time a member has no history yet.
    """
    facts = PersistentMemoryStore(conn).view(user_id)["current_facts"]
    for fact in facts:
        if fact["name"] == name:
            return str(fact["value"]), "member_memory"
    return default, "seeded_user_profile"


def _open_journey(
    user_id: int, *, seed_defaults: bool = True, conn: sqlite3.Connection | None = None
) -> CareJourney:
    journey_id = f"journey-{uuid.uuid4().hex[:12]}"
    journey = CareJourney.open(journey_id, user_id=str(user_id), **_journey_dependencies())
    if seed_defaults:
        now = datetime.now(timezone.utc)
        provider, provider_source = (
            _member_preference(conn, user_id, "preferred_provider", "Dr. Lee")
            if conn is not None else ("Dr. Lee", "seeded_user_profile")
        )
        facility, facility_source = (
            _member_preference(conn, user_id, "preferred_facility", "Seattle General")
            if conn is not None else ("Seattle General", "seeded_user_profile")
        )
        journey.record_fact(DecisionFact(
            "requested_procedure", "MRI knee without contrast", "user_request",
            now, 1.0, VerificationStatus.SOURCE_BACKED,
        ))
        journey.record_fact(DecisionFact(
            "preferred_provider", provider, provider_source, now, 1.0,
            VerificationStatus.SOURCE_BACKED,
        ))
        journey.record_fact(DecisionFact(
            "preferred_facility", facility, facility_source, now, 1.0,
            VerificationStatus.SOURCE_BACKED,
        ))
    _journeys[journey_id] = journey
    return journey


@app.post("/api/journeys")
def start_journey(body: JourneyStartIn, user_id: int = Depends(require_user)):
    journey = _open_journey(user_id, seed_defaults=False)
    if not body.empty:
        now = datetime.now(timezone.utc)
        for name, value in (("requested_procedure", body.procedure), ("preferred_provider", body.provider),
                            ("preferred_facility", body.facility)):
            journey.record_fact(DecisionFact(name, value, "user_request", now, 1.0, VerificationStatus.SOURCE_BACKED))
    return _journey_payload(journey)


@app.get("/api/journeys")
def list_user_journeys(
    conn: sqlite3.Connection = Depends(get_conn),
    user_id: int = Depends(require_user),
):
    return _user_care_context(conn, user_id)


@app.get("/api/care-context")
def get_care_context(
    conn: sqlite3.Connection = Depends(get_conn),
    user_id: int = Depends(require_user),
):
    return _user_care_context(conn, user_id)


@app.post("/api/care-agent/messages")
def care_agent_message(
    body: CareAgentMessageIn,
    conn: sqlite3.Connection = Depends(get_conn),
    catalog: sqlite3.Connection | None = Depends(get_catalog_conn_optional),
    user_id: int = Depends(require_user),
):
    context = _user_care_context(conn, user_id)
    utterance_id = body.utterance_id or f"utterance-{uuid.uuid4().hex[:12]}"
    correlation_id = body.correlation_id or f"correlation-{uuid.uuid4().hex[:12]}"
    plan = None
    plan_comparison_result = None
    plan_search_result = None
    voice = body.channel == "voice"
    try:
        plan = (
            _care_journey_agent.pending_reply_plan(
                context,
                body.active_journey_id,
                utterance_id=utterance_id,
                correlation_id=correlation_id,
            )
            if body.reply_to_pending else None
        )
        if plan is None:
            plan = _care_journey_agent.explicit_new_care_plan(
                body.text,
                utterance_id=utterance_id,
                correlation_id=correlation_id,
            )
        if plan is None:
            plan = _care_journey_agent.plan(
                body.text,
                context=context,
                active_journey_id=body.active_journey_id,
                utterance_id=utterance_id,
                correlation_id=correlation_id,
            )
        journey = _owned_journey(plan.target_journey_id, user_id)
        reply: str
        if plan.intent == JourneyIntent.NEW_CARE_REQUEST:
            started_journey = _owned_journey(body.active_journey_id, user_id)
            if (
                started_journey is not None
                and started_journey.stage.value == "intake"
                and not started_journey.workflow.care_state.facts
            ):
                journey = started_journey
            else:
                journey = _open_journey(user_id, seed_defaults=False)
            now = datetime.now(timezone.utc)
            for name, default in (("preferred_provider", "Dr. Lee"),
                                  ("preferred_facility", "Seattle General")):
                value, source = _member_preference(conn, user_id, name, default)
                journey.record_fact(DecisionFact(
                    name, value, source, now, 1.0,
                    VerificationStatus.SOURCE_BACKED,
                ))
            journey.onboard(
                body.text,
                source="care_journey_agent",
                prefer_explicit=plan.source == "explicit_new_care_request",
            )
            if _prepare_chat_care_options(journey):
                reply = _care_options_reply(journey, voice=voice)
            else:
                reply = _intake_reply(journey, continuing=False, voice=voice)
        elif plan.intent == JourneyIntent.CONTINUE_JOURNEY:
            if journey is None:
                journey = _restore_intake_journey(
                    conn, plan.target_journey_id, user_id
                )
            if journey is None:
                journey = _restore_booking_journey(
                    conn, plan.target_journey_id, user_id
                )
            if journey is None:
                journey = _restore_recommend_journey(
                    conn, plan.target_journey_id, user_id
                )
            if journey is None:
                raise RuntimeError("the selected journey is not active on this server")
            if journey.stage.value == "intake":
                journey.onboard(
                    body.text,
                    source="care_journey_agent",
                    prefer_explicit=plan.source == "explicit_pending_reply",
                )
                if _prepare_chat_care_options(journey):
                    reply = _care_options_reply(journey, voice=voice)
                else:
                    reply = _intake_reply(journey, continuing=True, voice=voice)
            elif (
                journey.stage.value == "book"
                and not journey.reschedule_original_slot
                and not journey.booking_slots
            ):
                slots = journey.collect_booking_preferences(body.text)
                reply = f"I found {len(slots)} matching synthetic appointment slots."
            elif journey.stage.value == "book" and journey.booking_slots:
                if journey.selected_booking_slot:
                    reply = (
                        "I restored your booking journey and selected slot. "
                        "Review the exact appointment approval before booking."
                    )
                else:
                    reply = (
                        f"I restored your booking journey with {len(journey.booking_slots)} "
                        "available synthetic slots. Choose one to continue."
                    )
            else:
                reply = f"I resumed {journey.journey_id} at the {journey.stage.value} stage."
        elif plan.intent == JourneyIntent.RESCHEDULE_APPOINTMENT:
            if journey is None:
                journey = _restore_completed_journey(
                    conn, plan.target_journey_id, user_id
                )
            if journey is None:
                raise RuntimeError("a receipt-backed confirmed appointment is required")
            slots = journey.begin_reschedule(body.text)
            reply = (f"I kept the confirmed appointment and found {len(slots)} replacement slots. "
                     "Choose one; the original will only be cancelled after its replacement is confirmed.")
        elif plan.intent == JourneyIntent.LIST_JOURNEYS:
            reply = f"You have {len(context['journeys'])} care journeys. Choose one to make it active."
        elif plan.intent == JourneyIntent.JOURNEY_STATUS:
            if journey:
                reply = f"{journey.journey_id} is currently at the {journey.stage.value} stage."
            else:
                active = context["journeys"][0] if context["journeys"] else None
                reply = (f"Your most recent journey is at the {active['stage']} stage."
                         if active else "You do not have a care journey yet.")
        elif plan.intent == JourneyIntent.COMPARE_PLANS:
            # Hermes does not reliably echo target_journey_id for compare_plans,
            # so fall back to the caller's active journey, then the member's
            # most recent journey — the same fallback JOURNEY_STATUS already
            # uses when the model omits a target.
            if journey is None:
                journey = _owned_journey(body.active_journey_id, user_id)
            if journey is None and context["journeys"]:
                journey = _owned_journey(context["journeys"][0]["journey_id"], user_id)
            procedure_code = None
            if journey is not None:
                code_fact = journey.workflow.care_state.facts.get("procedure_code")
                procedure_code = str(code_fact.value) if code_fact else None
            if catalog is None:
                reply = "Plan comparison needs the hospital price catalog, which isn't available right now."
            elif procedure_code is None:
                reply = (
                    "I can compare your plans once I know what care this is for — "
                    "what procedure or visit should I compare costs for?"
                )
            else:
                plan_count = conn.execute(
                    "SELECT COUNT(*) c FROM plan WHERE user_id IS ?", (user_id,)
                ).fetchone()["c"]
                if plan_count < 2:
                    reply = (
                        "You only have one plan on file right now. Upload a Summary "
                        "of Benefits for another plan in Documents, and I can compare them."
                    )
                    plan_comparison_result = None
                else:
                    plan_comparison_result = _run_plan_comparison(
                        conn, catalog, user_id,
                        [PlanComparisonServiceIn(code=procedure_code)],
                        household_size=1,
                    )
                    reply = _plan_comparison_reply(plan_comparison_result)
        elif plan.intent == JourneyIntent.FIND_PLANS:
            state = _extract_state_from_text(body.text)
            has_real_data = state is not None and conn.execute(
                "SELECT 1 FROM qhp_plan WHERE state = ? LIMIT 1", (state,)
            ).fetchone() is not None
            if has_real_data:
                plan_search_result = _run_plan_search(conn, state, limit=3)
                reply = _plan_search_reply(plan_search_result)
            else:
                plan_search_result = _sample_plan_search_result()
                reply = _plan_search_reply(plan_search_result, sample=True)
                if state is not None:
                    reply = f"I don't have marketplace plan data on file for {state} yet. " + reply
        else:
            reply = "Are you starting new care, continuing a journey, checking status, or rescheduling an appointment?"
    except HermesError as exc:
        _persist_care_agent_trace(
            conn, user_id=user_id, body=body, utterance_id=utterance_id,
            correlation_id=correlation_id, plan=plan, status="failed", error=str(exc),
        )
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        _persist_care_agent_trace(
            conn, user_id=user_id, body=body, utterance_id=utterance_id,
            correlation_id=correlation_id, plan=plan, status="failed", error=str(exc),
        )
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    conn.commit()
    journey_payload = _journey_payload(journey) if journey else None
    conn.commit()
    refreshed_context = _user_care_context(conn, user_id)
    _persist_care_agent_trace(
        conn, user_id=user_id, body=body, utterance_id=plan.utterance_id,
        correlation_id=plan.correlation_id, plan=plan, status="completed",
        journey_id=journey.journey_id if journey else plan.target_journey_id,
    )
    return {
        "reply": reply,
        "plan": plan.as_dict(),
        "journey": journey_payload,
        "context": refreshed_context,
        "plan_comparison": plan_comparison_result,
        "plan_search": plan_search_result,
    }


def _persist_care_agent_trace(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    body: CareAgentMessageIn,
    utterance_id: str,
    correlation_id: str,
    plan,
    status: str,
    error: str | None = None,
    journey_id: str | None = None,
) -> None:
    """Store one durable row per utterance; correlation groups a session."""
    now = datetime.now(timezone.utc).isoformat()
    resolved_journey = journey_id or (plan.target_journey_id if plan else None)
    intent = plan.intent.value if plan else "error"
    plan_json = json.dumps(
        plan.as_dict() if plan else {"validation_error": error or "unknown"},
        separators=(",", ":"),
    )
    conn.execute(
        """INSERT INTO care_agent_trace
           (utterance_id,correlation_id,user_id,journey_id,intent,plan_json,message,
            channel,status,error,created_at,completed_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(utterance_id) DO UPDATE SET
             journey_id=excluded.journey_id, intent=excluded.intent,
             plan_json=excluded.plan_json, message=excluded.message,
             channel=excluded.channel, status=excluded.status,
             error=excluded.error, completed_at=excluded.completed_at""",
        (utterance_id, correlation_id, user_id, resolved_journey, intent,
         plan_json, body.text, body.channel, status, error, now, now),
    )
    conn.commit()


def _voice_care_turn(
    text: str,
    active_journey_id: str | None,
    user_id: int,
    utterance_id: str,
    correlation_id: str,
) -> dict:
    """Run a spoken turn through the exact same authenticated journey path."""
    conn = db.connect()
    db.init_db(conn)
    # care_agent_message now takes `catalog` as a FastAPI Depends parameter;
    # this is a plain function call that bypasses dependency injection
    # entirely, so it must be supplied explicitly or Python would pass the
    # unresolved Depends() object through instead of a real connection. None
    # is a valid value here — care_agent_message degrades honestly (only the
    # compare_plans branch actually needs pricing data).
    catalog = db.connect_catalog(os.environ.get("ABYSS_KNOWLEDGE_DB"))
    try:
        context = _user_care_context(conn, user_id)
        reply_plan = _care_journey_agent.explicit_pending_reply_plan(
            text,
            context,
            active_journey_id,
            utterance_id=utterance_id,
            correlation_id=correlation_id,
        )
        return care_agent_message(
            CareAgentMessageIn(
                text=text,
                active_journey_id=active_journey_id,
                utterance_id=utterance_id,
                correlation_id=correlation_id,
                channel="voice",
                reply_to_pending=reply_plan is not None,
            ),
            conn=conn,
            catalog=catalog,
            user_id=user_id,
        )
    finally:
        if catalog is not None:
            catalog.close()
        conn.close()


def _discord_member_turn(conn: sqlite3.Connection, user_id: int, text: str) -> dict:
    """Route Discord through current deterministic context and Hermes gateway."""
    normalized = text.lower()
    memory = PersistentMemoryStore(conn)
    plan_terms = ("deductible", "out of pocket", "copay", "coinsurance", "my plan")
    action_terms = ("book", "schedule", "reschedule", "appointment", "need", "want")
    if any(term in normalized for term in plan_terms) and not any(
        term in normalized for term in action_terms
    ):
        evidence = {"member_memory": memory.hermes_snapshot(user_id)}
        plan = evidence["member_memory"].get("active_plan")
        if not plan:
            reply = "I don't have a current plan saved for this synthetic member yet."
        else:
            reply = explain(text, evidence)
        memory.append_event(
            user_id,
            agent_role="discord",
            event_type="grounded_plan_question",
            payload={"question_kind": "plan"},
            related_ref="discord-turn",
        )
        return {"reply": reply[:1800], "user_id": user_id, "channel": "discord"}

    context = _user_care_context(conn, user_id)
    active = next(
        (item for item in context["journeys"] if item.get("status") == "active"),
        None,
    )
    active_id = active.get("journey_id") if active else None
    utterance_id = f"discord-{uuid.uuid4().hex[:12]}"
    correlation_id = f"discord-correlation-{uuid.uuid4().hex[:12]}"
    explicit = _care_journey_agent.explicit_pending_reply_plan(
        text,
        context,
        active_id,
        utterance_id=utterance_id,
        correlation_id=correlation_id,
    )
    # Plain function call, bypasses FastAPI dependency injection — see the
    # identical note in _voice_care_turn for why `catalog` must be supplied
    # explicitly here. None is valid; care_agent_message degrades honestly.
    catalog = db.connect_catalog(os.environ.get("ABYSS_KNOWLEDGE_DB"))
    try:
        result = care_agent_message(
            CareAgentMessageIn(
                text=text,
                active_journey_id=active_id,
                utterance_id=utterance_id,
                correlation_id=correlation_id,
                channel="discord",
                reply_to_pending=explicit is not None,
            ),
            conn=conn,
            catalog=catalog,
            user_id=user_id,
        )
    finally:
        if catalog is not None:
            catalog.close()
    return {
        "reply": str(result["reply"])[:1800],
        "user_id": user_id,
        "channel": "discord",
        "journey": result.get("journey"),
        "plan": result.get("plan"),
    }


app.include_router(build_discord_router(
    get_conn=get_conn,
    turn_handler=_discord_member_turn,
))


@app.get("/api/journeys/{journey_id}")
def get_journey(
    journey_id: str,
    conn: sqlite3.Connection = Depends(get_conn),
    user_id: int = Depends(require_user),
):
    journey = _journeys.get(journey_id)
    if journey is None:
        row = conn.execute(
            "SELECT snapshot_json FROM care_journey WHERE journey_id=? AND user_id=?",
            (journey_id, user_id),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="journey not found")
        payload = json.loads(row["snapshot_json"])
        payload["read_only_history"] = True
        return payload
    if not journey.workflow.care_state.session_id.endswith(f":{user_id}"):
        raise HTTPException(status_code=404, detail="journey not found")
    return _journey_payload(journey)


@app.get("/api/admin/journeys")
def admin_journeys(
    conn: sqlite3.Connection = Depends(get_conn),
    user_id: int = Depends(require_user),
):
    """Synthetic operations view for the hackathon admin console."""
    live = {
        journey.journey_id: _journey_payload(journey)
        for journey in _journeys.values() if _journey_user_id(journey) == user_id
    }
    rows = conn.execute(
        """SELECT journey_id,snapshot_json FROM care_journey
           WHERE user_id=? ORDER BY updated_at DESC""",
        (user_id,),
    ).fetchall()
    return {"journeys": [live.get(row["journey_id"]) or json.loads(row["snapshot_json"])
                          for row in rows]}


@app.get("/api/admin/agent-sessions")
def admin_agent_sessions(
    conn: sqlite3.Connection = Depends(get_conn),
    user_id: int = Depends(require_user),
):
    rows = conn.execute(
        """SELECT utterance_id,correlation_id,journey_id,intent,plan_json,message,
                  channel,status,error,created_at,completed_at
           FROM care_agent_trace WHERE user_id=?
           ORDER BY created_at DESC LIMIT 200""",
        (user_id,),
    ).fetchall()
    sessions: dict[str, dict] = {}
    for row in reversed(rows):
        item = dict(row)
        item["plan"] = json.loads(item.pop("plan_json"))
        session = sessions.setdefault(item["correlation_id"], {
            "correlation_id": item["correlation_id"], "channel": item["channel"],
            "status": "completed", "started_at": item["created_at"],
            "updated_at": item["completed_at"] or item["created_at"], "turns": [],
        })
        session["turns"].append(item)
        session["updated_at"] = item["completed_at"] or item["created_at"]
        if item["status"] == "failed":
            session["status"] = "failed"
    ordered = sorted(sessions.values(), key=lambda item: item["updated_at"], reverse=True)
    return {"sessions": ordered}


@app.delete("/api/admin/demo-data")
def clear_demo_data(
    conn: sqlite3.Connection = Depends(get_conn),
    user_id: int = Depends(require_user),
):
    user = conn.execute("SELECT email FROM user WHERE id=?", (user_id,)).fetchone()
    if user is None or not str(user["email"]).endswith("@example.test"):
        raise HTTPException(status_code=403, detail="synthetic demo account required")
    counts = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table} WHERE user_id=?", (user_id,)).fetchone()[0]
        for table in ("care_journey", "appointment", "care_agent_trace")
    }
    for table in ("appointment", "care_agent_trace", "care_journey"):
        conn.execute(f"DELETE FROM {table} WHERE user_id=?", (user_id,))
    conn.commit()
    for journey_id, journey in tuple(_journeys.items()):
        if _journey_user_id(journey) == user_id:
            _journeys.pop(journey_id, None)
    return {"cleared": counts}


@app.post("/api/journeys/{journey_id}/onboard")
def onboard_journey(journey_id: str, body: JourneyOnboardIn, user_id: int = Depends(require_user)):
    journey = _journeys.get(journey_id)
    if journey is None or not journey.workflow.care_state.session_id.endswith(f":{user_id}"):
        raise HTTPException(status_code=404, detail="journey not found")
    try:
        journey.onboard(body.text, source=body.source)
        _prepare_chat_care_options(journey)
    except HermesError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _journey_payload(journey)


@app.post("/api/journeys/{journey_id}/consents")
def consent_journey(journey_id: str, body: JourneyConsentIn, user_id: int = Depends(require_user)):
    journey = _journeys.get(journey_id)
    if journey is None or not journey.workflow.care_state.session_id.endswith(f":{user_id}"):
        raise HTTPException(status_code=404, detail="journey not found")
    journey.record_consent(body.action, approved=body.approved, scope=body.scope, actor=f"user:{user_id}")
    if body.action == ConsentAction.PROCESS_DOCUMENTS and body.approved and journey.stage.value == "intake":
        journey.advance()
    return _journey_payload(journey)


@app.post("/api/journeys/{journey_id}/compare")
def compare_journey(journey_id: str, user_id: int = Depends(require_user)):
    journey = _journeys.get(journey_id)
    if journey is None or not journey.workflow.care_state.session_id.endswith(f":{user_id}"):
        raise HTTPException(status_code=404, detail="journey not found")
    try:
        journey.compare(["continuation", "wa-plan-a", "wa-plan-b"])
        journey.advance()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _journey_payload(journey)


@app.post("/api/journeys/{journey_id}/advance")
def advance_journey(journey_id: str, user_id: int = Depends(require_user)):
    journey = _journeys.get(journey_id)
    if journey is None or not journey.workflow.care_state.session_id.endswith(f":{user_id}"):
        raise HTTPException(status_code=404, detail="journey not found")
    try:
        journey.advance()
    except (RuntimeError, KeyError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _journey_payload(journey)


@app.post("/api/journeys/{journey_id}/selection")
def select_journey_path(
    journey_id: str,
    body: JourneySelectionIn,
    user_id: int = Depends(require_user),
):
    journey = _journeys.get(journey_id)
    if journey is None or not journey.workflow.care_state.session_id.endswith(f":{user_id}"):
        raise HTTPException(status_code=404, detail="journey not found")
    try:
        journey.select_current_care_path(body.hospital_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _journey_payload(journey)


@app.post("/api/journeys/{journey_id}/booking/preferences")
def collect_booking_preferences(
    journey_id: str,
    body: JourneyBookingPreferencesIn,
    user_id: int = Depends(require_user),
):
    journey = _journeys.get(journey_id)
    if journey is None or not journey.workflow.care_state.session_id.endswith(f":{user_id}"):
        raise HTTPException(status_code=404, detail="journey not found")
    try:
        journey.collect_booking_preferences(body.text)
    except HermesError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _journey_payload(journey)


@app.post("/api/journeys/{journey_id}/booking/slots/{slot_id}/select")
def select_booking_slot(
    journey_id: str,
    slot_id: str,
    user_id: int = Depends(require_user),
):
    journey = _journeys.get(journey_id)
    if journey is None or not journey.workflow.care_state.session_id.endswith(f":{user_id}"):
        raise HTTPException(status_code=404, detail="journey not found")
    try:
        journey.select_booking_slot(slot_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _journey_payload(journey)


@app.post("/api/journeys/{journey_id}/reschedule")
def reschedule_journey_appointment(
    journey_id: str,
    body: JourneyRescheduleIn,
    user_id: int = Depends(require_user),
):
    journey = _owned_journey(journey_id, user_id)
    if journey is None:
        raise HTTPException(status_code=404, detail="journey not found")
    try:
        replacement, cancellation = journey.execute_reschedule(
            booking_scope=body.booking_scope,
            cancellation_scope=body.cancellation_scope,
            idempotency_key=body.idempotency_key,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    payload = _journey_payload(journey)
    payload["reschedule_receipts"] = {
        "replacement": replacement.status,
        "cancellation": cancellation.status if cancellation else None,
    }
    return payload


class JourneyReasonIn(BaseModel):
    question: str = Field(default="Why did these care paths pass or fail?", min_length=1, max_length=500)


@app.post("/api/journeys/{journey_id}/matching-reason")
def matching_reason(journey_id: str, body: JourneyReasonIn, user_id: int = Depends(require_user)):
    journey = _journeys.get(journey_id)
    if journey is None or not journey.workflow.care_state.session_id.endswith(f":{user_id}"):
        raise HTTPException(status_code=404, detail="journey not found")
    try:
        reason = journey.explain_matching(body.question)
    except HermesError as exc:
        # The deterministic comparison remains available when Hermes is down.
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"reason": reason, "journey": _journey_payload(journey)}


@app.post("/api/journeys/{journey_id}/actions")
def action_journey(journey_id: str, body: JourneyActionIn, user_id: int = Depends(require_user)):
    journey = _journeys.get(journey_id)
    if journey is None or not journey.workflow.care_state.session_id.endswith(f":{user_id}"):
        raise HTTPException(status_code=404, detail="journey not found")
    try:
        if body.action == ConsentAction.TRANSITION_COVERAGE:
            if body.new_effective_date:
                journey.record_fact(DecisionFact("new_effective_date", body.new_effective_date,
                                                  "sandbox-enrollment-receipt", datetime.now(timezone.utc), 1.0,
                                                  VerificationStatus.VERIFIED))
            if body.first_premium_confirmed:
                journey.record_fact(DecisionFact("first_premium_confirmed", True,
                                                  "sandbox-enrollment-receipt", datetime.now(timezone.utc), 1.0,
                                                  VerificationStatus.VERIFIED))
        receipt = journey.execute(body.action, body.scope, body.idempotency_key)
        if receipt.status != "scheduled_retry":
            journey.advance()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _journey_payload(journey)


@app.post("/api/agent/chat")
def agent_chat(
    body: AgentChatIn,
    conn: sqlite3.Connection = Depends(get_conn),
    user_id: int = Depends(require_user),
):
    """Have GN100-hosted Hermes explain an authoritative VELA result."""
    evidence = dict(body.evidence)
    evidence["member_memory"] = PersistentMemoryStore(conn).hermes_snapshot(user_id)
    try:
        return {"reply": explain(body.question, evidence)}
    except HermesError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


class Credentials(BaseModel):
    email: str
    password: str


@app.post("/api/auth/signup")
def signup(body: Credentials, conn: sqlite3.Connection = Depends(get_conn)):
    email = auth.normalize_email(body.email)
    if "@" not in email or len(email) < 3:
        raise HTTPException(status_code=422, detail="that does not look like an email address")
    if len(body.password) < 8:
        raise HTTPException(status_code=422, detail="use at least 8 characters")
    if conn.execute("SELECT 1 FROM user WHERE email = ?", (email,)).fetchone():
        raise HTTPException(status_code=409, detail="an account with that email already exists")
    user_id = auth.create_user(conn, email, body.password)
    return {"token": auth.issue_session(conn, user_id), "email": email}


@app.post("/api/auth/login")
def login(body: Credentials, conn: sqlite3.Connection = Depends(get_conn)):
    email = auth.normalize_email(body.email)
    row = conn.execute("SELECT * FROM user WHERE email = ?", (email,)).fetchone()
    # One message for both "no such account" and "wrong password", so the
    # response cannot be used to discover which emails have accounts.
    if not row or not auth.verify_password(body.password, row["password_hash"], row["salt"]):
        raise HTTPException(status_code=401, detail="that email and password do not match")
    return {"token": auth.issue_session(conn, int(row["id"])), "email": email}


@app.post("/api/auth/logout")
def logout(
    authorization: str | None = Header(default=None),
    conn: sqlite3.Connection = Depends(get_conn),
):
    token = auth.bearer(authorization)
    if token:
        auth.revoke_session(conn, token)
    return {"ok": True}


@app.get("/api/auth/me")
def me(user_id: int = Depends(require_user), conn: sqlite3.Connection = Depends(get_conn)):
    row = conn.execute("SELECT id, email, created_at FROM user WHERE id = ?", (user_id,)).fetchone()
    if not row:
        raise auth.Unauthorized()
    return dict(row)


# --- models -----------------------------------------------------------------


class PlanIn(BaseModel):
    label: str | None = None
    payer_name: str | None = None
    qhp_plan_id: str | None = None  # links to a real marketplace plan
    deductible: float = 0
    deductible_met: float = 0
    coinsurance_pct: float = Field(0, ge=0, le=1, description="fraction, e.g. 0.2 for 20%")
    copay: float | None = None
    oop_max: float = 0
    oop_met: float = 0
    # Member-reported — no published source carries this figure, an SBC least
    # of all. 0 means "not provided"; the annual comparison must say so.
    monthly_premium: float = 0


def _active_plan_row(conn: sqlite3.Connection, user_id: int | None):
    """The member's active plan row.

    A member can hold several parsed plans in order to compare them, so this
    picks the active one rather than simply the newest.
    """
    return conn.execute(
        """SELECT * FROM plan WHERE user_id IS ? AND is_active = 1
           ORDER BY id DESC LIMIT 1""",
        (user_id,),
    ).fetchone()


def _load_plan(conn: sqlite3.Connection, user_id: int | None = None) -> Plan:
    """The member's stored plan, or an unconfigured one.

    A missing plan is not an error: prices are still worth showing, they just
    can't be personalised yet.
    """
    row = _active_plan_row(conn, user_id)
    if not row:
        return Plan()
    return Plan(
        deductible=row["deductible"],
        deductible_met=row["deductible_met"],
        coinsurance_pct=row["coinsurance_pct"],
        copay=row["copay"],
        oop_max=row["oop_max"],
        oop_met=row["oop_met"],
        payer_name=row["payer_name"],
        label=row["label"],
    )


def _qhp_plan_id(conn: sqlite3.Connection, user_id: int | None = None) -> str | None:
    row = _active_plan_row(conn, user_id)
    return row["qhp_plan_id"] if row else None


# --- routes -----------------------------------------------------------------


@app.get("/api/health")
def health(conn: sqlite3.Connection = Depends(get_conn)):
    """Liveness, and the headline figures.

    `state_database` and `knowledge_catalog` are reported separately and
    truthfully: the state database holds accounts, sessions and journeys and
    is expected to have zero hospitals and zero rates — the catalog is where
    those live. Conflating the two previously made an empty catalog report as
    "ready" because the (irrelevant) state database was reachable.
    """
    catalog_status = _hospital_knowledge.catalog_status() if hasattr(
        _hospital_knowledge, "catalog_status"
    ) else {"status": "unknown", "hospitals": 0, "rates": 0}
    return {
        "ok": True,
        "rates": catalog_status.get("rates", 0),
        "hospitals": catalog_status.get("hospitals", 0),
        "state_database": "ready",
        "knowledge_catalog": {
            **catalog_status,
            "source": _hospital_knowledge.source_name,
            "access": "read_only",
            "network_status_authority": False,
        },
    }


@app.get("/api/hospitals")
def hospitals(catalog: sqlite3.Connection = Depends(get_catalog_conn)):
    # rows_written from the last ingest, rather than COUNT(*) per hospital —
    # grouping 39.6M rows to render a list would take half a minute.
    rows = catalog.execute(
        """SELECT h.id, h.name, h.address, h.last_updated_on, h.mrf_url,
                  COALESCE((SELECT i.rows_written FROM ingest_run i
                            WHERE i.hospital_id = h.id
                            ORDER BY i.id DESC LIMIT 1), 0) AS rates
           FROM hospital h ORDER BY h.name"""
    ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/plan")
def get_plan(
    conn: sqlite3.Connection = Depends(get_conn), user_id: int = Depends(require_user)
):
    row = _active_plan_row(conn, user_id)
    return dict(row) if row else None


@app.get("/api/plan/summary")
def plan_summary(
    category: str | None = None,
    conn: sqlite3.Connection = Depends(get_conn),
    user_id: int = Depends(require_user),
):
    """The member's coverage, in the same shape the voice tool returns.

    Shared so a typed question and a spoken one produce the identical card —
    the alternative is two code paths that drift into two different answers.
    """
    from .ws import run_get_my_plan

    _, payload = run_get_my_plan(conn, category, user_id=user_id)
    return payload


@app.put("/api/plan")
def put_plan(
    body: PlanIn,
    conn: sqlite3.Connection = Depends(get_conn),
    user_id: int = Depends(require_user),
):
    try:
        Plan(
            deductible=body.deductible,
            deductible_met=body.deductible_met,
            coinsurance_pct=body.coinsurance_pct,
            copay=body.copay,
            oop_max=body.oop_max,
            oop_met=body.oop_met,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    conn.execute("DELETE FROM plan WHERE user_id IS ?", (user_id,))
    cur = conn.execute(
        """INSERT INTO plan (user_id, is_active, label, payer_name, qhp_plan_id, deductible,
                             deductible_met, coinsurance_pct, copay, oop_max, oop_met,
                             monthly_premium)
           VALUES (?,1,?,?,?,?,?,?,?,?,?,?) RETURNING id""",
        (user_id, body.label, body.payer_name, body.qhp_plan_id, body.deductible,
         body.deductible_met, body.coinsurance_pct, body.copay, body.oop_max, body.oop_met,
         body.monthly_premium),
    )
    plan_id = cur.fetchone()[0]
    conn.commit()
    return {"id": plan_id, **body.model_dump()}


class PlanUsageIn(BaseModel):
    """What the member has spent so far — the only part of a plan that moves."""

    deductible_met: float | None = None
    oop_met: float | None = None


@app.patch("/api/plan/usage")
def patch_plan_usage(
    body: PlanUsageIn,
    conn: sqlite3.Connection = Depends(get_conn),
    user_id: int = Depends(require_user),
):
    """Update spend-to-date without disturbing the rest of the plan.

    Separate from PUT /api/plan, which replaces everything. These two figures go
    stale the moment a bill is paid, and before this existed the only way to
    correct them was a SQL statement.
    """
    row = _active_plan_row(conn, user_id)
    if not row:
        raise HTTPException(status_code=404, detail="no plan is set up yet")

    deductible_met = row["deductible_met"] if body.deductible_met is None else body.deductible_met
    oop_met = row["oop_met"] if body.oop_met is None else body.oop_met
    if deductible_met < 0 or oop_met < 0:
        raise HTTPException(status_code=422, detail="amounts cannot be negative")

    conn.execute(
        "UPDATE plan SET deductible_met = ?, oop_met = ? WHERE id = ?",
        (deductible_met, oop_met, row["id"]),
    )
    conn.commit()
    return {"deductible_met": deductible_met, "oop_met": oop_met}


@app.delete("/api/plan")
def delete_plan(
    conn: sqlite3.Connection = Depends(get_conn), user_id: int = Depends(require_user)
):
    """Forget the stored plan so onboarding can run again.

    Only the plan row goes. Benefits read from an uploaded document stay under
    their reserved id, so re-linking the same document is not a re-upload.
    """
    conn.execute("DELETE FROM plan WHERE user_id IS ?", (user_id,))
    conn.commit()
    return {"ok": True}


@app.post("/api/sbc/parse")
async def parse_sbc(file: UploadFile = File(...)):
    """Read a Summary of Benefits and Coverage PDF into a plan profile.

    Nothing is saved. The parsed result goes back for the member to check and
    correct before they choose to keep it — the document layout varies enough
    between carriers that a value can land on the wrong row, and an unreviewed
    plan would silently skew every estimate afterwards.
    """
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=415, detail="please upload the SBC as a PDF")

    payload = await file.read()
    if len(payload) > 15 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="that PDF is larger than 15 MB")

    try:
        result = sbc.parse(io.BytesIO(payload))
    except Exception as exc:
        raise HTTPException(
            status_code=422, detail=f"could not read that PDF: {type(exc).__name__}"
        ) from exc

    return {"filename": file.filename, **result.as_dict()}


@app.post("/api/insurance/scan")
async def scan_card(
    file: UploadFile = File(...),
    extracted_text: str | None = Form(default=None),
    user_id: int = Depends(require_user),
):
    """Read a photo of an insurance card.

    Identification only. A card carries the payer, plan name and member number,
    but not the deductible, out-of-pocket maximum or coinsurance — so this
    prefills what it can see and the Summary of Benefits supplies the rest.
    """
    from .ingest import card

    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(status_code=415, detail="please upload an image of the insurance card")
    if extracted_text is not None and len(extracted_text) > 50_000:
        raise HTTPException(status_code=413, detail="recognized card text is too large")
    data = await file.read()
    if len(data) > 12_000_000:
        raise HTTPException(status_code=413, detail="that image is too large")
    result = card.parse(
        data,
        file.content_type or "image/jpeg",
        extracted_text=extracted_text,
    )
    return {"filename": file.filename, **result.as_dict()}


@app.post("/api/care-orders/analyze")
async def analyze_care_order(
    file: UploadFile = File(...),
    journey_id: str | None = Form(default=None),
    extracted_text: str | None = Form(default=None),
    conn: sqlite3.Connection = Depends(get_conn),
    user_id: int = Depends(require_user),
):
    """Retired unsafe intake path; use the exact-consent report workflow."""
    del file, journey_id, extracted_text, conn, user_id
    raise HTTPException(
        status_code=410,
        detail="use /api/report-intake/prepare, /analyze, and /confirm",
    )


class SbcBenefitIn(BaseModel):
    category: str
    kind: str  # copay | coinsurance | no_charge | not_covered
    amount: float = 0
    after_deductible: bool = True


class SbcApplyIn(BaseModel):
    """A parsed SBC after the member has reviewed and corrected it."""

    label: str | None = None
    payer_name: str | None = None
    deductible: float = 0
    deductible_met: float = 0
    oop_max: float = 0
    oop_met: float = 0
    # Not on the SBC itself — the member types this in separately. 0 means
    # "not provided", not "free coverage".
    monthly_premium: float = 0
    benefits: list[SbcBenefitIn] = []
    # Keep the plan already stored and add this one alongside it, so the two can
    # be compared. Off by default: onboarding is replacing, not accumulating.
    keep_existing: bool = False


# Benefits read from an uploaded document live under a reserved plan id, so
# everything downstream — cost_share_for, the estimator, the voice tools — reads
# them exactly as it reads a real marketplace plan.
#
# The id is per-member and per-upload. It used to be the single constant
# "SBC-UPLOADED", which was fine while ABYSS had one user: with accounts, two
# members uploading a document would have silently overwritten each other's
# benefits, and comparing two of your own plans would have been impossible.
SBC_PLAN_PREFIX = "SBC-UPLOADED"


def sbc_plan_id(user_id: int, slot: int = 0) -> str:
    return f"{SBC_PLAN_PREFIX}:{user_id}:{slot}"


@app.post("/api/sbc/apply")
def apply_sbc(
    body: SbcApplyIn,
    conn: sqlite3.Connection = Depends(get_conn),
    user_id: int = Depends(require_user),
):
    """Save a reviewed SBC as the member's plan.

    `keep_existing` adds the document as another plan to compare against rather
    than replacing the active one.
    """
    slot = 0
    if body.keep_existing:
        used = conn.execute(
            """SELECT qhp_plan_id FROM plan
               WHERE user_id IS ? AND qhp_plan_id LIKE ?""",
            (user_id, f"{SBC_PLAN_PREFIX}:{user_id}:%"),
        ).fetchall()
        slot = max((int(str(r[0]).rsplit(":", 1)[1]) for r in used), default=-1) + 1
    SBC_PLAN_ID = sbc_plan_id(user_id, slot)

    conn.execute(
        """INSERT INTO qhp_plan (plan_id, state, issuer_id, issuer_name, marketing_name,
                                 metal_level, plan_type, hsa_eligible, deductible, oop_max)
           VALUES (?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(plan_id) DO UPDATE SET
             issuer_name=excluded.issuer_name, marketing_name=excluded.marketing_name,
             deductible=excluded.deductible, oop_max=excluded.oop_max""",
        (SBC_PLAN_ID, "", "", body.payer_name or "", body.label or "Uploaded plan",
         "", "", 0, body.deductible, body.oop_max),
    )
    conn.execute("DELETE FROM plan_benefit WHERE plan_id = ?", (SBC_PLAN_ID,))
    conn.executemany(
        """INSERT INTO plan_benefit (plan_id, category, kind, amount, after_deductible, covered)
           VALUES (?,?,?,?,?,?)""",
        [
            (SBC_PLAN_ID, b.category, b.kind, b.amount,
             1 if b.after_deductible else 0, 0 if b.kind == "not_covered" else 1)
            for b in body.benefits
        ],
    )

    if body.keep_existing:
        # The new upload becomes the active one; the previous plans stay for
        # comparison.
        conn.execute("UPDATE plan SET is_active = 0 WHERE user_id IS ?", (user_id,))
    else:
        conn.execute("DELETE FROM plan WHERE user_id IS ?", (user_id,))
    cur = conn.execute(
        """INSERT INTO plan (user_id, is_active, label, payer_name, qhp_plan_id, deductible,
                             deductible_met, coinsurance_pct, copay, oop_max, oop_met,
                             monthly_premium)
           VALUES (?,1,?,?,?,?,?,?,?,?,?,?) RETURNING id""",
        (user_id, body.label or "Uploaded plan", body.payer_name, SBC_PLAN_ID, body.deductible,
         body.deductible_met, 0.0, None, body.oop_max, body.oop_met, body.monthly_premium),
    )
    plan_id = cur.fetchone()[0]
    conn.commit()
    return {"id": plan_id, "qhp_plan_id": SBC_PLAN_ID, "benefits_saved": len(body.benefits)}


@app.get("/api/plans/states")
def plan_states(conn: sqlite3.Connection = Depends(get_conn)):
    """States whose plans are linkable, with counts.

    Absent states are not missing data — some run their own marketplaces and are
    not published in the federal Public Use Files. The weekend WA scenario is
    supplied separately as controlled synthetic data.
    """
    rows = conn.execute(
        """SELECT state, COUNT(*) n FROM qhp_plan
           WHERE deductible IS NOT NULL GROUP BY state ORDER BY state"""
    ).fetchall()
    return [{"state": r["state"], "plans": r["n"]} for r in rows]


def _run_plan_search(
    conn: sqlite3.Connection,
    state: str,
    q: str | None = None,
    metal: str | None = None,
    limit: int = 25,
) -> dict:
    """Find a marketplace plan to link, so estimates use its real cost sharing.

    Only federal-platform states are present — the CMS Public Use Files do not
    cover state-run marketplaces (MA, RI, CA, NY, WA and others). Those members,
    and anyone on employer coverage, enter their benefits by hand instead.

    Shared by the REST route (`GET /api/plans/search`) and the conversational
    `find_plans` intent — one implementation, one source of truth.
    """
    # A PUF plan id ends in a variant suffix: -00 off-exchange, -01 standard
    # on-exchange, -02 and up are cost-sharing-reduction variants that only
    # income-qualified members can buy. Offering a CSR variant to everyone would
    # show benefits most people cannot actually get, so only the standard
    # variants are listed, and -00/-01 pairs are collapsed to one row.
    sql = """SELECT MAX(plan_id) AS plan_id, state, issuer_name, marketing_name,
                    metal_level, plan_type, hsa_eligible, deductible, oop_max
             FROM qhp_plan
             WHERE state = ? AND deductible IS NOT NULL AND oop_max IS NOT NULL
               AND substr(plan_id, -2) IN ('00', '01')"""
    params: list = [state.upper()]
    if metal:
        sql += " AND metal_level = ?"
        params.append(metal)
    if q:
        sql += " AND (marketing_name LIKE ? OR issuer_name LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    # Group on the standard component id — the plan id without its variant.
    sql += """ GROUP BY substr(plan_id, 1, length(plan_id) - 3)
               ORDER BY deductible, marketing_name LIMIT ?"""
    params.append(limit)

    rows = [dict(r) for r in conn.execute(sql, params)]
    return {"state": state.upper(), "count": len(rows), "plans": rows}


@app.get("/api/plans/search")
def search_plans(
    state: str,
    q: str | None = None,
    metal: str | None = None,
    limit: int = 25,
    conn: sqlite3.Connection = Depends(get_conn),
):
    return _run_plan_search(conn, state, q, metal, limit)


@app.get("/api/plans/{plan_id}/benefits")
def plan_benefits(plan_id: str, conn: sqlite3.Connection = Depends(get_conn)):
    """Every service category's cost-sharing rule for one plan."""
    plan = conn.execute("SELECT * FROM qhp_plan WHERE plan_id = ?", (plan_id,)).fetchone()
    if not plan:
        raise HTTPException(status_code=404, detail="unknown plan")
    benefits = conn.execute(
        """SELECT category, kind, amount, after_deductible, covered
           FROM plan_benefit WHERE plan_id = ? AND kind != 'unknown' ORDER BY category""",
        (plan_id,),
    ).fetchall()
    return {"plan": dict(plan), "benefits": [dict(b) for b in benefits]}


@app.get("/api/price")
def price(
    q: str,
    code: str | None = None,
    conn: sqlite3.Connection = Depends(get_conn),
    catalog: sqlite3.Connection = Depends(get_catalog_conn),
    user_id: int | None = Depends(optional_user),
):
    """Answer a price question, personalised to the stored plan.

    Signing in is not required. Published hospital prices are public, and a
    member who has not finished onboarding should still see them — they simply
    are not personalised.

    Pass `code` to price a specific billing code directly — that is how the
    client confirms one of the candidates offered when a query is ambiguous.

    Hospital and rate data always comes from `catalog` (the hospital knowledge
    catalog); `conn` (the member's own state database) is used only for their
    plan and lookup history.
    """
    if code:
        row = catalog.execute(
            "SELECT code, code_type FROM rate WHERE code = ? LIMIT 1", (code,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"unknown code {code}")
        resolution = retrieval.Resolution(row["code"], row["code_type"], "confirmed", True)
    else:
        resolution = retrieval.resolve_code(catalog, q)

    if not resolution.code:
        return {
            "query": q,
            "resolved": None,
            "resolution": resolution.how,
            "hospitals": [],
            "message": "Could not match that to a billing code in the ingested files.",
        }

    if not resolution.confident:
        # Never price a guess. A wrong procedure priced confidently is worse
        # than asking which one the user meant.
        return {
            "query": q,
            "resolved": None,
            "resolution": resolution.how,
            "needs_confirmation": True,
            "candidates": resolution.candidates,
            "hospitals": [],
            "message": (
                "That didn't match a procedure ABYSS recognises. These billing codes "
                "mention those words — which one did you mean?"
            ),
        }

    code, code_type, how = resolution.code, resolution.code_type, resolution.how
    prices = retrieval.prices_for_code(catalog, code, code_type)
    formula_only = retrieval.formula_priced_count(catalog, code)

    if not prices:
        # The code resolved, but no hospital in the catalog published a usable
        # rate for it. Only claim formula pricing when that is actually what
        # happened — `formula_only` is the count of formula-priced (not
        # dollar-priced) rows for this code; if it is zero, no hospital
        # published anything for this code at all, formula or otherwise, and
        # saying so is the honest answer rather than a guessed cause.
        if formula_only > 0:
            message = (
                "These hospitals publish this service as a contractual formula rather "
                "than a dollar amount, so no estimate can be derived from the file."
            )
        else:
            message = (
                "No hospital in the catalog published a rate for this code."
            )
        return {
            "query": q,
            "resolved": {"code": code, "code_type": code_type},
            "resolution": how,
            "hospitals": [],
            "formula_priced_rows": formula_only,
            "message": message,
        }

    plan = _load_plan(conn, user_id)
    plan_configured = plan.deductible or plan.oop_max or plan.coinsurance_pct or plan.copay
    cost_share, share_status = retrieval.cost_share_status(
        conn, catalog, _qhp_plan_id(conn, user_id), code
    )

    results = []
    for p in prices:
        est = estimate(p.typical, plan, low_allowed=p.low, high_allowed=p.high,
                       cost_share=cost_share, cost_share_status=share_status)
        results.append({**p.as_dict(), "estimate": est.as_dict()})

    # The cheapest option's range, not the spread across every hospital. The
    # estimate card and the spoken answer both lead with the cheapest, and a
    # home screen showing a different, much wider range for the same question
    # reads as a contradiction.
    db.record_lookup(
        conn, q, code, prices[0].description,
        results[0]["estimate"]["low"], results[0]["estimate"]["high"],
        user_id=user_id,
    )

    return {
        "query": q,
        "resolved": {
            "code": code,
            "code_type": code_type,
            "description": prices[0].description,
        },
        "resolution": how,
        "plan_configured": bool(plan_configured),
        "cost_sharing": (
            {"category": cost_share.category, "kind": cost_share.kind,
             "amount": cost_share.amount, "after_deductible": cost_share.after_deductible}
            if cost_share else None
        ),
        "hospitals": results,
        "cash_prices": retrieval.cash_prices_for_code(catalog, code),
        "formula_priced_rows": formula_only,
    }


@app.get("/api/history")
def history(
    limit: int = 5,
    conn: sqlite3.Connection = Depends(get_conn),
    user_id: int = Depends(require_user),
):
    """Recent questions, for the home screen. Includes ones asked out loud."""
    return {"recent": db.recent_lookups(conn, limit, user_id=user_id)}


@app.get("/api/plans/mine")
def my_plans(
    conn: sqlite3.Connection = Depends(get_conn), user_id: int = Depends(require_user)
):
    """Every plan this member holds, so two of them can be compared."""
    rows = conn.execute(
        """SELECT id, label, payer_name, qhp_plan_id, deductible, deductible_met,
                  coinsurance_pct, copay, oop_max, oop_met, is_active
           FROM plan WHERE user_id IS ? ORDER BY is_active DESC, id DESC""",
        (user_id,),
    ).fetchall()
    return {"plans": [dict(r) for r in rows]}


@app.post("/api/plans/{plan_id}/activate")
def activate_plan(
    plan_id: int,
    conn: sqlite3.Connection = Depends(get_conn),
    user_id: int = Depends(require_user),
):
    if not conn.execute(
        "SELECT 1 FROM plan WHERE id = ? AND user_id IS ?", (plan_id, user_id)
    ).fetchone():
        raise HTTPException(status_code=404, detail="no such plan")
    conn.execute("UPDATE plan SET is_active = 0 WHERE user_id IS ?", (user_id,))
    conn.execute("UPDATE plan SET is_active = 1 WHERE id = ?", (plan_id,))
    conn.commit()
    return {"ok": True, "active": plan_id}


@app.delete("/api/plans/{plan_id}")
def delete_one_plan(
    plan_id: int,
    conn: sqlite3.Connection = Depends(get_conn),
    user_id: int = Depends(require_user),
):
    row = conn.execute(
        "SELECT qhp_plan_id, is_active FROM plan WHERE id = ? AND user_id IS ?",
        (plan_id, user_id),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="no such plan")
    conn.execute("DELETE FROM plan WHERE id = ?", (plan_id,))
    # The benefits belong to this upload alone, so they go with it. A plan linked
    # to a real marketplace id keeps its catalogue rows.
    if str(row["qhp_plan_id"] or "").startswith(SBC_PLAN_PREFIX):
        conn.execute("DELETE FROM plan_benefit WHERE plan_id = ?", (row["qhp_plan_id"],))
        conn.execute("DELETE FROM qhp_plan WHERE plan_id = ?", (row["qhp_plan_id"],))
    if row["is_active"]:
        # Never leave the member with plans but no active one.
        nxt = conn.execute(
            "SELECT id FROM plan WHERE user_id IS ? ORDER BY id DESC LIMIT 1", (user_id,)
        ).fetchone()
        if nxt:
            conn.execute("UPDATE plan SET is_active = 1 WHERE id = ?", (nxt["id"],))
    conn.commit()
    return {"ok": True}


@app.get("/api/plans/compare")
def compare_plans(
    q: str,
    conn: sqlite3.Connection = Depends(get_conn),
    catalog: sqlite3.Connection = Depends(get_catalog_conn),
    user_id: int = Depends(require_user),
):
    """What one procedure costs under each plan the member holds.

    The comparison is anchored to a single hospital — the cheapest that publishes
    the code — so the only thing varying between the rows is the plan. Comparing
    plan A at one hospital against plan B at another would attribute a difference
    in hospital pricing to the insurance.

    Premiums are not modelled: ABYSS has no premium data, and a comparison that
    silently omitted it while looking complete would be worse than one that says
    so.
    """
    resolution = retrieval.resolve_code(catalog, q)
    if not resolution.code or not resolution.confident:
        return {"query": q, "resolved": None, "plans": [],
                "message": "Name the procedure a little more precisely to compare plans."}

    prices = retrieval.prices_for_code(catalog, resolution.code)
    if not prices:
        return {"query": q, "resolved": {"code": resolution.code}, "plans": [],
                "message": "No hospital publishes a dollar price for this yet."}

    cheapest = prices[0]
    rows = conn.execute(
        "SELECT * FROM plan WHERE user_id IS ? ORDER BY is_active DESC, id DESC", (user_id,)
    ).fetchall()

    out = []
    for row in rows:
        plan = Plan(
            deductible=row["deductible"], deductible_met=row["deductible_met"],
            coinsurance_pct=row["coinsurance_pct"], copay=row["copay"],
            oop_max=row["oop_max"], oop_met=row["oop_met"],
            payer_name=row["payer_name"], label=row["label"],
        )
        share, share_status = retrieval.cost_share_status(
            conn, catalog, row["qhp_plan_id"], resolution.code
        )
        est = estimate(
            cheapest.typical, plan, low_allowed=cheapest.low, high_allowed=cheapest.high,
            cost_share=share, cost_share_status=share_status,
        )
        out.append({
            "plan_id": row["id"], "label": row["label"], "payer_name": row["payer_name"],
            "is_active": row["is_active"], "estimate": est.as_dict(),
        })

    out.sort(key=lambda p: p["estimate"]["expected"])
    return {
        "query": q,
        "resolved": {"code": resolution.code, "description": cheapest.description},
        "hospital": cheapest.hospital,
        "allowed": cheapest.typical,
        "plans": out,
    }


@dataclass
class _ResolvedService:
    """A stated service anchored to one code and its cheapest published hospital.

    Every plan is priced against the same hospital-service pair — same
    anchoring principle as `/api/plans/compare` — so the plan is the only
    thing that varies between rows in the comparison.
    """

    code: str
    description: str | None
    hospital: str | None
    allowed_amount: float | None


def _resolve_service(catalog: sqlite3.Connection, code: str, code_type: str | None = None) -> _ResolvedService:
    prices = retrieval.prices_for_code(catalog, code, code_type)
    if not prices:
        return _ResolvedService(code=code, description=None, hospital=None, allowed_amount=None)
    cheapest = prices[0]
    return _ResolvedService(
        code=code, description=cheapest.description, hospital=cheapest.hospital,
        allowed_amount=cheapest.typical,
    )


class PlanComparisonServiceIn(BaseModel):
    """A service the member expects to use this year, by plain language or code."""

    query: str | None = None
    code: str | None = None


class PlanComparisonIn(BaseModel):
    services: list[PlanComparisonServiceIn] = []
    household_size: int = Field(1, ge=1)
    # Defaults to the member's first-uploaded plan — the natural reading of
    # "what they have now" when nothing else says otherwise.
    current_plan_id: int | None = None


US_STATE_ABBREVIATIONS = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE",
    "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
    "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR",
    "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
    "district of columbia": "DC",
}


def _extract_state_from_text(text: str) -> str | None:
    """A deterministic state lookup, not a model guess.

    Matches a full state name, or a standalone two-letter abbreviation the
    member typed in capitals, in their own words — so find_plans never has to
    ask Hermes to invent a location the member did not actually say. The
    abbreviation check stays case-sensitive against the original text on
    purpose: matching case-insensitively would treat ordinary words like "me"
    or "in" as Maine/Indiana in ordinary sentences such as "show me plans".
    """
    lowered = f" {text.lower()} "
    for name, abbrev in US_STATE_ABBREVIATIONS.items():
        if f" {name} " in lowered:
            return abbrev
    for abbrev in set(US_STATE_ABBREVIATIONS.values()):
        if re.search(rf"\b{abbrev}\b", text):
            return abbrev
    return None


def _plan_search_reply(result: dict, *, sample: bool = False) -> str:
    """State the real plans found in one spoken-friendly sentence.

    Never states a plan that isn't already in `result` — this only narrates
    _run_plan_search's own output, or the seeded sample catalog's own records.
    """
    plans = result.get("plans") or []
    if not plans:
        return (
            f"I don't have marketplace plan data on file for {result.get('state', 'that state')} yet."
        )
    lead = "Here are a few sample plans" if sample else f"Here are a few {result['state']} marketplace plans"
    parts = []
    for p in plans[:3]:
        parts.append(
            f"{p['marketing_name']} from {p['issuer_name']} ({p['metal_level'].title() if p.get('metal_level') else 'unrated'}) "
            f"— ${p['deductible']:,.0f} deductible, ${p['oop_max']:,.0f} out-of-pocket max"
        )
    return lead + ": " + "; ".join(parts) + "."


def _sample_plan_search_result() -> dict:
    """The seeded Washington demo catalog, presented as sample plans.

    WA runs its own exchange, so it is structurally absent from the free CMS
    Public Use Files _run_plan_search reads — this is the same seeded synthetic
    catalog journey.py already uses for plan-feasibility evaluation, reused
    here rather than inventing new numbers. Excludes "continuation", which
    represents the member's current plan, not a plan to discover.
    """
    catalog = SeededCatalog()
    plans = [
        {
            "plan_id": record.plan_id,
            "state": "WA",
            "issuer_name": "Sample catalog",
            "marketing_name": record.name,
            "metal_level": None,
            "plan_type": None,
            "hsa_eligible": None,
            "deductible": record.deductible_exposure,
            "oop_max": record.expected_care_oop,
        }
        for record in catalog.plans.values()
        if not record.is_current
    ]
    return {"state": "WA", "count": len(plans), "plans": plans}


def _plan_comparison_reply(result: dict) -> str:
    """State the real comparison numbers in one spoken-friendly sentence.

    Mirrors _care_options_reply's style: lead with the useful result. Never
    states a number that isn't already in `result` — this only narrates
    _run_plan_comparison's own output.
    """
    plans = result.get("plans") or []
    if not plans:
        return result.get("message") or "I could not compare your plans right now."
    incomplete = result.get("incomplete_plans") or []
    if incomplete:
        # Refusing to rank is the honest answer: the totals for these plans are
        # missing their real cost sharing, so any ranking would be arbitrary.
        names = " and ".join(incomplete) if len(incomplete) < 3 else ", ".join(incomplete)
        return (
            f"I can't compare these plans yet. {names} "
            f"{'has' if len(incomplete) == 1 else 'have'} no cost-sharing detail on file, "
            "so I can only see the deductible — the real cost would be higher and I'd be "
            "guessing. Upload the Summary of Benefits for it in Documents and I'll run this again."
        )
    recommendation = result.get("recommendation")
    if recommendation:
        savings = recommendation["estimated_annual_savings"]["predicted"]
        return (
            f"Comparing your {len(plans)} plans — {recommendation['recommended_label']} "
            f"has the lower predicted annual cost, about ${savings:,.2f} less than "
            f"{recommendation['current_label']} this year."
        )
    cheapest = plans[0]
    return (
        f"Comparing your {len(plans)} plans, {cheapest['label']} has the lowest "
        f"predicted annual cost at about ${cheapest['scenarios']['predicted']['annual_total']:,.2f}."
    )


def _run_plan_comparison(
    conn: sqlite3.Connection,
    catalog: sqlite3.Connection,
    user_id: int,
    services: list["PlanComparisonServiceIn"],
    household_size: int,
    current_plan_id: int | None = None,
) -> dict:
    """EMME's core deliverable: predicted / possible / worst-case annual cost
    across every plan the member has uploaded an SBC for.

    Predicted uses only the services the member actually named. Possible adds
    a real, catalog-priced injury bundle (a household of two or more also gets
    a concussion bundle) — EMME's "predicted + a broken arm". Worst case is the
    plan's out-of-pocket maximum, not an itemised guess. A plan whose OOP max
    was never provided is reported incomplete for that scenario rather than
    silently priced as unbounded or free.

    Shared by the REST route (`POST /api/plan-comparison`) and the
    conversational `compare_plans` intent — one implementation, so a typed
    request and a spoken one can never drift into two different answers.
    """
    plan_rows = conn.execute(
        "SELECT * FROM plan WHERE user_id IS ? ORDER BY id", (user_id,)
    ).fetchall()
    if not plan_rows:
        return {
            "plans": [],
            "recommendation": None,
            "message": "Upload a Summary of Benefits for at least one plan to compare costs.",
        }

    resolved_services: list[_ResolvedService] = []
    unresolved: list[dict] = []
    for item in services:
        if item.code:
            row = catalog.execute(
                "SELECT code, code_type FROM rate WHERE code = ? LIMIT 1", (item.code,)
            ).fetchone()
            resolution = (
                retrieval.Resolution(row["code"], row["code_type"], "confirmed", True)
                if row else retrieval.Resolution(None, None, "unknown-code", False)
            )
        elif item.query:
            resolution = retrieval.resolve_code(catalog, item.query)
        else:
            continue
        if not resolution.code or not resolution.confident:
            unresolved.append({
                "query": item.query, "code": item.code,
                "candidates": resolution.candidates,
            })
            continue
        resolved_services.append(_resolve_service(catalog, resolution.code, resolution.code_type))

    possible_extra: list[_ResolvedService] = []
    for event_name, codes in EVENT_BUNDLES.items():
        if event_name == "concussion" and household_size < 2:
            continue
        possible_extra.extend(_resolve_service(catalog, code, code_type) for code, code_type in codes)

    current_plan_id = current_plan_id or plan_rows[0]["id"]

    def _priced(service: _ResolvedService, qhp_plan_id: str | None) -> PricedService:
        if service.allowed_amount is None:
            return PricedService(
                code=service.code, description=service.description, hospital=service.hospital,
                allowed_amount=None, cost_share=None, cost_share_status="unpriced",
            )
        cost_share, status = retrieval.cost_share_status(conn, catalog, qhp_plan_id, service.code)
        return PricedService(
            code=service.code, description=service.description, hospital=service.hospital,
            allowed_amount=service.allowed_amount, cost_share=cost_share, cost_share_status=status,
        )

    plan_results = []
    for row in plan_rows:
        plan = Plan(
            deductible=row["deductible"], deductible_met=row["deductible_met"],
            coinsurance_pct=row["coinsurance_pct"], copay=row["copay"],
            oop_max=row["oop_max"], oop_met=row["oop_met"],
            payer_name=row["payer_name"], label=row["label"],
        )
        annual_premium = row["monthly_premium"] * 12

        predicted_priced = [_priced(s, row["qhp_plan_id"]) for s in resolved_services]
        possible_priced = predicted_priced + [_priced(s, row["qhp_plan_id"]) for s in possible_extra]

        predicted = simulate_annual_scenario("predicted", plan, annual_premium, predicted_priced)
        possible = simulate_annual_scenario("possible", plan, annual_premium, possible_priced)
        worst_case = worst_case_scenario(plan, annual_premium)

        plan_results.append({
            "plan_id": row["id"],
            "label": row["label"] or f"Plan {row['id']}",
            "payer_name": row["payer_name"],
            "is_current": row["id"] == current_plan_id,
            "qhp_plan_id": row["qhp_plan_id"],
            "monthly_premium": row["monthly_premium"],
            "premium_provided": row["monthly_premium"] > 0,
            "key_details": {
                "deductible": row["deductible"],
                "deductible_remaining": plan.remaining_deductible,
                "oop_max": row["oop_max"] or None,
                "oop_remaining": plan.remaining_oop if row["oop_max"] > 0 else None,
                "coinsurance_pct": row["coinsurance_pct"] or None,
                "copay": row["copay"],
                "cost_sharing_source": "per_service" if row["qhp_plan_id"] else "blended",
            },
            "scenarios": {
                "predicted": predicted.as_dict(),
                "possible": possible.as_dict(),
                "worst_case": worst_case.as_dict(),
            },
        })

    plan_results.sort(key=lambda p: p["scenarios"]["predicted"]["annual_total"])

    # A scenario is `complete=False` when a service's cost share could not be
    # classified: `simulate_annual_scenario` then charges only the deductible,
    # which understates the member's real exposure. Ranking on that number and
    # announcing a dollar saving would state a confident total the engine
    # itself knows is wrong, so name the plans instead and refuse to rank.
    incomplete_labels = [
        plan["label"] for plan in plan_results
        if not plan["scenarios"]["predicted"]["complete"]
    ]

    current = next((p for p in plan_results if p["is_current"]), None)
    recommendation = None
    if (
        not incomplete_labels
        and current is not None
        and plan_results[0]["plan_id"] != current["plan_id"]
    ):
        best = plan_results[0]
        recommendation = {
            "recommended_plan_id": best["plan_id"],
            "recommended_label": best["label"],
            "current_plan_id": current["plan_id"],
            "current_label": current["label"],
            "estimated_annual_savings": {
                scenario: round(
                    current["scenarios"][scenario]["annual_total"]
                    - best["scenarios"][scenario]["annual_total"], 2,
                )
                for scenario in ("predicted", "possible", "worst_case")
            },
            "reason": (
                f"{best['label']} has the lower predicted annual cost: "
                f"${best['scenarios']['predicted']['annual_total']:,.2f} vs "
                f"${current['scenarios']['predicted']['annual_total']:,.2f} on {current['label']}."
            ),
        }

    return {
        "household_size": household_size,
        "plans": plan_results,
        "unresolved_services": unresolved,
        "incomplete_plans": incomplete_labels,
        "recommendation": recommendation,
    }


@app.post("/api/plan-comparison")
def plan_comparison(
    body: PlanComparisonIn,
    conn: sqlite3.Connection = Depends(get_conn),
    catalog: sqlite3.Connection = Depends(get_catalog_conn),
    user_id: int = Depends(require_user),
):
    return _run_plan_comparison(
        conn, catalog, user_id, body.services, body.household_size, body.current_plan_id,
    )


class BillCheckIn(BaseModel):
    """A line from a bill or an explanation of benefits."""

    query: str                      # procedure description or billing code
    amount: float
    # Which number off the paperwork this is. Getting this wrong is the whole
    # risk of the feature, so it is asked rather than guessed.
    amount_kind: str = "allowed"    # allowed | charged | paid
    hospital_id: int | None = None


@app.post("/api/bill/check")
def check_bill(
    body: BillCheckIn,
    conn: sqlite3.Connection = Depends(get_conn),
    catalog: sqlite3.Connection = Depends(get_catalog_conn),
    user_id: int = Depends(require_user),
):
    """Compare one line of a bill against what the hospital published.

    The comparison depends entirely on *which* figure the member is holding, and
    the three on a bill are not interchangeable:

    `charged`  the gross chargemaster price. Almost nobody pays it, and it runs
               several times the negotiated rate — so it is compared against the
               published gross charge, never against negotiated rates.
    `allowed`  what the insurer agreed the service costs. This is the number
               that should match a published negotiated rate, and the only one
               where "you were overcharged" is a meaningful claim.
    `paid`     the member's own share after the plan applied. That is a function
               of their benefits rather than the hospital's price, so it is
               checked against their estimate instead.

    Blending these would produce confident nonsense: a gross charge is routinely
    4x the negotiated rate, so treating one as the other flags every ordinary
    bill as an overcharge.
    """
    kind = body.amount_kind.strip().lower()
    if kind not in ("allowed", "charged", "paid"):
        raise HTTPException(status_code=422, detail="amount_kind must be allowed, charged or paid")
    if body.amount <= 0:
        raise HTTPException(status_code=422, detail="enter the amount from your bill")

    resolution = retrieval.resolve_code(catalog, body.query)
    if not resolution.code or not resolution.confident:
        return {
            "resolved": None,
            "candidates": [c.__dict__ if hasattr(c, "__dict__") else c
                           for c in (resolution.candidates or [])][:5],
            "message": (
                "Name the service more precisely, or enter the billing code printed on the "
                "bill — it is usually a five-digit number in a column marked CPT or HCPCS."
            ),
        }

    ref = retrieval.billed_reference(catalog, resolution.code, body.hospital_id)
    if not ref:
        return {
            "resolved": {"code": resolution.code},
            "message": "No hospital publishes a dollar price for this code, so there is nothing "
                       "to compare against.",
        }

    hospital = None
    if body.hospital_id is not None:
        row = catalog.execute(
            "SELECT name FROM hospital WHERE id = ?", (body.hospital_id,)
        ).fetchone()
        hospital = row["name"] if row else None

    if kind == "charged":
        low, high = ref["gross_low"], ref["gross_high"]
        basis = "the hospital's published gross charge"
        missing = "This hospital publishes no gross charge for this code."
    elif kind == "paid":
        plan = _load_plan(conn, user_id)
        share, share_status = retrieval.cost_share_status(
            conn, catalog, _qhp_plan_id(conn, user_id), resolution.code
        )
        est = estimate(
            ref["median"], plan, low_allowed=ref["low"], high_allowed=ref["high"],
            cost_share=share, cost_share_status=share_status,
        )
        return {
            "resolved": {"code": resolution.code, "description": ref["description"]},
            "amount_kind": kind,
            "amount": body.amount,
            "hospital": hospital,
            "verdict": _verdict(body.amount, est.low, est.high),
            "reference": {"low": est.low, "high": est.high, "basis": "your plan's share"},
            "estimate": est.as_dict(),
            "note": "What you owe depends on your benefits, not only the hospital's price.",
        }
    else:
        low, high = ref["low"], ref["high"]
        basis = "negotiated rates published for this code"
        missing = "This hospital publishes no negotiated rate for this code."

    if low is None or high is None:
        return {
            "resolved": {"code": resolution.code, "description": ref["description"]},
            "message": missing,
        }

    return {
        "resolved": {"code": resolution.code, "description": ref["description"]},
        "amount_kind": kind,
        "amount": body.amount,
        "hospital": hospital,
        "verdict": _verdict(body.amount, low, high, ref["rates"] if kind == "allowed" else None),
        "reference": {
            "low": low,
            "high": high,
            # Only for negotiated rates. The median is computed over the
            # negotiated distribution, so returning it beside a gross-charge
            # low/high would put the two kinds of money in one object — the
            # exact confusion this endpoint exists to prevent.
            "median": ref["median"] if kind == "allowed" else None,
            "count": ref["count"] if kind == "allowed" else None,
            "basis": basis,
        },
        # Comparing against every hospital at once is close to meaningless: the
        # spread is wide enough that any plausible bill falls inside it. Say so
        # rather than returning a reassuring "within" that carries no
        # information — the hospital's name is printed on the bill anyway.
        "scope_warning": (
            "This compares against all hospitals at once, where published rates vary so widely "
            "that almost any amount looks normal. Pick the hospital from your bill for an answer "
            "that means something."
            if hospital is None else None
        ),
        "cash_price": (
            {"low": ref["cash_low"], "high": ref["cash_high"]} if ref["cash_low"] else None
        ),
    }


def _verdict(
    amount: float, low: float, high: float, rates: list[float] | None = None
) -> dict:
    """Where a figure sits against the published range.

    Deliberately not a yes/no. Negotiated rates differ legitimately by payer, so
    a number above the range is a reason to ask a question, not proof of an
    error — and saying otherwise would send people into a billing dispute they
    are going to lose.

    The percentile carries the answer when the range alone cannot. Across all 57
    hospitals a knee MRI spans $34 to $10,491, so every conceivable bill lands
    "within" and the verdict says nothing; against that same spread, "higher
    than 94% of published rates" still does.
    """
    verdict: dict
    if amount > high:
        verdict = {
            "status": "above",
            "over_by": round(amount - high, 2),
            "headline": "Higher than anything published for this code",
            "detail": "Worth asking the hospital which rate was applied and why.",
        }
    elif amount < low:
        verdict = {
            "status": "below",
            "headline": "Lower than the published range",
            "detail": "Nothing to query — you were charged less than the published rates.",
        }
    else:
        verdict = {
            "status": "within",
            "headline": "Within the published range",
            "detail": "This is consistent with what the hospital publishes for this code.",
        }

    if rates:
        below = sum(1 for r in rates if r < amount)
        verdict["percentile"] = round(100 * below / len(rates))
    return verdict


class AppointmentIn(BaseModel):
    """Something the member arranged themselves, by phone.

    ABYSS has no scheduling integration and does not pretend to have one: this
    records what was booked so the estimate survives the phone call.
    """

    hospital_id: int | None = None
    code: str | None = None
    description: str | None = None
    booked_for: str | None = None  # ISO date
    estimated_cost: float | None = None
    note: str | None = None


@app.get("/api/appointments")
def list_appointments(
    conn: sqlite3.Connection = Depends(get_conn),
    catalog: sqlite3.Connection = Depends(get_catalog_conn),
    user_id: int = Depends(require_user),
):
    """Soonest first, with anything undated last.

    `appointment` lives in the member's state database; `hospital` lives in the
    knowledge catalog — two different SQLite files, so the join happens in
    Python rather than SQL.
    """
    rows = conn.execute(
        """SELECT * FROM appointment WHERE user_id IS ?
           ORDER BY booked_for IS NULL, booked_for, id""",
        (user_id,),
    ).fetchall()
    hospital_ids = {r["hospital_id"] for r in rows if r["hospital_id"] is not None}
    hospitals = {}
    if hospital_ids:
        placeholders = ",".join("?" for _ in hospital_ids)
        hospitals = {
            h["id"]: h for h in catalog.execute(
                f"SELECT id, name, address, source_page_url FROM hospital WHERE id IN ({placeholders})",
                tuple(hospital_ids),
            ).fetchall()
        }
    out = []
    for r in rows:
        row = dict(r)
        h = hospitals.get(r["hospital_id"])
        row["hospital"] = h["name"] if h else None
        row["address"] = h["address"] if h else None
        row["source_page_url"] = h["source_page_url"] if h else None
        out.append(row)
    return {"appointments": out}


@app.post("/api/appointments")
def add_appointment(
    body: AppointmentIn,
    conn: sqlite3.Connection = Depends(get_conn),
    user_id: int = Depends(require_user),
):
    # `hospital_id` is a foreign key into this state database's `hospital`
    # table, but callers get hospital ids from the knowledge catalog
    # (`GET /api/hospitals`), which is a different database. Storing one here
    # raises IntegrityError; say so plainly instead of returning a 500.
    if body.hospital_id is not None and conn.execute(
        "SELECT 1 FROM hospital WHERE id = ?", (body.hospital_id,)
    ).fetchone() is None:
        raise HTTPException(
            status_code=422,
            detail="hospital_id is not known to this database; omit it and name the hospital in description",
        )
    cur = conn.execute(
        """INSERT INTO appointment (user_id, hospital_id, code, description, booked_for,
                                    estimated_cost, note, created_at)
           VALUES (?,?,?,?,?,?,?,?) RETURNING id""",
        (user_id, body.hospital_id, body.code, body.description, body.booked_for,
         body.estimated_cost, body.note,
         datetime.now(timezone.utc).isoformat(timespec="seconds")),
    )
    appointment_id = cur.fetchone()[0]
    conn.commit()
    return {"id": appointment_id, **body.model_dump()}


@app.delete("/api/appointments/{appointment_id}")
def delete_appointment(
    appointment_id: int,
    conn: sqlite3.Connection = Depends(get_conn),
    user_id: int = Depends(require_user),
):
    # Scoped by user as well as id, so guessing an id reveals nothing.
    cur = conn.execute(
        "DELETE FROM appointment WHERE id = ? AND user_id IS ?", (appointment_id, user_id)
    )
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="no such appointment")
    return {"ok": True}


@app.get("/api/search")
def search(q: str, limit: int = 10, catalog: sqlite3.Connection = Depends(get_catalog_conn)):
    return {"query": q, "results": retrieval.search(catalog, q, limit=limit)}


@app.get("/api/providers")
def providers(
    code: str,
    conn: sqlite3.Connection = Depends(get_conn),
    catalog: sqlite3.Connection = Depends(get_catalog_conn),
    user_id: int | None = Depends(optional_user),
):
    """Facilities that publish a price for this code, cheapest first."""
    prices = retrieval.prices_for_code(catalog, code)
    plan = _load_plan(conn, user_id)
    cost_share, share_status = retrieval.cost_share_status(
        conn, catalog, _qhp_plan_id(conn, user_id), code
    )
    out = []
    for p in prices:
        est = estimate(p.typical, plan, low_allowed=p.low, high_allowed=p.high,
                       cost_share=cost_share, cost_share_status=share_status)
        out.append({**p.as_dict(), "estimate": est.as_dict()})
    return {"code": code, "providers": out}
