import unittest

from abyss.cost_engine import CarePath, rank_paths


class CostEngineTests(unittest.TestCase):
    def test_annual_total_has_visible_components(self):
        path = CarePath("wa-silver", "WA Silver", 300, 600, 240, 160)
        self.assertEqual(path.annual_premium, 3600)
        self.assertEqual(path.annual_total, 4600)

    def test_ineligible_cheaper_plan_is_not_recommended(self):
        blocked = CarePath("blocked", "Blocked", 10, 0, eligible=False)
        valid = CarePath("valid", "Valid", 300, 400)
        self.assertEqual(rank_paths([blocked, valid])[0].plan_id, "valid")

    def test_negative_cost_is_rejected(self):
        with self.assertRaises(ValueError):
            CarePath("bad", "Bad", -1, 0)


if __name__ == "__main__":
    unittest.main()
