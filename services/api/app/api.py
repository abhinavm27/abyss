"""FastAPI service: price lookup, estimation, providers, booking, plan.

Runs on :8010 by default.
"""

from __future__ import annotations

import io
import os
import sqlite3
import uuid
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from abyss.agent import explain
from abyss.hermes_client import HermesError
from abyss.domain import ConsentAction, DecisionFact, VerificationStatus
from abyss.journey import CareJourney
from abyss.knowledge import SQLiteHospitalKnowledgeCatalog

from . import auth, db, retrieval
from .ingest import sbc
from .estimator import Plan, estimate
from .ws import voice_endpoint

app = FastAPI(title="ABYSS", version="0.1.0")

# The journey store is intentionally process-local for the sandbox demo. A
# production deployment would persist the same events and receipts in the
# application database; it must never silently turn a sandbox receipt into a
# production action.
_journeys: dict[str, CareJourney] = {}


def _journey_dependencies() -> dict:
    """Build adapters without coupling the journey domain to FastAPI."""
    knowledge_db = os.getenv("ABYSS_KNOWLEDGE_DB")
    if not knowledge_db:
        return {}
    return {"hospital_knowledge": SQLiteHospitalKnowledgeCatalog(knowledge_db)}


@app.websocket("/ws")
async def voice(ws: WebSocket):
    await voice_endpoint(ws)

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


class AgentChatIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    evidence: dict = Field(default_factory=dict)


class JourneyStartIn(BaseModel):
    procedure: str = Field(default="MRI knee without contrast", min_length=1)
    provider: str = Field(default="Dr. Lee", min_length=1)
    facility: str = Field(default="Seattle General", min_length=1)


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


def _journey_payload(journey: CareJourney) -> dict:
    return {
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
    }


@app.post("/api/journeys")
def start_journey(body: JourneyStartIn, user_id: int = Depends(require_user)):
    journey_id = f"journey-{uuid.uuid4().hex[:12]}"
    journey = CareJourney.open(journey_id, user_id=str(user_id), **_journey_dependencies())
    now = datetime.now(timezone.utc)
    for name, value in (("requested_procedure", body.procedure), ("preferred_provider", body.provider),
                        ("preferred_facility", body.facility)):
        journey.record_fact(DecisionFact(name, value, "user_request", now, 1.0, VerificationStatus.SOURCE_BACKED))
    _journeys[journey_id] = journey
    return _journey_payload(journey)


@app.get("/api/journeys/{journey_id}")
def get_journey(journey_id: str, user_id: int = Depends(require_user)):
    journey = _journeys.get(journey_id)
    if journey is None or not journey.workflow.care_state.session_id.endswith(f":{user_id}"):
        raise HTTPException(status_code=404, detail="journey not found")
    return _journey_payload(journey)


@app.get("/api/admin/journeys")
def admin_journeys(user_id: int = Depends(require_user)):
    """Synthetic operations view for the hackathon admin console."""
    return {"journeys": [_journey_payload(journey) for journey in _journeys.values()]}


@app.post("/api/journeys/{journey_id}/onboard")
def onboard_journey(journey_id: str, body: JourneyOnboardIn, user_id: int = Depends(require_user)):
    journey = _journeys.get(journey_id)
    if journey is None or not journey.workflow.care_state.session_id.endswith(f":{user_id}"):
        raise HTTPException(status_code=404, detail="journey not found")
    try:
        journey.onboard(body.text, source=body.source)
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
        journey.advance()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _journey_payload(journey)


@app.post("/api/agent/chat")
def agent_chat(body: AgentChatIn, user_id: int = Depends(require_user)):
    """Have GN100-hosted Hermes explain an authoritative ABYSS result."""
    try:
        return {"reply": explain(body.question, body.evidence)}
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

    The rate count comes from the planner's statistics rather than a COUNT(*):
    counting 39.6M rows took 32 seconds and this is the first request the app
    makes, so it timed out the dev proxy and the app never started.
    """
    hospitals = conn.execute("SELECT COUNT(*) c FROM hospital").fetchone()["c"]
    return {"ok": True, "rates": db.approximate_rate_count(conn), "hospitals": hospitals}


@app.get("/api/hospitals")
def hospitals(conn: sqlite3.Connection = Depends(get_conn)):
    # rows_written from the last ingest, rather than COUNT(*) per hospital —
    # grouping 39.6M rows to render a list would take half a minute.
    rows = conn.execute(
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
                             deductible_met, coinsurance_pct, copay, oop_max, oop_met)
           VALUES (?,1,?,?,?,?,?,?,?,?,?) RETURNING id""",
        (user_id, body.label, body.payer_name, body.qhp_plan_id, body.deductible,
         body.deductible_met, body.coinsurance_pct, body.copay, body.oop_max, body.oop_met),
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
    file: UploadFile = File(...), user_id: int = Depends(require_user)
):
    """Read a photo of an insurance card.

    Identification only. A card carries the payer, plan name and member number,
    but not the deductible, out-of-pocket maximum or coinsurance — so this
    prefills what it can see and the Summary of Benefits supplies the rest.
    """
    from .ingest import card

    data = await file.read()
    if len(data) > 12_000_000:
        raise HTTPException(status_code=413, detail="that image is too large")
    result = card.parse(data, file.content_type or "image/jpeg")
    return {"filename": file.filename, **result.as_dict()}


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
                             deductible_met, coinsurance_pct, copay, oop_max, oop_met)
           VALUES (?,1,?,?,?,?,?,?,?,?,?) RETURNING id""",
        (user_id, body.label or "Uploaded plan", body.payer_name, SBC_PLAN_ID, body.deductible,
         body.deductible_met, 0.0, None, body.oop_max, body.oop_met),
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


@app.get("/api/plans/search")
def search_plans(
    state: str,
    q: str | None = None,
    metal: str | None = None,
    limit: int = 25,
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Find a marketplace plan to link, so estimates use its real cost sharing.

    Only federal-platform states are present — the CMS Public Use Files do not
    cover state-run marketplaces (MA, RI, CA, NY and others). Those members, and
    anyone on employer coverage, enter their benefits by hand instead.
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
    user_id: int | None = Depends(optional_user),
):
    """Answer a price question, personalised to the stored plan.

    Signing in is not required. Published hospital prices are public, and a
    member who has not finished onboarding should still see them — they simply
    are not personalised.

    Pass `code` to price a specific billing code directly — that is how the
    client confirms one of the candidates offered when a query is ambiguous.
    """
    if code:
        row = conn.execute(
            "SELECT code, code_type FROM rate WHERE code = ? LIMIT 1", (code,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"unknown code {code}")
        resolution = retrieval.Resolution(row["code"], row["code_type"], "confirmed", True)
    else:
        resolution = retrieval.resolve_code(conn, q)

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
    prices = retrieval.prices_for_code(conn, code, code_type)
    formula_only = retrieval.formula_priced_count(conn, code)

    if not prices:
        # The code exists but no hospital published a dollar figure for it.
        return {
            "query": q,
            "resolved": {"code": code, "code_type": code_type},
            "resolution": how,
            "hospitals": [],
            "formula_priced_rows": formula_only,
            "message": (
                "These hospitals publish this service as a contractual formula rather "
                "than a dollar amount, so no estimate can be derived from the file."
            ),
        }

    plan = _load_plan(conn, user_id)
    plan_configured = plan.deductible or plan.oop_max or plan.coinsurance_pct or plan.copay
    cost_share, share_status = retrieval.cost_share_status(
        conn, _qhp_plan_id(conn, user_id), code
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
        "cash_prices": retrieval.cash_prices_for_code(conn, code),
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
    resolution = retrieval.resolve_code(conn, q)
    if not resolution.code or not resolution.confident:
        return {"query": q, "resolved": None, "plans": [],
                "message": "Name the procedure a little more precisely to compare plans."}

    prices = retrieval.prices_for_code(conn, resolution.code)
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
            conn, row["qhp_plan_id"], resolution.code
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

    resolution = retrieval.resolve_code(conn, body.query)
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

    ref = retrieval.billed_reference(conn, resolution.code, body.hospital_id)
    if not ref:
        return {
            "resolved": {"code": resolution.code},
            "message": "No hospital publishes a dollar price for this code, so there is nothing "
                       "to compare against.",
        }

    hospital = None
    if body.hospital_id is not None:
        row = conn.execute(
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
            conn, _qhp_plan_id(conn, user_id), resolution.code
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
    conn: sqlite3.Connection = Depends(get_conn), user_id: int = Depends(require_user)
):
    """Soonest first, with anything undated last."""
    rows = conn.execute(
        """SELECT a.*, h.name AS hospital, h.address, h.source_page_url
           FROM appointment a LEFT JOIN hospital h ON h.id = a.hospital_id
           WHERE a.user_id IS ?
           ORDER BY a.booked_for IS NULL, a.booked_for, a.id""",
        (user_id,),
    ).fetchall()
    return {"appointments": [dict(r) for r in rows]}


@app.post("/api/appointments")
def add_appointment(
    body: AppointmentIn,
    conn: sqlite3.Connection = Depends(get_conn),
    user_id: int = Depends(require_user),
):
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
def search(q: str, limit: int = 10, conn: sqlite3.Connection = Depends(get_conn)):
    return {"query": q, "results": retrieval.search(conn, q, limit=limit)}


@app.get("/api/providers")
def providers(
    code: str,
    conn: sqlite3.Connection = Depends(get_conn),
    user_id: int | None = Depends(optional_user),
):
    """Facilities that publish a price for this code, cheapest first."""
    prices = retrieval.prices_for_code(conn, code)
    plan = _load_plan(conn, user_id)
    cost_share, share_status = retrieval.cost_share_status(
        conn, _qhp_plan_id(conn, user_id), code
    )
    out = []
    for p in prices:
        est = estimate(p.typical, plan, low_allowed=p.low, high_allowed=p.high,
                       cost_share=cost_share, cost_share_status=share_status)
        out.append({**p.as_dict(), "estimate": est.as_dict()})
    return {"code": code, "providers": out}
