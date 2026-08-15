"""Permissioned state machine for the ABYSS golden path."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .domain import CareState, ConsentAction


class WorkflowStage(StrEnum):
    INTAKE = "intake"
    COMPARE = "compare"
    RECOMMEND = "recommend"
    ENROLL = "enroll"
    TRANSITION = "transition"
    VERIFY = "verify"
    BOOK = "book"
    COMPLETE = "complete"


class ConsentRequired(RuntimeError):
    pass


@dataclass(slots=True)
class AbyssWorkflow:
    care_state: CareState
    stage: WorkflowStage = WorkflowStage.INTAKE

    _next_stage = {
        WorkflowStage.INTAKE: WorkflowStage.COMPARE,
        WorkflowStage.COMPARE: WorkflowStage.RECOMMEND,
        WorkflowStage.RECOMMEND: WorkflowStage.ENROLL,
        WorkflowStage.ENROLL: WorkflowStage.TRANSITION,
        WorkflowStage.TRANSITION: WorkflowStage.VERIFY,
        WorkflowStage.VERIFY: WorkflowStage.BOOK,
        WorkflowStage.BOOK: WorkflowStage.COMPLETE,
    }

    _required_consent = {
        WorkflowStage.INTAKE: ConsentAction.PROCESS_DOCUMENTS,
        WorkflowStage.ENROLL: ConsentAction.ENROLL_PLAN,
        WorkflowStage.TRANSITION: ConsentAction.TRANSITION_COVERAGE,
        WorkflowStage.VERIFY: ConsentAction.SHARE_WITH_PROVIDER,
        WorkflowStage.BOOK: ConsentAction.BOOK_APPOINTMENT,
    }

    def advance(self) -> WorkflowStage:
        if self.stage == WorkflowStage.COMPLETE:
            raise RuntimeError("workflow is already complete")

        required = self._required_consent.get(self.stage)
        if required and not self.care_state.has_consent(required):
            raise ConsentRequired(f"{required.value} approval is required")

        self.stage = self._next_stage[self.stage]
        return self.stage

