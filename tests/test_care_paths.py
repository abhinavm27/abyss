import unittest

from abyss.care_paths import (
    build_alternative_scenario,
    build_hospital_options,
    member_cost_scenario,
)
from abyss.catalogs import SeededCatalog
from abyss.knowledge import PublishedHospitalRate


def rate(hospital_id: int, hospital: str, typical: float) -> PublishedHospitalRate:
    return PublishedHospitalRate(
        hospital_id, hospital, "Seattle", "MRI knee", "73721", "HCPCS", 1,
        typical, typical, typical, "https://example.test/mrf",
        "https://example.test/source", "2026-04-01", "2026-08-15T12:00:00+00:00",
    )


class CarePathScenarioTests(unittest.TestCase):
    def test_member_cost_uses_seeded_deductible_and_coinsurance(self) -> None:
        plan = SeededCatalog().plan("continuation")
        self.assertEqual(member_cost_scenario(plan, 531.25), 506.25)

    def test_current_options_rank_hospitals_by_member_scenario(self) -> None:
        plan = SeededCatalog().plan("continuation")
        options = build_hospital_options(
            plan,
            [rate(2, "Hospital B", 1000), rate(1, "Hospital A", 500)],
            coverage_status="current",
        )
        self.assertEqual([item.hospital for item in options], ["Hospital A", "Hospital B"])
        self.assertEqual(options[0].network_status, "pending_verification")
        self.assertEqual(options[0].estimate_status, "scenario_not_guarantee")

    def test_alternative_is_separate_exploration_scenario(self) -> None:
        plan = SeededCatalog().plan("wa-plan-b")
        scenario = build_alternative_scenario(plan, [rate(1, "Hospital A", 500)], 8500)
        self.assertIsNotNone(scenario)
        self.assertTrue(scenario.requires_plan_switch)
        self.assertEqual(scenario.action_status, "exploration_only")
        self.assertGreater(scenario.estimated_annual_savings, 0)


if __name__ == "__main__":
    unittest.main()
