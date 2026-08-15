import unittest

from abyss.care_journey_agent import CareJourneyAgent, JourneyIntent


class FakePlanner:
    def __init__(self, payload: str) -> None:
        self.payload = payload

    def chat(self, messages, **kwargs):
        return self.payload


class SequencedPlanner:
    def __init__(self, *payloads: str) -> None:
        self.payloads = list(payloads)
        self.calls = 0

    def chat(self, messages, **kwargs):
        payload = self.payloads[min(self.calls, len(self.payloads) - 1)]
        self.calls += 1
        return payload


class CareJourneyAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = {
            "user": {"user_id": "7"},
            "journeys": [
                {"journey_id": "journey-mri", "stage": "complete", "status": "complete"},
                {"journey_id": "journey-pt", "stage": "intake", "status": "active"},
            ],
            "appointments": [
                {"appointment_id": "appointment-mri", "journey_id": "journey-mri", "status": "confirmed"},
            ],
        }

    def test_agent_routes_reschedule_to_existing_journey(self) -> None:
        model = FakePlanner(
            '{"intent":"reschedule_appointment","target_journey_id":"journey-mri",'
            '"target_appointment_id":"appointment-mri","steps":["search_replacement_slots"],'
            '"reuse":["procedure_code","selected_care_path"],'
            '"refresh":["appointment_availability"],"missing":[]}'
        )
        plan = CareJourneyAgent(model).plan(
            "Move my MRI to next Friday", context=self.context,
            active_journey_id="journey-pt",
        )
        self.assertEqual(plan.intent, JourneyIntent.RESCHEDULE_APPOINTMENT)
        self.assertEqual(plan.target_journey_id, "journey-mri")
        self.assertTrue(plan.correlation_id.startswith("correlation-"))

    def test_model_format_variations_are_normalized_without_changing_intent(self) -> None:
        model = FakePlanner(
            '{"intent":"new_care_request","target_journey_id":"",'
            '"target_appointment_id":"","steps":[],"reuse":false,'
            '"refresh":false,"missing":[]}'
        )
        plan = CareJourneyAgent(model).plan(
            "book an ultrasound scan", context=self.context,
            active_journey_id="journey-mri",
        )
        self.assertEqual(plan.intent, JourneyIntent.NEW_CARE_REQUEST)
        self.assertIsNone(plan.target_journey_id)
        self.assertEqual(plan.source, "hermes")
        self.assertEqual(plan.attempt_count, 1)
        self.assertIn("target_journey_id:empty_string_to_null", plan.normalizations)
        self.assertIn("reuse:empty_value_to_array", plan.normalizations)

    def test_invalid_schema_is_retried_with_model_feedback(self) -> None:
        model = SequencedPlanner(
            '{"intent":"new_care_request","steps":"start"}',
            '{"intent":"new_care_request","target_journey_id":null,'
            '"target_appointment_id":null,"steps":["start_journey"],'
            '"reuse":[],"refresh":[],"missing":[]}',
        )
        plan = CareJourneyAgent(model).plan(
            "book an ultrasound scan", context=self.context,
            active_journey_id="journey-mri",
        )
        self.assertEqual(plan.intent, JourneyIntent.NEW_CARE_REQUEST)
        self.assertEqual(plan.source, "hermes_schema_retry")
        self.assertEqual(plan.attempt_count, 2)
        self.assertEqual(model.calls, 2)
        self.assertTrue(plan.validation_errors)

    def test_unauthorized_model_reference_fails_to_safe_clarification(self) -> None:
        model = FakePlanner(
            '{"intent":"reschedule_appointment","target_journey_id":"journey-other",'
            '"target_appointment_id":null,"steps":[],"reuse":[],"refresh":[],"missing":[]}'
        )
        plan = CareJourneyAgent(model).plan(
            "Reschedule my MRI appointment", context=self.context,
            active_journey_id="journey-mri",
        )
        self.assertEqual(plan.intent, JourneyIntent.UNKNOWN)
        self.assertEqual(plan.source, "safe_clarification")
        self.assertIsNone(plan.target_journey_id)
        self.assertIsNone(plan.target_appointment_id)
        self.assertEqual(plan.confidence, 0.0)


if __name__ == "__main__":
    unittest.main()
