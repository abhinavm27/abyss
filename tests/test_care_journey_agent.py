import unittest

from abyss.care_journey_agent import CareJourneyAgent, JourneyIntent


class FakePlanner:
    def __init__(self, payload: str) -> None:
        self.payload = payload

    def chat(self, messages, **kwargs):
        return self.payload


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

    def test_unauthorized_model_reference_uses_bounded_fallback(self) -> None:
        model = FakePlanner(
            '{"intent":"reschedule_appointment","target_journey_id":"journey-other",'
            '"target_appointment_id":null,"steps":[],"reuse":[],"refresh":[],"missing":[]}'
        )
        plan = CareJourneyAgent(model).plan(
            "Reschedule my MRI appointment", context=self.context,
            active_journey_id="journey-mri",
        )
        self.assertEqual(plan.source, "deterministic_fallback")
        self.assertEqual(plan.target_journey_id, "journey-mri")
        self.assertEqual(plan.target_appointment_id, "appointment-mri")


if __name__ == "__main__":
    unittest.main()
