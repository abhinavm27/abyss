import unittest

from app.api import _extract_state_from_text, _plan_search_reply, _sample_plan_search_result


class ExtractStateFromTextTests(unittest.TestCase):
    def test_full_state_name_is_matched(self):
        self.assertEqual(_extract_state_from_text("find me insurance plans in Texas"), "TX")

    def test_capitalized_abbreviation_is_matched(self):
        self.assertEqual(_extract_state_from_text("find plans in TX"), "TX")

    def test_common_english_words_are_not_mistaken_for_state_abbreviations(self):
        # Regression: "me"/"in"/"or"/"hi" collide with real state abbreviations
        # (ME, IN, OR, HI) when matched case-insensitively. A lowercase,
        # ordinary sentence must never resolve to a state.
        for text in (
            "can you show me some insurance plans?",
            "what insurance plans are available?",
            "hi, can you help me find a plan",
        ):
            self.assertIsNone(_extract_state_from_text(text), text)

    def test_lowercase_abbreviation_is_not_matched(self):
        # Deliberately conservative: only a capitalized abbreviation counts as
        # the member naming a state, matching the "never invent" principle.
        self.assertIsNone(_extract_state_from_text("find plans in tx"))

    def test_no_state_mentioned_returns_none(self):
        self.assertIsNone(_extract_state_from_text("find me insurance plans"))


class PlanSearchReplyTests(unittest.TestCase):
    def test_sample_catalog_is_labeled_as_sample_not_real(self):
        result = _sample_plan_search_result()
        reply = _plan_search_reply(result, sample=True)
        self.assertIn("sample", reply.lower())
        self.assertIn("Washington Plan A", reply)

    def test_empty_result_states_no_data_rather_than_inventing_a_plan(self):
        reply = _plan_search_reply({"state": "MA", "count": 0, "plans": []})
        self.assertIn("MA", reply)
        self.assertNotIn("$", reply)


if __name__ == "__main__":
    unittest.main()
