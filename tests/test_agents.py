import json
from unittest import TestCase

from abyss.agents import (KnowledgeAgent, MatchingAgent, OnboardingAgent, ReviewAgent,
                          SchedulerAgent, VoiceInboxAgent)
from abyss.agent import AgentOutputError
from abyss.procedures import ProcedureCatalog


class FakeModel:
    def __init__(self, response: str):
        self.response = response
        self.calls = []

    def chat(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return self.response


class AgentRoleTests(TestCase):
    def test_onboarding_extracts_candidate_facts_only(self):
        model = FakeModel(json.dumps({"facts": [{"name": "procedure", "value": "73721", "confidence": 0.9}]}))
        proposal = OnboardingAgent(model).extract("knee MRI", source="synthetic-referral")
        self.assertEqual(proposal.facts[0].verification_status.value, "inferred")
        self.assertEqual(proposal.facts[0].consent_required.value, "process_documents")
        self.assertIn("service_date", proposal.missing)
        self.assertIn("What date do you expect to receive this care?", proposal.questions)

    def test_onboarding_rejects_model_authority_fields(self):
        model = FakeModel('{"facts":[{"name":"plan","value":"A","confidence":1,"decision":"choose"}]}')
        with self.assertRaises(AgentOutputError):
            OnboardingAgent(model).extract("plan A", source="synthetic-card")

    def test_matching_agent_only_returns_a_request(self):
        request = MatchingAgent().request_evaluation(["wa-plan-a", "wa-plan-b"], provider_id="dr-lee")
        self.assertEqual(request.plan_ids, ("wa-plan-a", "wa-plan-b"))
        self.assertFalse(hasattr(request, "recommended_plan"))

    def test_matching_reasoning_uses_engine_evidence_without_recommendation_authority(self):
        model = FakeModel("Plan B is feasible; Plan A fails the provider constraint.")
        from abyss.evaluation import PathEvaluation
        evaluations = [
            PathEvaluation("wa-plan-b", "Plan B", "dr-lee", "seattle-general", True, 6750, 4800),
            PathEvaluation("wa-plan-a", "Plan A", "dr-lee", "seattle-general", False, 6200, 4200,
                           ("preferred_provider_out_of_network",)),
        ]
        answer = MatchingAgent(model).reason_about_evaluation(evaluations, question="Explain the constraints")
        self.assertIn("Plan B", answer)
        prompt = model.calls[0][0][1]["content"]
        self.assertIn('"authority":"deterministic_engine"', prompt)

    def test_scheduler_only_proposes_scoped_booking(self):
        proposal = SchedulerAgent().propose(provider_id="dr-lee", facility_id="seattle-general", date="2026-09-04", time="10:30")
        self.assertEqual(proposal.consent_scope, "dr-lee / seattle-general / 2026-09-04 10:30")

    def test_voice_rejects_open_ended_or_unknown_intents(self):
        agent = VoiceInboxAgent()
        with self.assertRaises(AgentOutputError):
            agent.normalize(intent="book_appointment_now", text="book it")
        normalized = agent.normalize(intent="approve_action", text="yes, approve Plan B")
        self.assertEqual(normalized["intent"], "approve_action")

    def test_review_is_read_only_summary(self):
        result = ReviewAgent().summarize(stage="complete", events=[{"type": "receipt"}], receipts=[{"status": "sandbox_confirmed"}])
        self.assertEqual(result["receipt_count"], 1)
        self.assertNotIn("execute", result)

    def test_knowledge_agent_uses_engine_evidence(self):
        model = FakeModel("Plan B is the feasible lower-cost option.")
        from abyss.evaluation import PathEvaluation
        evaluations = [PathEvaluation("wa-plan-b", "Plan B", "dr-lee", "seattle-general", True, 6750, 4800)]
        answer = KnowledgeAgent(model).explain_result(evaluations, question="Which path is recommended?")
        self.assertIn("Plan B", answer)
        self.assertIn("authoritative JSON", model.calls[0][0][1]["content"])

    def test_procedure_catalog_requires_clarification_for_bare_knee_mri(self):
        result = ProcedureCatalog().resolve("I want an MRI scan for my knee")
        self.assertTrue(result.needs_confirmation)
        self.assertEqual(result.candidates, ("73721", "73722"))

    def test_procedure_catalog_resolves_cbc_with_differential(self):
        result = ProcedureCatalog().resolve("Complete blood count (CBC) with differential")
        self.assertEqual(result.code, "85025")
        self.assertEqual(result.canonical_name, "Complete blood count with differential")
        self.assertFalse(result.needs_confirmation)
