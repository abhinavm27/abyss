from unittest import TestCase

from abyss.domain import ConsentAction
from abyss.journey import CareJourney
from abyss.agents import KnowledgeAgent, OnboardingAgent
from abyss.domain import DecisionFact, VerificationStatus
from datetime import UTC, datetime
from abyss.workflow import WorkflowStage


class VerticalSliceTests(TestCase):
    def test_onboarding_agent_is_orchestrated_into_fact_ledger(self) -> None:
        class FakeModel:
            def chat(self, messages, **kwargs):
                return '{"facts":[{"name":"requested_procedure","value":"73721","confidence":0.95}]}'

        journey = CareJourney.open("journey-onboard", onboarding_agent=OnboardingAgent(FakeModel()))
        proposal = journey.onboard("MRI knee without contrast", source="synthetic-referral")
        self.assertEqual(proposal.facts[0].name, "requested_procedure")
        self.assertEqual(journey.workflow.care_state.facts["requested_procedure"].value, "73721")
        self.assertEqual(journey.memory.current("journey-onboard:synthetic-user", "requested_procedure").fact.value, "73721")
        self.assertIn("onboarding_completed", [event.event_type for event in journey.audit.for_journey("journey-onboard")])

    def test_ambiguous_knee_mri_does_not_enter_decision_as_a_code(self) -> None:
        class FakeModel:
            def chat(self, messages, **kwargs):
                return '{"facts":[{"name":"requested_procedure","value":"MRI knee","confidence":0.95}]}'

        journey = CareJourney.open("journey-procedure", onboarding_agent=OnboardingAgent(FakeModel()), knowledge_agent=KnowledgeAgent())
        journey.onboard("I want an MRI scan for my knee", source="user_request")
        self.assertIsNone(journey.procedure_resolution.code)
        self.assertIn("procedure_code_confirmation", journey.onboarding_missing)

    def test_onboarding_accumulates_facts_and_routes_confirmation_through_knowledge(self) -> None:
        class SequencedModel:
            def __init__(self):
                self.responses = iter([
                    '{"facts":[{"name":"requested_procedure","value":"MRI knee","confidence":0.95}]}',
                    '{"facts":[{"name":"service_date","value":"2026-09-04","confidence":0.95},'
                    '{"name":"coverage_end_date","value":"2026-08-31","confidence":0.95}]}',
                ])

            def chat(self, messages, **kwargs):
                return next(self.responses)

        class TrackingKnowledge(KnowledgeAgent):
            def __init__(self):
                self.confirmed_codes = []

            def propose_procedure(self, phrase, *, confirmed_code=None):
                self.confirmed_codes.append(confirmed_code)
                return super().propose_procedure(phrase, confirmed_code=confirmed_code)

        knowledge = TrackingKnowledge()
        journey = CareJourney.open(
            "journey-cumulative",
            onboarding_agent=OnboardingAgent(SequencedModel()),
            knowledge_agent=knowledge,
        )
        journey.onboard("I want an MRI scan for my knee", source="user_request")
        self.assertIn("procedure_code_confirmation", journey.onboarding_missing)
        journey.onboard(
            "Without contrast, on 2026-09-04; my coverage ends 2026-08-31",
            source="user_request",
        )
        self.assertEqual(journey.onboarding_missing, ())
        self.assertEqual(journey.workflow.care_state.facts["procedure_code"].value, "73721")
        self.assertEqual(knowledge.confirmed_codes[-1], "73721")

    def test_resolved_procedure_does_not_become_ambiguous_on_later_reply(self) -> None:
        class SequencedModel:
            def __init__(self):
                self.responses = iter([
                    '{"facts":[{"name":"requested_procedure","value":"MRI knee","confidence":0.95}]}',
                    '{"facts":[{"name":"coverage_end_date","value":"sept 30","confidence":0.95}]}',
                    '{"facts":[{"name":"service_date","value":"aug 30","confidence":0.95}]}',
                ])

            def chat(self, messages, **kwargs):
                return next(self.responses)

        journey = CareJourney.open(
            "journey-sticky-procedure",
            onboarding_agent=OnboardingAgent(SequencedModel()),
            knowledge_agent=KnowledgeAgent(),
        )
        journey.onboard("I want an MRI scan for my knee", source="user_request")
        journey.onboard("Coverage ends Sept 30. MRI with contrast", source="user_request")
        self.assertEqual(journey.workflow.care_state.facts["procedure_code"].value, "73722")
        journey.onboard("Aug 30", source="user_request")
        self.assertEqual(journey.onboarding_missing, ())
        self.assertEqual(journey.workflow.care_state.facts["procedure_code"].value, "73722")

    def test_seeded_comparison_rejects_out_of_network_plan(self) -> None:
        journey = CareJourney.open("journey-001")
        journey.record_consent(ConsentAction.PROCESS_DOCUMENTS, approved=True, scope="seeded documents")
        self.assertEqual(journey.advance(), WorkflowStage.COMPARE)
        evaluations = journey.compare(["continuation", "wa-plan-a", "wa-plan-b"])
        self.assertEqual(evaluations[0].plan_id, "wa-plan-b")
        rejected = next(item for item in evaluations if item.plan_id == "wa-plan-a")
        self.assertFalse(rejected.feasible)
        self.assertIn("preferred_provider_out_of_network", rejected.hard_failures)
        event_types = [event.event_type for event in journey.audit.for_journey("journey-001")]
        self.assertIn("matching_requested", event_types)
        self.assertIn("evaluation_completed", event_types)

    def test_action_requires_exact_consent(self) -> None:
        journey = CareJourney.open("journey-002")
        with self.assertRaises(RuntimeError):
            journey.execute(ConsentAction.ENROLL_PLAN, "wa-plan-b", "enroll-1")
        journey.record_consent(ConsentAction.PROCESS_DOCUMENTS, approved=True, scope="seeded documents")
        journey.advance()
        journey.advance()
        journey.advance()
        journey.record_consent(ConsentAction.ENROLL_PLAN, approved=True, scope="wa-plan-b")
        with self.assertRaises(RuntimeError):
            journey.execute(ConsentAction.ENROLL_PLAN, "wa-plan-a", "enroll-1")
        receipt = journey.execute(ConsentAction.ENROLL_PLAN, "wa-plan-b", "enroll-1")
        self.assertTrue(receipt.sandbox)
        self.assertEqual(receipt.status, "sandbox_confirmed")
        journey.execute(ConsentAction.ENROLL_PLAN, "wa-plan-b", "enroll-1")
        self.assertEqual(len(journey.receipts), 1)

    def test_fact_and_receipt_are_audited_and_actions_are_stage_bound(self) -> None:
        journey = CareJourney.open("journey-003")
        journey.record_fact(DecisionFact("procedure", "73721", "synthetic-referral", datetime.now(UTC), 1.0, VerificationStatus.SOURCE_BACKED))
        self.assertEqual(len(journey.audit.for_journey("journey-003")), 1)
        journey.record_consent(ConsentAction.ENROLL_PLAN, approved=True, scope="wa-plan-b")
        with self.assertRaises(RuntimeError):
            journey.execute(ConsentAction.ENROLL_PLAN, "wa-plan-b", "enroll-3")

    def test_complete_sandbox_path_requires_transition_prerequisites(self) -> None:
        journey = CareJourney.open("journey-004")
        journey.record_consent(ConsentAction.PROCESS_DOCUMENTS, approved=True, scope="seeded documents")
        journey.advance()  # compare
        journey.compare(["continuation", "wa-plan-a", "wa-plan-b"])
        journey.advance()  # recommend
        journey.advance()  # enroll
        journey.record_consent(ConsentAction.ENROLL_PLAN, approved=True, scope="wa-plan-b")
        journey.execute(ConsentAction.ENROLL_PLAN, "wa-plan-b", "enroll-4")
        journey.advance()  # transition
        journey.record_consent(ConsentAction.TRANSITION_COVERAGE, approved=True, scope="current to wa-plan-b")
        with self.assertRaises(RuntimeError):
            journey.execute(ConsentAction.TRANSITION_COVERAGE, "current to wa-plan-b", "transition-4")
        for name, value in (("new_effective_date", "2026-09-01"), ("first_premium_confirmed", True)):
            journey.record_fact(DecisionFact(name, value, "sandbox-enrollment-receipt", datetime.now(UTC), 1.0, VerificationStatus.VERIFIED))
        journey.execute(ConsentAction.TRANSITION_COVERAGE, "current to wa-plan-b", "transition-4")
        journey.advance()  # verify
        journey.record_consent(ConsentAction.SHARE_WITH_PROVIDER, approved=True, scope="dr-lee / seattle-general")
        journey.execute(ConsentAction.SHARE_WITH_PROVIDER, "dr-lee / seattle-general", "verify-4")
        journey.advance()  # book
        journey.record_consent(ConsentAction.BOOK_APPOINTMENT, approved=True, scope="dr-lee / 2026-09-04 10:30")
        journey.execute(ConsentAction.BOOK_APPOINTMENT, "dr-lee / 2026-09-04 10:30", "book-4")
        self.assertEqual(len(journey.receipts), 4)
