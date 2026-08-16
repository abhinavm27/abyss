import unittest

from app.estimator import Plan, ServiceCostShare
from app.plan_comparison import (
    EVENT_BUNDLES,
    PricedService,
    simulate_annual_scenario,
    worst_case_scenario,
)


class SimulateAnnualScenarioTests(unittest.TestCase):
    def test_deductible_carries_across_services_in_one_scenario(self):
        # $1,000 deductible, 20% coinsurance after. Two $600 services in the
        # same year must not each get a fresh $1,000 deductible.
        plan = Plan(deductible=1000, coinsurance_pct=0.20, oop_max=5000)
        cs = ServiceCostShare(kind="coinsurance", amount=0.20, after_deductible=True)
        services = [
            PricedService("73721", "MRI knee", "Fred Hutchinson", 600.0, cs, "applied"),
            PricedService("73721", "MRI knee", "Overlake", 600.0, cs, "applied"),
        ]
        scenario = simulate_annual_scenario("predicted", plan, 3600, services)

        # First service: all $600 goes to deductible (still under $1,000).
        self.assertEqual(scenario.line_items[0].member_cost, 600.0)
        # Second service: $400 finishes the deductible, then 20% of the
        # remaining $200 = $40. Total $440, not another $600.
        self.assertEqual(scenario.line_items[1].member_cost, 440.0)
        self.assertEqual(scenario.care_cost, 1040.0)
        self.assertEqual(scenario.annual_premium, 3600.0)
        self.assertEqual(scenario.annual_total, 4640.0)
        self.assertTrue(scenario.complete)

    def test_unpriced_service_is_reported_not_guessed(self):
        plan = Plan(deductible=500, coinsurance_pct=0.2, oop_max=3000)
        services = [PricedService("99999", "Unknown", None, None, None, "unpriced")]
        scenario = simulate_annual_scenario("predicted", plan, 0, services)
        self.assertIsNone(scenario.line_items[0].member_cost)
        self.assertEqual(scenario.care_cost, 0.0)
        self.assertFalse(scenario.complete)

    def test_uncovered_service_marks_scenario_incomplete(self):
        plan = Plan(deductible=500, coinsurance_pct=0.2, oop_max=3000)
        services = [PricedService("73721", "MRI knee", "Fred Hutchinson", 600.0, None, "uncovered")]
        scenario = simulate_annual_scenario("predicted", plan, 0, services)
        self.assertFalse(scenario.complete)


class WorstCaseScenarioTests(unittest.TestCase):
    def test_worst_case_is_premium_plus_remaining_oop(self):
        plan = Plan(deductible=1000, coinsurance_pct=0.2, oop_max=5000, oop_met=1000)
        scenario = worst_case_scenario(plan, 3600)
        self.assertEqual(scenario.care_cost, 4000.0)  # 5000 - 1000 already met
        self.assertEqual(scenario.annual_total, 7600.0)
        self.assertTrue(scenario.complete)

    def test_no_oop_max_is_incomplete_not_zero(self):
        plan = Plan(deductible=1000, coinsurance_pct=0.2)
        scenario = worst_case_scenario(plan, 3600)
        self.assertFalse(scenario.complete)
        self.assertEqual(scenario.care_cost, 0.0)


class EventBundlesTests(unittest.TestCase):
    def test_bundles_reference_real_catalog_codes_not_placeholders(self):
        # Guards against a future edit swapping in an invented code — every
        # bundle code must be a real CPT/HCPCS code, not a fixture id.
        for name, codes in EVENT_BUNDLES.items():
            self.assertTrue(codes, name)
            for code, code_type in codes:
                self.assertRegex(code, r"^\d{4,5}$", f"{name}: {code}")
                self.assertEqual(code_type, "HCPCS")


if __name__ == "__main__":
    unittest.main()
