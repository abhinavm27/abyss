"""Deterministic annual-cost comparison for ABYSS care paths."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class CarePath:
    plan_id: str
    plan_name: str
    monthly_premium: float
    expected_care_oop: float
    annual_medications: float = 0
    remaining_deductible_exposure: float = 0
    eligible: bool = True
    provider_in_network: bool = True

    def __post_init__(self) -> None:
        amounts = (
            self.monthly_premium,
            self.expected_care_oop,
            self.annual_medications,
            self.remaining_deductible_exposure,
        )
        if any(value < 0 for value in amounts):
            raise ValueError("cost components cannot be negative")

    @property
    def annual_premium(self) -> float:
        return round(self.monthly_premium * 12, 2)

    @property
    def annual_total(self) -> float:
        return round(
            self.annual_premium
            + self.expected_care_oop
            + self.annual_medications
            + self.remaining_deductible_exposure,
            2,
        )

    def as_dict(self) -> dict:
        return {
            **asdict(self),
            "annual_premium": self.annual_premium,
            "annual_total": self.annual_total,
        }


def rank_paths(paths: list[CarePath]) -> list[CarePath]:
    """Rank feasible paths by total; never recommend an ineligible path."""
    return sorted(
        paths,
        key=lambda path: (
            not (path.eligible and path.provider_in_network),
            path.annual_total,
            path.plan_name,
        ),
    )
