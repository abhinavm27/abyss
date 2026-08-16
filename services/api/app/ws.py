"""Consent-safe NVIDIA speech bridge for the Care Journey Agent.

Temporary compatibility protocol for the imported audio client:

    CLIENT -> SERVER (JSON text frames)
      { "type": "speech_start" }
      { "type": "audio", "data": "<base64 PCM 16 kHz mono>" }
      { "type": "speech_end" }
      { "type": "text",  "text": "how much is a knee MRI" }

    SERVER -> CLIENT (JSON text frames)
      { "type": "ready", "output_sample_rate": 22050 }
      { "type": "transcript", "role": "user"|"assistant", "text": "..." }
      { "type": "audio", "data": "<base64 PCM 22.05 kHz mono>" }
      { "type": "ui", "target": "care_journey", "payload": { ... } }
      { "type": "turn_complete" }
      { "type": "error", "message": "..." }

Parakeet performs ASR, the existing Care Journey Agent routes the transcript
through Hermes/Nemotron and deterministic rules, and Magpie speaks only the
grounded response returned by that path.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import uuid
from collections.abc import Callable
from typing import Any

from fastapi import HTTPException, WebSocket, WebSocketDisconnect

from . import auth, db, retrieval
from .ingest import qhp
from .estimator import Plan, estimate
from .nvidia_speech import NvidiaSpeechClient, NvidiaSpeechError

log = logging.getLogger(__name__)

def _plan_row(conn, user_id: int | None):
    return conn.execute(
        "SELECT * FROM plan WHERE user_id IS ? AND is_active = 1 ORDER BY id DESC LIMIT 1",
        (user_id,),
    ).fetchone()


def _load_plan(conn, user_id: int | None = None) -> Plan:
    row = _plan_row(conn, user_id)
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


def run_lookup_price(
    conn, procedure: str, code: str | None = None, user_id: int | None = None
) -> tuple[dict, dict]:
    """Execute a price lookup.

    Returns (compact_result_for_the_model, full_payload_for_the_ui). The model
    gets a trimmed version so it has less to hallucinate around; the UI gets the
    full record including citations and the per-line breakdown.
    """
    if code:
        row = conn.execute(
            "SELECT code, code_type FROM rate WHERE code = ? LIMIT 1", (code,)
        ).fetchone()
        resolution = (
            retrieval.Resolution(row["code"], row["code_type"], "confirmed", True)
            if row
            else retrieval.Resolution(None, None, "unknown-code", False)
        )
    else:
        resolution = retrieval.resolve_code(conn, procedure)

    if not resolution.code:
        payload = {
            "query": procedure,
            "resolved": None,
            "resolution": resolution.how,
            "hospitals": [],
            "message": "No billing code in the ingested files matches that.",
        }
        return {"found": False, "reason": "no_match"}, payload

    if not resolution.confident:
        candidates = resolution.candidates[:5]
        payload = {
            "query": procedure,
            "resolved": None,
            "resolution": resolution.how,
            "needs_confirmation": True,
            "candidates": candidates,
            "hospitals": [],
            "message": "That didn't match a procedure ABYSS recognises. Which did you mean?",
        }
        return {
            "found": False,
            "needs_confirmation": True,
            "options": [
                {"code": c["code"], "description": c["description"]} for c in candidates
            ],
        }, payload

    prices = retrieval.prices_for_code(conn, resolution.code, resolution.code_type)
    formula_rows = retrieval.formula_priced_count(conn, resolution.code)

    if not prices:
        payload = {
            "query": procedure,
            "resolved": {"code": resolution.code, "code_type": resolution.code_type},
            "resolution": resolution.how,
            "hospitals": [],
            "formula_priced_rows": formula_rows,
            "message": (
                "These hospitals publish this service as a contractual formula rather "
                "than a dollar amount, so no estimate can be derived from the file."
            ),
        }
        return {
            "found": False,
            "reason": "published_as_formula",
            "formula_priced_rows": formula_rows,
        }, payload

    plan = _load_plan(conn, user_id)
    # The member's own rule for this service category, when they linked a plan
    # or uploaded an SBC. Without this the spoken answer would use a blended
    # rate while the REST path used the real one — same question, two numbers.
    plan_row = _plan_row(conn, user_id)
    cost_share, share_status = retrieval.cost_share_status(
        conn, plan_row["qhp_plan_id"] if plan_row else None, resolution.code
    )

    hospitals, compact = [], []
    for rank, p in enumerate(prices):
        est = estimate(p.typical, plan, low_allowed=p.low, high_allowed=p.high,
                       cost_share=cost_share, cost_share_status=share_status)
        hospitals.append({**p.as_dict(), "estimate": est.as_dict()})
        compact.append(
            {
                "rank": rank + 1,
                "hospital": p.hospital,
                "you_pay_low": est.low,
                "you_pay_high": est.high,
                "you_pay_typical": est.expected,
            }
        )

    payload = {
        "query": procedure,
        "resolved": {
            "code": resolution.code,
            "code_type": resolution.code_type,
            "description": prices[0].description,
        },
        "resolution": resolution.how,
        "plan_configured": bool(
            plan.deductible or plan.oop_max or plan.coinsurance_pct or plan.copay
        ),
        "hospitals": hospitals,
        "cash_prices": retrieval.cash_prices_for_code(conn, resolution.code),
        "formula_priced_rows": formula_rows,
    }
    # The cheapest option, matching what is said out loud and what the REST
    # route records — one question must not produce two different ranges.
    db.record_lookup(
        conn, procedure, resolution.code, prices[0].description,
        compact[0]["you_pay_low"], compact[0]["you_pay_high"],
        user_id=user_id,
    )

    # The cheapest option is stated outright rather than left for the model to
    # infer. Ties on the low end are common (two hospitals often share a floor
    # rate), and ranking by the wrong field names the wrong hospital out loud.
    return {
        "found": True,
        "procedure": prices[0].description,
        "code": resolution.code,
        "plan_applied": payload["plan_configured"],
        "cheapest": compact[0],
        "most_expensive": compact[-1],
        "potential_saving": round(compact[-1]["you_pay_typical"] - compact[0]["you_pay_typical"], 2),
        "hospitals": compact,
    }, payload


def run_get_my_plan(
    conn, category: str | None = None, user_id: int | None = None
) -> tuple[dict, dict]:
    """Answer a question about the member's own coverage.

    Returns (compact_result_for_the_model, full_payload_for_the_ui). Everything
    comes from the stored plan — if the member never set one up, that is said
    plainly rather than described in general terms, because a generic answer to
    "what's my deductible" reads as a real one.
    """
    row = _plan_row(conn, user_id)
    if not row:
        payload = {"configured": False}
        return {"configured": False, "reason": "no_plan_set_up"}, payload

    plan = _load_plan(conn, user_id)
    linked_id = row["qhp_plan_id"]

    remaining_deductible = plan.remaining_deductible
    remaining_oop = plan.remaining_oop
    has_oop_cap = plan.oop_max > 0

    benefits: list[dict] = []
    if linked_id:
        rows = conn.execute(
            """SELECT category, kind, amount, after_deductible FROM plan_benefit
               WHERE plan_id = ? AND kind != 'unknown' ORDER BY category""",
            (linked_id,),
        ).fetchall()
        benefits = [dict(r) for r in rows]

    def describe(b: dict) -> str:
        if b["kind"] == "not_covered":
            return "not covered"
        if b["kind"] == "no_charge":
            base = "covered in full"
        elif b["kind"] == "copay":
            base = f"${b['amount']:,.0f} copay"
        else:
            base = f"{b['amount']:.0%} coinsurance"
        return base + (" after the deductible" if b["after_deductible"] else "")

    payload = {
        "configured": True,
        "label": row["label"],
        "payer_name": row["payer_name"],
        "source": (
            "uploaded document" if linked_id == "SBC-UPLOADED"
            else "marketplace plan" if linked_id
            else "entered by hand"
        ),
        "deductible": plan.deductible,
        "deductible_met": plan.deductible_met,
        "deductible_remaining": remaining_deductible,
        "oop_max": plan.oop_max,
        "oop_met": plan.oop_met,
        "oop_remaining": remaining_oop if has_oop_cap else None,
        "benefits": [{**b, "description": describe(b)} for b in benefits],
    }

    compact: dict = {
        "configured": True,
        "plan_name": row["label"],
        "deductible": plan.deductible,
        "deductible_met": plan.deductible_met,
        "deductible_remaining": remaining_deductible,
        "deductible_is_met": remaining_deductible <= 0,
        "out_of_pocket_max": plan.oop_max if has_oop_cap else None,
        "out_of_pocket_remaining": remaining_oop if has_oop_cap else None,
    }

    if category:
        match = next((b for b in benefits if b["category"] == category), None)
        if match:
            compact["asked_about"] = {"category": category, "charge": describe(match)}
            payload["highlight"] = category
        else:
            # Only a linked plan carries per-service detail. Saying so is more
            # use than a blended rate that was never in their plan document.
            compact["asked_about"] = {
                "category": category,
                "charge": None,
                "reason": (
                    "this plan has no published detail for that service"
                    if linked_id
                    else "their benefits were entered by hand, so only the deductible, "
                         "coinsurance and out-of-pocket maximum are known"
                ),
            }
    elif benefits:
        compact["covers"] = [
            {"category": b["category"], "charge": describe(b)} for b in benefits
        ]

    return compact, payload


def run_update_plan_usage(
    conn,
    deductible_met: float | None = None,
    oop_met: float | None = None,
    add: bool = False,
    user_id: int | None = None,
) -> tuple[dict, dict]:
    """Record what the member says they have now paid.

    `add` distinguishes "another $200" from "it's at $1,500" — getting that
    backwards would silently reset someone's progress, so the model is told to
    set it explicitly and the result is always read back to them.
    """
    row = _plan_row(conn, user_id)
    if not row:
        return {"ok": False, "reason": "no_plan_set_up"}, {"configured": False}

    new_deductible = row["deductible_met"]
    new_oop = row["oop_met"]
    if deductible_met is not None:
        new_deductible = (row["deductible_met"] + deductible_met) if add else deductible_met
    if oop_met is not None:
        new_oop = (row["oop_met"] + oop_met) if add else oop_met

    new_deductible = max(0.0, float(new_deductible))
    new_oop = max(0.0, float(new_oop))

    conn.execute(
        "UPDATE plan SET deductible_met = ?, oop_met = ? WHERE id = ?",
        (new_deductible, new_oop, row["id"]),
    )
    conn.commit()

    _, payload = run_get_my_plan(conn, user_id=user_id)
    return (
        {
            "ok": True,
            "deductible_met": new_deductible,
            "deductible_remaining": max(0.0, row["deductible"] - new_deductible),
            "oop_met": new_oop,
        },
        payload,
    )


CareTurn = Callable[[str, str | None, int, str, str], dict[str, Any]]


async def _stream_magpie(
    ws: WebSocket,
    speech: NvidiaSpeechClient,
    text: str,
) -> None:
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[bytes | Exception | None] = asyncio.Queue()

    def produce() -> None:
        try:
            speech.stream_speech(
                text,
                lambda chunk: loop.call_soon_threadsafe(queue.put_nowait, chunk),
            )
        except Exception as error:
            loop.call_soon_threadsafe(queue.put_nowait, error)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    worker = asyncio.create_task(asyncio.to_thread(produce))
    while True:
        item = await queue.get()
        if item is None:
            break
        if isinstance(item, Exception):
            raise item
        await ws.send_json({"type": "audio", "data": base64.b64encode(item).decode()})
    await worker


async def voice_endpoint(
    ws: WebSocket,
    *,
    care_turn: CareTurn,
    speech: NvidiaSpeechClient | None = None,
) -> None:
    """Bridge half-duplex audio turns into the same journey path as typed chat."""
    await ws.accept()
    speech = speech or NvidiaSpeechClient()
    conn = db.connect()
    db.init_db(conn)

    user_id: int | None = None
    requested_journey_id: str | None = None
    try:
        first = json.loads(await ws.receive_text())
        if first.get("type") == "auth":
            user_id = auth.user_for_token(conn, first.get("token"))
            if isinstance(first.get("active_journey_id"), str):
                candidate = str(first["active_journey_id"]).strip()
                owned = conn.execute(
                    "SELECT 1 FROM care_journey WHERE journey_id=? AND user_id=?",
                    (candidate, user_id),
                ).fetchone()
                if owned:
                    requested_journey_id = candidate
    except (json.JSONDecodeError, KeyError):
        pass
    if user_id is None:
        await ws.send_json({"type": "error", "message": "sign in to use voice"})
        await ws.close()
        conn.close()
        return

    health = await asyncio.to_thread(speech.health)
    if not all(health.values()):
        await ws.send_json({
            "type": "error",
            "message": "NVIDIA speech services are not ready",
            "services": health,
        })
        await ws.close()
        conn.close()
        return

    session_id = f"voice-{uuid.uuid4().hex[:12]}"
    correlation_id = f"correlation-{uuid.uuid4().hex[:12]}"
    # A browser reconnect is a transport event, not a new care journey.
    active_journey_id: str | None = requested_journey_id
    utterance_id: str | None = None
    pcm = bytearray()
    max_pcm_bytes = speech.config.input_sample_rate * 2 * 45

    async def process_turn(text: str, turn_id: str) -> None:
        nonlocal active_journey_id
        normalized = text.strip()
        if not normalized:
            await ws.send_json({"type": "turn_complete"})
            return
        await ws.send_json({
            "type": "transcript", "role": "user", "text": normalized,
            "utterance_id": turn_id, "session_id": session_id,
        })
        await ws.send_json({"type": "processing", "stage": "reasoning"})
        result = await asyncio.to_thread(
            care_turn,
            normalized,
            active_journey_id,
            user_id,
            turn_id,
            correlation_id,
        )
        journey = result.get("journey")
        if isinstance(journey, dict) and journey.get("journey_id"):
            active_journey_id = str(journey["journey_id"])
        await ws.send_json({"type": "ui", "target": "care_journey", "payload": result})
        reply = str(result.get("reply") or "I could not determine the next journey step.")
        await ws.send_json({
            "type": "transcript", "role": "assistant", "text": reply,
            "utterance_id": turn_id, "session_id": session_id,
        })
        await ws.send_json({"type": "processing", "stage": "speaking"})
        await _stream_magpie(ws, speech, reply)
        await ws.send_json({"type": "turn_complete"})

    async def process_turn_safely(text: str, turn_id: str) -> None:
        """Keep a recoverable agent-turn failure from ending the voice session."""
        try:
            await process_turn(text, turn_id)
        except HTTPException as exc:
            detail = str(exc.detail)
            log.warning("voice turn rejected: %s", detail)
            await ws.send_json({
                "type": "turn_error", "message": detail, "recoverable": True,
                "utterance_id": turn_id, "session_id": session_id,
            })
            await ws.send_json({"type": "turn_complete"})

    try:
        await ws.send_json({
            "type": "ready",
            "provider": "nvidia",
            "asr_model": "parakeet-1.1b-ctc-en-us",
            "reasoning_model": "hermes-nemotron",
            "tts_model": "magpie-tts-multilingual",
            "input_sample_rate": speech.config.input_sample_rate,
            "output_sample_rate": speech.config.output_sample_rate,
            "session_id": session_id,
        })
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            kind = msg.get("type")
            if kind == "speech_start":
                pcm.clear()
                utterance_id = f"utterance-{uuid.uuid4().hex[:12]}"
                await ws.send_json({"type": "listening", "utterance_id": utterance_id})
            elif kind == "audio" and msg.get("data"):
                try:
                    chunk = base64.b64decode(msg["data"], validate=True)
                except (ValueError, TypeError):
                    continue
                if len(pcm) + len(chunk) <= max_pcm_bytes:
                    pcm.extend(chunk)
            elif kind == "speech_end":
                turn_id = utterance_id or f"utterance-{uuid.uuid4().hex[:12]}"
                if len(pcm) < speech.config.input_sample_rate // 2:
                    pcm.clear()
                    await ws.send_json({"type": "turn_complete"})
                    continue
                await ws.send_json({"type": "processing", "stage": "transcribing"})
                try:
                    text = await asyncio.to_thread(speech.transcribe_pcm, bytes(pcm))
                except NvidiaSpeechError as exc:
                    pcm.clear()
                    await ws.send_json({
                        "type": "turn_error", "message": str(exc), "recoverable": True,
                        "utterance_id": turn_id, "session_id": session_id,
                    })
                    await ws.send_json({"type": "turn_complete"})
                    continue
                pcm.clear()
                await process_turn_safely(text, turn_id)
            elif kind == "text" and msg.get("text"):
                await process_turn_safely(
                    str(msg["text"]), f"utterance-{uuid.uuid4().hex[:12]}"
                )
    except WebSocketDisconnect:
        pass
    except (NvidiaSpeechError, RuntimeError, ValueError) as exc:
        log.exception("voice turn failed")
        try:
            await ws.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass
    except Exception:
        log.exception("voice session failed")
        try:
            await ws.send_json({"type": "error", "message": "voice session failed"})
        except Exception:
            pass
    finally:
        conn.close()
        try:
            await ws.close()
        except Exception:
            pass
