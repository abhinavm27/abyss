from datetime import UTC, datetime
from unittest import TestCase

from abyss.domain import (
    CareState,
    ConsentAction,
    DecisionFact,
    VerificationStatus,
)


class DecisionFactTests(TestCase):
    def test_fact_requires_bounded_confidence(self) -> None:
        with self.assertRaises(ValueError):
            DecisionFact(
                name="deductible",
                value=1000,
                source="seeded plan document",
                observed_at=datetime.now(UTC),
                confidence=1.1,
                verification_status=VerificationStatus.SOURCE_BACKED,
            )


class CareStateTests(TestCase):
    def test_latest_consent_record_controls_action(self) -> None:
        state = CareState(session_id="demo")
        state.record_consent(
            ConsentAction.BOOK_APPOINTMENT,
            approved=True,
            actor="synthetic-user",
            scope="MRI at seeded facility",
        )
        state.record_consent(
            ConsentAction.BOOK_APPOINTMENT,
            approved=False,
            actor="synthetic-user",
            scope="MRI at seeded facility",
        )
        self.assertFalse(state.has_consent(ConsentAction.BOOK_APPOINTMENT))

