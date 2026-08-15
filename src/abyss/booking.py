"""Permissioned sandbox scheduling for the Booking Agent.

The model may extract scheduling preferences. Deterministic code owns slot
generation, exact consent matching, idempotency, retries, and booking state.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from threading import Lock
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from .agent import AgentOutputError
from .hermes_client import HermesClient


class BookingModel(Protocol):
    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str: ...


@dataclass(frozen=True, slots=True)
class BookingPreferences:
    date_from: str
    date_to: str
    time_of_day: str
    source: str
    confidence: float

    def as_dict(self) -> dict:
        return {
            "date_from": self.date_from,
            "date_to": self.date_to,
            "time_of_day": self.time_of_day,
            "source": self.source,
            "confidence": self.confidence,
        }


@dataclass(frozen=True, slots=True)
class BookingSlot:
    slot_id: str
    hospital_id: int
    hospital: str
    procedure_code: str
    starts_at: str
    duration_minutes: int
    status: str = "available"
    source: str = "seeded sandbox schedule"
    retry_demo: bool = False

    def consent_scope(self, plan_name: str) -> str:
        return f"{self.slot_id} / {self.hospital} / {self.starts_at} / {plan_name}"

    def as_dict(self, plan_name: str) -> dict:
        return {
            "slot_id": self.slot_id,
            "hospital_id": self.hospital_id,
            "hospital": self.hospital,
            "procedure_code": self.procedure_code,
            "starts_at": self.starts_at,
            "duration_minutes": self.duration_minutes,
            "status": self.status,
            "source": self.source,
            "retry_demo": self.retry_demo,
            "consent_scope": self.consent_scope(plan_name),
        }


@dataclass(frozen=True, slots=True)
class ScheduledBookingTask:
    task_id: str
    journey_id: str
    slot_id: str
    consent_scope: str
    idempotency_key: str
    status: str
    attempts: int
    next_attempt_at: str
    last_error: str
    created_at: str
    completed_at: str | None = None

    def as_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "slot_id": self.slot_id,
            "status": self.status,
            "attempts": self.attempts,
            "next_attempt_at": self.next_attempt_at,
            "last_error": self.last_error,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }


@dataclass(frozen=True, slots=True)
class BookingNotification:
    notification_id: str
    journey_id: str
    kind: str
    message: str
    created_at: str
    read: bool = False

    def as_dict(self) -> dict:
        return {
            "notification_id": self.notification_id,
            "kind": self.kind,
            "message": self.message,
            "created_at": self.created_at,
            "read": self.read,
        }


@dataclass(frozen=True, slots=True)
class BookingAttempt:
    status: str
    slot: BookingSlot
    task: ScheduledBookingTask | None = None


BOOKING_PREFERENCES_PROMPT = """You are the bounded ABYSS Booking Agent.
Extract scheduling preferences from synthetic text. Return only JSON with
date_from and date_to in YYYY-MM-DD format and time_of_day as morning,
afternoon, or any. Do not select or book a slot. Do not provide medical advice."""


class BookingAgent:
    """Extract preferences and request slots; it has no booking authority."""

    def __init__(self, client: HermesClient | BookingModel | None = None) -> None:
        self.client = client

    def collect_preferences(
        self,
        text: str,
        *,
        default_date: str,
        source: str = "user_request",
    ) -> BookingPreferences:
        if not text.strip():
            raise ValueError("scheduling preferences are required")
        client = self.client or HermesClient()
        raw = client.chat([
            {"role": "system", "content": BOOKING_PREFERENCES_PROMPT},
            {"role": "user", "content": f"Synthetic scheduling request:\n{text.strip()}"},
        ], max_tokens=180, temperature=0.0)
        try:
            candidate = raw.strip()
            if not candidate.startswith("{"):
                candidate = candidate[candidate.find("{"):candidate.rfind("}") + 1]
            payload = json.loads(candidate)
            if set(payload) != {"date_from", "date_to", "time_of_day"}:
                raise TypeError
            date_from = date.fromisoformat(str(payload["date_from"]))
            date_to = date.fromisoformat(str(payload["date_to"]))
            time_of_day = str(payload["time_of_day"]).lower()
            if time_of_day not in {"morning", "afternoon", "any"} or date_to < date_from:
                raise ValueError
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            fallback = self._explicit_fallback(text, default_date)
            if fallback is None:
                raise AgentOutputError(
                    "Booking Agent did not return valid scheduling preferences"
                ) from exc
            return BookingPreferences(
                fallback[0], fallback[1], fallback[2], source, 1.0
            )
        return BookingPreferences(
            date_from.isoformat(), date_to.isoformat(), time_of_day, source, 0.9
        )

    @staticmethod
    def _explicit_fallback(text: str, default_date: str) -> tuple[str, str, str] | None:
        iso_dates = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", text)
        try:
            start = date.fromisoformat(iso_dates[0] if iso_dates else default_date)
            end = date.fromisoformat(iso_dates[1]) if len(iso_dates) > 1 else start + timedelta(days=14)
        except ValueError:
            return None
        lowered = text.lower()
        period = "morning" if "morning" in lowered else "afternoon" if "afternoon" in lowered else "any"
        return start.isoformat(), end.isoformat(), period


class SandboxBookingService:
    """Thread-safe synthetic slot inventory with exact-scope retry tasks."""

    def __init__(self, retry_delay_seconds: int = 4) -> None:
        self.retry_delay_seconds = retry_delay_seconds
        self._slots: dict[str, BookingSlot] = {}
        self._tasks: dict[str, ScheduledBookingTask] = {}
        self._notifications: list[BookingNotification] = []
        self._booked_idempotency: dict[str, BookingSlot] = {}
        self._transient_failures: set[str] = set()
        self._lock = Lock()

    def search_slots(
        self,
        *,
        hospital_id: int,
        hospital: str,
        procedure_code: str,
        preferences: BookingPreferences,
    ) -> list[BookingSlot]:
        start = date.fromisoformat(preferences.date_from)
        end = date.fromisoformat(preferences.date_to)
        candidates = [
            (start + timedelta(days=5), time(10, 30), True),
            (start + timedelta(days=6), time(14, 0), False),
            (start + timedelta(days=9), time(9, 0), False),
        ]
        output: list[BookingSlot] = []
        with self._lock:
            for day, starts, retry_demo in candidates:
                period = "morning" if starts.hour < 12 else "afternoon"
                if day > end or preferences.time_of_day not in {"any", period}:
                    continue
                timestamp = datetime.combine(
                    day, starts, tzinfo=ZoneInfo("America/Los_Angeles")
                ).isoformat()
                slot_id = f"slot-{hospital_id}-{procedure_code}-{day:%Y%m%d}-{starts:%H%M}"
                slot = self._slots.setdefault(slot_id, BookingSlot(
                    slot_id, hospital_id, hospital, procedure_code, timestamp, 45,
                    retry_demo=retry_demo,
                ))
                if slot.status == "available":
                    output.append(slot)
        return output

    def request_booking(
        self,
        *,
        journey_id: str,
        slot_id: str,
        expected_scope: str,
        consent_scope: str,
        idempotency_key: str,
    ) -> BookingAttempt:
        if consent_scope != expected_scope:
            raise RuntimeError("booking consent scope does not match the selected slot")
        with self._lock:
            existing = self._booked_idempotency.get(idempotency_key)
            if existing:
                return BookingAttempt("booked", existing)
            slot = self._slots.get(slot_id)
            if slot is None or slot.status != "available":
                raise RuntimeError("selected appointment slot is no longer available")
            if slot.retry_demo and slot_id not in self._transient_failures:
                self._transient_failures.add(slot_id)
                now = datetime.now(UTC)
                task_id = f"booking-task-{journey_id}-{slot_id}"
                task = ScheduledBookingTask(
                    task_id, journey_id, slot_id, consent_scope, idempotency_key,
                    "scheduled", 1,
                    (now + timedelta(seconds=self.retry_delay_seconds)).isoformat(),
                    "sandbox provider temporarily unavailable", now.isoformat(),
                )
                self._tasks[task_id] = task
                self._notifications.append(BookingNotification(
                    f"notification-{len(self._notifications) + 1}", journey_id,
                    "booking_retry_scheduled",
                    "The provider did not confirm immediately. ABYSS scheduled a retry for the exact approved slot.",
                    now.isoformat(),
                ))
                return BookingAttempt("scheduled_retry", slot, task)
            booked = replace(slot, status="booked")
            self._slots[slot_id] = booked
            self._booked_idempotency[idempotency_key] = booked
            return BookingAttempt("booked", booked)

    def process_due_tasks(self, now: datetime | None = None) -> list[ScheduledBookingTask]:
        current = now or datetime.now(UTC)
        completed: list[ScheduledBookingTask] = []
        with self._lock:
            for task_id, task in list(self._tasks.items()):
                if task.status != "scheduled" or datetime.fromisoformat(task.next_attempt_at) > current:
                    continue
                slot = self._slots.get(task.slot_id)
                if slot is None or slot.status != "available":
                    updated = replace(
                        task, status="needs_user_action", attempts=task.attempts + 1,
                        last_error="approved slot is no longer available",
                        completed_at=current.isoformat(),
                    )
                    message = "The approved slot became unavailable. Choose a new slot before ABYSS can continue."
                    kind = "booking_needs_user_action"
                else:
                    booked = replace(slot, status="booked")
                    self._slots[slot.slot_id] = booked
                    self._booked_idempotency[task.idempotency_key] = booked
                    updated = replace(
                        task, status="completed", attempts=task.attempts + 1,
                        last_error="", completed_at=current.isoformat(),
                    )
                    display_time = datetime.fromisoformat(slot.starts_at).strftime(
                        "%B %d, %Y at %I:%M %p %Z"
                    )
                    message = f"Booking confirmed for {slot.hospital} on {display_time}."
                    kind = "booking_confirmed"
                self._tasks[task_id] = updated
                self._notifications.append(BookingNotification(
                    f"notification-{len(self._notifications) + 1}", task.journey_id,
                    kind, message, current.isoformat(),
                ))
                completed.append(updated)
        return completed

    def tasks_for_journey(self, journey_id: str) -> list[ScheduledBookingTask]:
        with self._lock:
            return [task for task in self._tasks.values() if task.journey_id == journey_id]

    def notifications_for_journey(self, journey_id: str) -> list[BookingNotification]:
        with self._lock:
            return [item for item in self._notifications if item.journey_id == journey_id]

    def slot(self, slot_id: str) -> BookingSlot | None:
        with self._lock:
            return self._slots.get(slot_id)

    def cancel_booking(self, slot_id: str) -> BookingSlot:
        """Cancel only a known confirmed sandbox slot."""
        with self._lock:
            slot = self._slots.get(slot_id)
            if slot is None or slot.status != "booked":
                raise RuntimeError("original appointment is not confirmed")
            cancelled = replace(slot, status="cancelled")
            self._slots[slot_id] = cancelled
            return cancelled

    def restore_confirmed_slot(self, slot: BookingSlot) -> BookingSlot:
        """Restore a persisted sandbox receipt as confirmed inventory state."""
        confirmed = replace(slot, status="booked")
        with self._lock:
            self._slots[slot.slot_id] = confirmed
        return confirmed
