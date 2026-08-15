"""Deterministic plan-and-hospital care path scenarios.

The hospital's typical published negotiated rate is used as a scenario input.
It is not asserted to be this plan's contracted allowed amount. Network status
must be verified before any provider sharing or booking action.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from .catalogs import PlanRecord
from .knowledge import PublishedHospitalRate


@dataclass(frozen=True, slots=True)
class HospitalCareOption:
    plan_id: str
    plan_name: str
    coverage_status: str
    hospital_id: int
    hospital: str
    address: str | None
    procedure_code: str
    published_typical_rate: float
    published_low_rate: float
    published_high_rate: float
    estimated_member_cost: float
    estimated_annual_total: float
    deductible_remaining: float
    coinsurance_rate: float
    network_status: str
    estimate_status: str
    source_page_url: str | None
    rate_published_at: str | None

    def as_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "plan_name": self.plan_name,
            "coverage_status": self.coverage_status,
            "hospital_id": self.hospital_id,
            "hospital": self.hospital,
            "address": self.address,
            "procedure_code": self.procedure_code,
            "published_typical_rate": self.published_typical_rate,
            "published_low_rate": self.published_low_rate,
            "published_high_rate": self.published_high_rate,
            "estimated_member_cost": self.estimated_member_cost,
            "estimated_annual_total": self.estimated_annual_total,
            "deductible_remaining": self.deductible_remaining,
            "coinsurance_rate": self.coinsurance_rate,
            "network_status": self.network_status,
            "estimate_status": self.estimate_status,
            "source_page_url": self.source_page_url,
            "rate_published_at": self.rate_published_at,
        }


@dataclass(frozen=True, slots=True)
class AlternativePlanScenario:
    plan_id: str
    plan_name: str
    hospital_id: int
    hospital: str
    estimated_member_cost: float
    estimated_annual_total: float
    estimated_annual_savings: float
    requires_plan_switch: bool = True
    action_status: str = "exploration_only"

    def as_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "plan_name": self.plan_name,
            "hospital_id": self.hospital_id,
            "hospital": self.hospital,
            "estimated_member_cost": self.estimated_member_cost,
            "estimated_annual_total": self.estimated_annual_total,
            "estimated_annual_savings": self.estimated_annual_savings,
            "requires_plan_switch": self.requires_plan_switch,
            "action_status": self.action_status,
        }


@dataclass(frozen=True, slots=True)
class CarePathSelection:
    plan_id: str
    plan_name: str
    coverage_status: str
    hospital_id: int
    hospital: str
    procedure_code: str
    published_typical_rate: float
    estimated_member_cost: float
    network_status: str
    selected_at: str
    booking_consent: bool = False

    @classmethod
    def from_option(cls, option: HospitalCareOption) -> CarePathSelection:
        return cls(
            plan_id=option.plan_id,
            plan_name=option.plan_name,
            coverage_status=option.coverage_status,
            hospital_id=option.hospital_id,
            hospital=option.hospital,
            procedure_code=option.procedure_code,
            published_typical_rate=option.published_typical_rate,
            estimated_member_cost=option.estimated_member_cost,
            network_status=option.network_status,
            selected_at=datetime.now(UTC).isoformat(),
        )

    def as_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "plan_name": self.plan_name,
            "coverage_status": self.coverage_status,
            "hospital_id": self.hospital_id,
            "hospital": self.hospital,
            "procedure_code": self.procedure_code,
            "published_typical_rate": self.published_typical_rate,
            "estimated_member_cost": self.estimated_member_cost,
            "network_status": self.network_status,
            "selected_at": self.selected_at,
            "booking_consent": self.booking_consent,
        }


def member_cost_scenario(plan: PlanRecord, published_rate: float) -> float:
    """Apply seeded benefit terms to a published-rate scenario."""
    deductible = min(published_rate, plan.deductible_remaining)
    after_deductible = max(0.0, published_rate - deductible)
    return round(deductible + after_deductible * plan.coinsurance_rate, 2)


def build_hospital_options(
    plan: PlanRecord,
    rates: list[PublishedHospitalRate],
    *,
    coverage_status: str,
) -> list[HospitalCareOption]:
    options = []
    annual_premium = plan.monthly_premium * 12
    for rate in rates:
        member_cost = member_cost_scenario(plan, rate.typical)
        options.append(HospitalCareOption(
            plan_id=plan.plan_id,
            plan_name=plan.name,
            coverage_status=coverage_status,
            hospital_id=rate.hospital_id,
            hospital=rate.hospital,
            address=rate.address,
            procedure_code=rate.procedure_code,
            published_typical_rate=rate.typical,
            published_low_rate=rate.low,
            published_high_rate=rate.high,
            estimated_member_cost=member_cost,
            estimated_annual_total=round(annual_premium + plan.annual_medications + member_cost, 2),
            deductible_remaining=plan.deductible_remaining,
            coinsurance_rate=plan.coinsurance_rate,
            network_status="pending_verification",
            estimate_status="scenario_not_guarantee",
            source_page_url=rate.source_page_url,
            rate_published_at=rate.published_at,
        ))
    return sorted(options, key=lambda item: (item.estimated_member_cost, item.hospital))


def build_alternative_scenario(
    plan: PlanRecord,
    rates: list[PublishedHospitalRate],
    current_best_annual_total: float,
) -> AlternativePlanScenario | None:
    options = build_hospital_options(plan, rates, coverage_status="alternative")
    if not options:
        return None
    best = options[0]
    return AlternativePlanScenario(
        plan_id=plan.plan_id,
        plan_name=plan.name,
        hospital_id=best.hospital_id,
        hospital=best.hospital,
        estimated_member_cost=best.estimated_member_cost,
        estimated_annual_total=best.estimated_annual_total,
        estimated_annual_savings=round(
            max(0.0, current_best_annual_total - best.estimated_annual_total), 2
        ),
    )
