import unittest

from abyss.voice_proactive import proactive_voice_prompt


class ProactiveVoicePromptTests(unittest.TestCase):
    def test_new_session_invites_a_request(self) -> None:
        self.assertIn("Tell me what care you need", proactive_voice_prompt(None))

    def test_intake_asks_only_the_persisted_clarification(self) -> None:
        prompt = proactive_voice_prompt({
            "stage": "intake",
            "procedure_resolution": {"canonical_name": "abdominal ultrasound"},
            "onboarding_questions": ["What date do you expect to receive this care?"],
        })
        self.assertIn("abdominal ultrasound", prompt)
        self.assertIn("What date", prompt)

    def test_complete_journey_offers_review_or_reschedule(self) -> None:
        prompt = proactive_voice_prompt({
            "stage": "complete",
            "facts": [{"name": "requested_procedure", "value": "knee MRI"}],
        })
        self.assertIn("confirmed", prompt)
        self.assertIn("reschedule", prompt)


if __name__ == "__main__":
    unittest.main()
