from unittest import TestCase

from abyss.domain import CareState, ConsentAction
from abyss.workflow import AbyssWorkflow, ConsentRequired, WorkflowStage


class WorkflowTests(TestCase):
    def test_current_coverage_path_skips_enrollment_and_transition(self) -> None:
        workflow = AbyssWorkflow(CareState("session-current"), WorkflowStage.RECOMMEND)
        self.assertEqual(workflow.continue_current_coverage(), WorkflowStage.VERIFY)

    def test_intake_requires_document_consent(self) -> None:
        workflow = AbyssWorkflow(CareState(session_id="demo"))
        with self.assertRaises(ConsentRequired):
            workflow.advance()

    def test_separate_enrollment_and_transition_approvals(self) -> None:
        state = CareState(session_id="demo")
        state.record_consent(
            ConsentAction.PROCESS_DOCUMENTS,
            approved=True,
            actor="synthetic-user",
            scope="seeded card and referral",
        )
        workflow = AbyssWorkflow(state)
        self.assertEqual(workflow.advance(), WorkflowStage.COMPARE)
        self.assertEqual(workflow.advance(), WorkflowStage.RECOMMEND)
        self.assertEqual(workflow.advance(), WorkflowStage.ENROLL)

        state.record_consent(
            ConsentAction.ENROLL_PLAN,
            approved=True,
            actor="synthetic-user",
            scope="sandbox plan enrollment",
        )
        self.assertEqual(workflow.advance(), WorkflowStage.TRANSITION)

        with self.assertRaises(ConsentRequired):
            workflow.advance()
