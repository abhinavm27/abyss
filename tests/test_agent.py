import json
import unittest
from datetime import UTC, datetime

from abyss.agent import AgentOutputError, explain, extract_facts


class FakeHermes:
    def __init__(self):
        self.messages = None

    def chat(self, messages, **kwargs):
        self.messages = messages
        return "The estimate is $612; it is not a guarantee."


class AgentTests(unittest.TestCase):
    def test_evidence_is_supplied_as_authoritative_json(self):
        client = FakeHermes()
        reply = explain("What will I pay?", {"expected": 612}, client=client)
        self.assertIn("$612", reply)
        prompt = client.messages[1]["content"]
        self.assertIn(json.dumps({"expected": 612}, separators=(",", ":")), prompt)
        self.assertIn("authoritative JSON", prompt)

    def test_extraction_returns_unverified_candidate_facts(self):
        class ExtractionHermes(FakeHermes):
            def chat(self, messages, **kwargs):
                return json.dumps({"facts": [{"name": "procedure", "value": "73721", "source": "referral", "confidence": 0.9}]})

        facts = extract_facts("MRI knee without contrast", source="referral", client=ExtractionHermes())
        self.assertEqual(facts[0].value, "73721")
        self.assertEqual(facts[0].verification_status.value, "inferred")
        self.assertEqual(facts[0].consent_required.value, "process_documents")

    def test_extraction_rejects_unknown_model_schema(self):
        class InvalidHermes(FakeHermes):
            def chat(self, messages, **kwargs):
                return '{"facts": [{"name": "x", "value": 1, "unsafe": true}]}'

        with self.assertRaises(AgentOutputError):
            extract_facts("synthetic", source="doc", client=InvalidHermes())

    def test_extraction_uses_orchestrator_provenance(self):
        class UntrustedProvenanceHermes(FakeHermes):
            def chat(self, messages, **kwargs):
                return json.dumps({"facts": [{
                    "name": "service_date", "value": "2026-09-04",
                    "source": "model-invented-source", "confidence": 1.0,
                    "observed_at": "not-a-timestamp",
                }]})

        observed = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
        fact = extract_facts(
            "Service date is 2026-09-04", source="user_request",
            observed_at=observed, client=UntrustedProvenanceHermes(),
        )[0]
        self.assertEqual(fact.source, "user_request")
        self.assertEqual(fact.observed_at, observed)

    def test_extraction_accepts_fenced_json_before_strict_validation(self):
        class FencedHermes(FakeHermes):
            def chat(self, messages, **kwargs):
                return 'Here is the extraction:\n```json\n{"facts":[{"name":"service_date","value":"2026-09-04","confidence":1.0}]}\n```'

        facts = extract_facts("Service date is 2026-09-04", source="user_request", client=FencedHermes())
        self.assertEqual(facts[0].name, "service_date")

    def test_extraction_normalizes_common_model_confidence_encodings(self):
        class LabeledConfidenceHermes(FakeHermes):
            def chat(self, messages, **kwargs):
                return json.dumps({"facts": [
                    {"name": "requested_procedure", "value": "CBC with differential", "confidence": "high"},
                    {"name": "service_date", "value": "2026-08-30", "confidence": "95%"},
                ]})

        facts = extract_facts(
            "CBC with differential on 2026-08-30",
            source="user_request",
            client=LabeledConfidenceHermes(),
        )
        by_name = {fact.name: fact.confidence for fact in facts}
        self.assertEqual(by_name["requested_procedure"], 0.9)
        self.assertEqual(by_name["service_date"], 0.95)

    def test_extraction_recovers_only_explicit_seeded_facts_from_bad_model_output(self):
        class BrokenHermes(FakeHermes):
            def chat(self, messages, **kwargs):
                return "I could not produce JSON."

        facts = extract_facts(
            "MRI knee without contrast. Service date is 2026-09-04 and coverage ends 2026-08-31.",
            source="user_request",
            client=BrokenHermes(),
        )
        by_name = {fact.name: fact for fact in facts}
        self.assertEqual(by_name["requested_procedure"].value, "MRI knee without contrast")
        self.assertEqual(by_name["service_date"].value, "2026-09-04")
        self.assertEqual(by_name["coverage_end_date"].value, "2026-08-31")
        self.assertEqual(by_name["requested_procedure"].verification_status.value, "source_backed")

    def test_extraction_supplements_model_with_explicit_natural_dates(self):
        class PartialHermes(FakeHermes):
            def chat(self, messages, **kwargs):
                return '{"facts":[{"name":"contrast_status","value":"with contrast","confidence":1.0}]}'

        facts = extract_facts(
            "Aug 30, coverage ends Sept 30. MRI with contrast",
            source="user_request",
            client=PartialHermes(),
        )
        by_name = {fact.name: fact.value for fact in facts}
        self.assertEqual(by_name["service_date"], "aug 30")
        self.assertEqual(by_name["coverage_end_date"], "sept 30")

    def test_extraction_retries_once_with_schema_feedback(self):
        class CorrectingHermes(FakeHermes):
            def __init__(self):
                super().__init__()
                self.calls = 0

            def chat(self, messages, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    return "I need to think about that."
                self.messages = messages
                return json.dumps({"facts": [{
                    "name": "requested_procedure",
                    "value": "complete abdominal ultrasound",
                    "source": "user_request",
                    "confidence": 0.9,
                    "observed_at": "2026-08-15T12:00:00Z",
                }]})

        client = CorrectingHermes()
        facts = extract_facts(
            "complete abdominal ultrasound",
            source="user_request",
            client=client,
        )
        self.assertEqual(client.calls, 2)
        self.assertEqual(facts[0].value, "complete abdominal ultrasound")
        self.assertIn("required schema", client.messages[-1]["content"])


if __name__ == "__main__":
    unittest.main()
