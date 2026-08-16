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
    def test_explicit_pending_reply_skips_semantic_replanning(self) -> None:
        context = {
            "journeys": [{
                "journey_id": "journey-blood",
                "stage": "intake",
                "pending_fields": ["procedure_code_confirmation"],
                "pending_questions": ["Which blood test was ordered?"],
            }],
        }
        plan = CareJourneyAgent.pending_reply_plan(
            context,
            "journey-blood",
            utterance_id="utterance-1",
            correlation_id="correlation-1",
        )
        self.assertIsNotNone(plan)
        self.assertEqual(plan.intent, JourneyIntent.CONTINUE_JOURNEY)
        self.assertEqual(plan.target_journey_id, "journey-blood")
        self.assertEqual(plan.source, "explicit_pending_reply")

    def test_pending_reply_fast_path_requires_exact_active_intake(self) -> None:
        context = {"journeys": [{
            "journey_id": "journey-complete",
            "stage": "complete",
            "pending_fields": [],
        }]}
        self.assertIsNone(CareJourneyAgent.pending_reply_plan(
            context,
            "journey-complete",
            utterance_id="utterance-2",
            correlation_id="correlation-2",
        ))

    def test_voice_exact_pending_answer_uses_fast_path(self) -> None:
        context = {"journeys": [{
            "journey_id": "journey-ultrasound",
            "stage": "intake",
            "pending_fields": ["procedure_code_confirmation"],
        }]}
        plan = CareJourneyAgent.explicit_pending_reply_plan(
            "Complete abdominal ultrasound",
            context,
            "journey-ultrasound",
            utterance_id="utterance-voice",
            correlation_id="correlation-voice",
        )
        self.assertIsNotNone(plan)
        self.assertEqual(plan.source, "explicit_pending_reply")

    def test_voice_ambiguous_pending_answer_keeps_model_reasoning(self) -> None:
        context = {"journeys": [{
            "journey_id": "journey-ultrasound",
            "stage": "intake",
            "pending_fields": ["procedure_code_confirmation"],
        }]}
        plan = CareJourneyAgent.explicit_pending_reply_plan(
            "I want to do something else",
            context,
            "journey-ultrasound",
            utterance_id="utterance-voice",
            correlation_id="correlation-voice",
        )
        self.assertIsNone(plan)

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

    def test_clarification_answer_can_continue_active_intake_journey(self) -> None:
        context = dict(self.context)
        context["journeys"] = [
            {
                "journey_id": "journey-ultrasound",
                "stage": "intake",
                "status": "active",
                "pending_fields": ["procedure_code_confirmation"],
                "pending_questions": [
                    "What body area and specific type of procedure did your clinician order?"
                ],
                "intake_facts": {
                    "requested_procedure": {
                        "value": "ultrasound scan",
                        "source": "care_journey_agent",
                        "verification_status": "inferred",
                    }
                },
            }
        ]
        model = FakePlanner(
            '{"intent":"continue_journey",'
            '"target_journey_id":"journey-ultrasound",'
            '"target_appointment_id":null,"steps":["continue_active_stage"],'
            '"reuse":[],"refresh":[],"missing":[]}'
        )
        plan = CareJourneyAgent(model).plan(
            "Abdominal ultrasound, complete.", context=context,
            active_journey_id="journey-ultrasound",
        )
        self.assertEqual(plan.intent, JourneyIntent.CONTINUE_JOURNEY)
        self.assertEqual(plan.target_journey_id, "journey-ultrasound")

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
