"""Deterministic plan/provider evaluation; models never participate in ranking."""

from __future__ import annotations

from dataclasses import dataclass

from .catalogs import PlanRecord, ProviderRecord


@dataclass(frozen=True, slots=True)
class PathEvaluation:
    plan_id: str
    plan_name: str
    provider_id: str
    facility_id: str
    feasible: bool
    annual_total: float
    annual_premium: float
    hard_failures: tuple[str, ...] = ()


def evaluate(plan: PlanRecord, provider: ProviderRecord) -> PathEvaluation:
    failures: list[str] = []
    if not plan.eligible:
        failures.append("plan_not_eligible")
    if provider.provider_id not in plan.provider_ids:
        failures.append("preferred_provider_out_of_network")
    if provider.facility_id not in plan.facility_ids:
        failures.append("preferred_facility_out_of_network")
    premium = round(plan.monthly_premium * 12, 2)
    total = round(premium + plan.expected_care_oop + plan.annual_medications + plan.deductible_exposure, 2)
    return PathEvaluation(plan.plan_id, plan.name, provider.provider_id, provider.facility_id,
                          not failures, total, premium, tuple(failures))


def rank(evaluations: list[PathEvaluation]) -> list[PathEvaluation]:
    return sorted(evaluations, key=lambda item: (not item.feasible, item.annual_total, item.plan_name))
