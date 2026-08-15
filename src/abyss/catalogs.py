"""Deterministic, source-backed catalogs for the seeded demo."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PlanRecord:
    plan_id: str
    name: str
    monthly_premium: float
    expected_care_oop: float
    annual_medications: float
    deductible_exposure: float
    eligible: bool
    provider_ids: frozenset[str]
    facility_ids: frozenset[str]
    source: str = "seeded synthetic plan catalog"


@dataclass(frozen=True, slots=True)
class ProviderRecord:
    provider_id: str
    name: str
    facility_id: str
    source: str = "seeded synthetic provider catalog"
    verified: bool = True


@dataclass(frozen=True, slots=True)
class FacilityRecord:
    facility_id: str
    name: str
    procedure_code: str
    estimated_price: float
    source: str = "seeded synthetic Seattle hospital catalog"


class SeededCatalog:
    """Small truthful fixture catalog; unavailable records are not inferred."""

    def __init__(self) -> None:
        self.plans = {
            "continuation": PlanRecord(
                "continuation", "Continuation PPO", 600, 500, 700, 500, True,
                frozenset({"dr-lee"}), frozenset({"seattle-general"}),
            ),
            "wa-plan-a": PlanRecord(
                "wa-plan-a", "Washington Plan A", 350, 400, 650, 300, True,
                frozenset(), frozenset({"seattle-general"}),
            ),
            "wa-plan-b": PlanRecord(
                "wa-plan-b", "Washington Plan B", 400, 550, 650, 300, True,
                frozenset({"dr-lee"}), frozenset({"seattle-general"}),
            ),
        }
        self.providers = {"dr-lee": ProviderRecord("dr-lee", "Dr. Lee", "seattle-general")}
        self.facilities = {
            "seattle-general": FacilityRecord("seattle-general", "Seattle General", "73721", 550)
        }

    def plan(self, plan_id: str) -> PlanRecord:
        return self.plans[plan_id]

    def provider(self, provider_id: str) -> ProviderRecord:
        return self.providers[provider_id]

    def facility(self, facility_id: str) -> FacilityRecord:
        return self.facilities[facility_id]
