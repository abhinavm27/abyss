import unittest
from datetime import UTC, datetime, timedelta

from abyss.booking import (
    BookingAgent,
    BookingPreferences,
    SandboxBookingService,
)


class FakePreferenceModel:
    def chat(self, messages, **kwargs):
        return '{"date_from":"2026-08-30","date_to":"2026-09-15","time_of_day":"any"}'


class BookingTests(unittest.TestCase):
    def test_booking_agent_returns_validated_preferences(self) -> None:
        preferences = BookingAgent(FakePreferenceModel()).collect_preferences(
            "Any time from August 30 to September 15",
            default_date="2026-08-30",
        )
        self.assertEqual(preferences.date_from, "2026-08-30")
        self.assertEqual(preferences.time_of_day, "any")

    def test_exact_consent_scope_is_required(self) -> None:
        service = SandboxBookingService()
        slots = service.search_slots(
            hospital_id=1,
            hospital="Hospital A",
            procedure_code="73721",
            preferences=BookingPreferences(
                "2026-08-30", "2026-09-15", "any", "test", 1.0
            ),
        )
        expected = slots[0].consent_scope("Continuation PPO")
        with self.assertRaises(RuntimeError):
            service.request_booking(
                journey_id="journey-1",
                slot_id=slots[0].slot_id,
                expected_scope=expected,
                consent_scope="different slot",
                idempotency_key="book-1",
            )

    def test_transient_failure_schedules_and_completes_exact_retry(self) -> None:
        service = SandboxBookingService(retry_delay_seconds=4)
        slots = service.search_slots(
            hospital_id=1,
            hospital="Hospital A",
            procedure_code="73721",
            preferences=BookingPreferences(
                "2026-08-30", "2026-09-15", "any", "test", 1.0
            ),
        )
        self.assertTrue(slots[0].starts_at.endswith("-07:00"))
        slot = slots[0]
        scope = slot.consent_scope("Continuation PPO")
        attempt = service.request_booking(
            journey_id="journey-1",
            slot_id=slot.slot_id,
            expected_scope=scope,
            consent_scope=scope,
            idempotency_key="book-1",
        )
        self.assertEqual(attempt.status, "scheduled_retry")
        self.assertEqual(attempt.task.status, "scheduled")

        completed = service.process_due_tasks(datetime.now(UTC) + timedelta(seconds=5))
        self.assertEqual(completed[0].status, "completed")
        self.assertEqual(service.slot(slot.slot_id).status, "booked")
        notifications = service.notifications_for_journey("journey-1")
        self.assertEqual(notifications[-1].kind, "booking_confirmed")


if __name__ == "__main__":
    unittest.main()
