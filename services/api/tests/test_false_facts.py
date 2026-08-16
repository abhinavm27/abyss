"""Regression tests for two bugs that made VELA state false facts confidently.

Both were silent: the system produced a normal-looking answer, so neither an
exception nor an existing test caught them. They are guarded here because the
whole design claim is that the deterministic layer never asserts something it
cannot support.
"""

import unittest

from abyss.procedures import ProcedureCatalog
from app.api import _plan_comparison_reply


class ContrastAnswerScopeTests(unittest.TestCase):
    """A contrast answer must only disambiguate the catalog's own candidates.

    "without contrast" used to hardcode CPT 73721 (MRI knee) for *any* body
    part, and ProcedureCatalog.resolve short-circuits on a confirmed code
    before it ever reads the phrase — so a shoulder MRI resolved to
    "MRI knee without contrast" with confidence "confirmed", was recorded as a
    VERIFIED catalog fact, and was priced and booked as a knee MRI.
    """

    def test_knee_phrase_still_offers_both_contrast_variants(self):
        resolution = ProcedureCatalog().resolve("MRI knee")
        self.assertEqual(resolution.candidates, ("73721", "73722"))

    def test_other_body_parts_do_not_offer_the_knee_codes(self):
        # The gate in journey.onboard accepts a contrast-derived code only when
        # it is in these candidates, so an empty tuple is what stops the knee
        # code being forced onto an unrelated request.
        for phrase in ("MRI shoulder", "MRI of my brain", "abdominal ultrasound complete"):
            with self.subTest(phrase=phrase):
                self.assertNotIn("73721", ProcedureCatalog().resolve(phrase).candidates)
                self.assertNotIn("73722", ProcedureCatalog().resolve(phrase).candidates)

    def test_confirmed_code_still_short_circuits_for_a_real_knee_choice(self):
        resolution = ProcedureCatalog().resolve("MRI knee", confirmed_code="73722")
        self.assertEqual(resolution.code, "73722")
        self.assertFalse(resolution.needs_confirmation)


class IncompleteComparisonHonestyTests(unittest.TestCase):
    """An incomplete total must never be narrated as a confident recommendation.

    simulate_annual_scenario sets complete=False when a service's cost share
    could not be classified, and charges only the deductible — understating
    real exposure. Nothing read that flag, so a $3,200 unclassified visit was
    reported as $500 and used to rank plans and quote a dollar saving.
    """

    @staticmethod
    def _plan(label, total, complete):
        return {
            "plan_id": 1,
            "label": label,
            "scenarios": {"predicted": {"annual_total": total, "complete": complete}},
        }

    def test_incomplete_plan_is_named_and_no_total_is_asserted(self):
        reply = _plan_comparison_reply({
            "plans": [self._plan("Plan B - Gold", 7100.0, False)],
            "incomplete_plans": ["Plan B - Gold"],
            "recommendation": None,
        })
        self.assertIn("Plan B - Gold", reply)
        self.assertIn("Summary of Benefits", reply)
        # The misleading number must not appear anywhere in the spoken answer.
        self.assertNotIn("7,100", reply)
        self.assertNotIn("$", reply)

    def test_complete_comparison_still_states_the_recommendation(self):
        reply = _plan_comparison_reply({
            "plans": [self._plan("Plan A", 3299.38, True), self._plan("Plan B", 6899.38, True)],
            "incomplete_plans": [],
            "recommendation": {
                "recommended_label": "Plan A",
                "current_label": "Plan B",
                "estimated_annual_savings": {"predicted": 3600.0},
            },
        })
        self.assertIn("Plan A", reply)
        self.assertIn("3,600.00", reply)

    def test_complete_comparison_without_a_recommendation_states_the_cheapest(self):
        reply = _plan_comparison_reply({
            "plans": [self._plan("Plan A", 3299.38, True)],
            "incomplete_plans": [],
            "recommendation": None,
        })
        self.assertIn("3,299.38", reply)


if __name__ == "__main__":
    unittest.main()
