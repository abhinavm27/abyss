"""Annual cost-scenario comparison across a member's plans — the EMME product.

EMME's core deliverable is a personalised analysis: here are your best plan
options, here is what each will cost across a range of outcomes, here is why.
This module is the deterministic engine behind that: three usage scenarios
(predicted, possible, worst case), applied against a plan's real cost-sharing
terms and real published hospital rates, with a running deductible/OOP balance
across the whole plan year — not three independent single-service estimates.

Nothing here invents a price. A service with no published rate in the
knowledge catalog is reported as unpriced rather than guessed at, matching the
"at least $X" pattern the single-service estimator already uses.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .estimator import Plan, ServiceCostShare, patient_responsibility

# Real, catalog-verifiable procedure bundles for EMME's "possible" scenario —
# predicted usage plus one unplanned injury. Codes were checked against the
# Seattle knowledge catalog and are not a guess at what commonly gets billed
# for these events; see docs/DEMO_TRUTH.md for the verification note.
EVENT_BUNDLES: dict[str, list[tuple[str, str]]] = {
    "broken_arm": [
        ("99284", "HCPCS"),  # ER visit, moderate complexity
        ("73090", "HCPCS"),  # forearm x-ray
        ("25600", "HCPCS"),  # closed treatment, distal radius fracture
        ("29075", "HCPCS"),  # short arm cast application
    ],
    "concussion": [
        ("99282", "HCPCS"),  # ER visit, straightforward complexity
        ("70450", "HCPCS"),  # CT head/brain without contrast
    ],
}


@dataclass(frozen=True, slots=True)
class ScenarioLineItem:
    """One priced service within an annual scenario."""

    code: str
    description: str | None
    hospital: str | None
    allowed_amount: float | None  # None when no hospital published a rate
    member_cost: float | None
    cost_share_status: str  # applied | no_plan | unclassified | uncovered | unpriced
    breakdown: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "description": self.description,
            "hospital": self.hospital,
            "allowed_amount": self.allowed_amount,
            "member_cost": self.member_cost,
            "cost_share_status": self.cost_share_status,
            "breakdown": self.breakdown,
        }


@dataclass(frozen=True, slots=True)
class AnnualScenario:
    """One year's expected spend under one usage assumption."""

    name: str  # predicted | possible | worst_case
    annual_premium: float
    care_cost: float
    line_items: list[ScenarioLineItem]
    complete: bool  # False if any line item's cost share is unclassified/uncovered/unpriced

    @property
    def annual_total(self) -> float:
        return round(self.annual_premium + self.care_cost, 2)

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "annual_premium": self.annual_premium,
            "care_cost": self.care_cost,
            "annual_total": self.annual_total,
            "complete": self.complete,
            "line_items": [item.as_dict() for item in self.line_items],
        }


@dataclass(frozen=True, slots=True)
class PricedService:
    """A service resolved against the knowledge catalog, ready to run through a plan."""

    code: str
    description: str | None
    hospital: str | None
    allowed_amount: float | None
    cost_share: ServiceCostShare | None
    cost_share_status: str


def _apply_running(
    plan_state: Plan, service: PricedService
) -> tuple[Plan, ScenarioLineItem]:
    """Run one service through the plan's current deductible/OOP balance.

    Returns the *updated* plan state (deductible_met/oop_met advanced by what
    this service charged) alongside the line item, so the next service in the
    scenario sees an accurate remaining balance — three services against the
    same $2,000 deductible are not three independent $2,000 deductibles.
    """
    if service.allowed_amount is None:
        return plan_state, ScenarioLineItem(
            code=service.code, description=service.description, hospital=service.hospital,
            allowed_amount=None, member_cost=None, cost_share_status="unpriced",
        )

    charged, breakdown = patient_responsibility(
        service.allowed_amount, plan_state, service.cost_share
    )
    next_state = Plan(
        deductible=plan_state.deductible,
        deductible_met=min(plan_state.deductible, plan_state.deductible_met
                            + sum(b["amount"] for b in breakdown if b["label"] == "Deductible")),
        coinsurance_pct=plan_state.coinsurance_pct,
        oop_max=plan_state.oop_max,
        oop_met=(plan_state.oop_met + charged) if plan_state.oop_max > 0
                else plan_state.oop_met,
        copay=plan_state.copay,
        payer_name=plan_state.payer_name,
        label=plan_state.label,
    )
    line_item = ScenarioLineItem(
        code=service.code, description=service.description, hospital=service.hospital,
        allowed_amount=service.allowed_amount, member_cost=charged,
        cost_share_status=service.cost_share_status, breakdown=breakdown,
    )
    return next_state, line_item


def simulate_annual_scenario(
    name: str, plan: Plan, annual_premium: float, services: list[PricedService],
) -> AnnualScenario:
    """Run a sequence of services through one plan year, in order.

    `plan` should carry the member's deductible/OOP *already met* going into
    this scenario (0 for a fresh plan year, or their actual year-to-date spend
    if they are mid-year). Each service advances the running balance for the
    next.
    """
    state = plan
    line_items: list[ScenarioLineItem] = []
    care_cost = 0.0
    complete = True
    for service in services:
        state, item = _apply_running(state, service)
        line_items.append(item)
        if item.member_cost is not None:
            care_cost += item.member_cost
        if item.cost_share_status in ("unclassified", "uncovered", "unpriced"):
            complete = False
    return AnnualScenario(
        name=name, annual_premium=round(annual_premium, 2), care_cost=round(care_cost, 2),
        line_items=line_items, complete=complete,
    )


def worst_case_scenario(plan: Plan, annual_premium: float) -> AnnualScenario:
    """EMME's worst case: something unexpected happens and the member hits OOP max.

    Not itemised — the whole point of an out-of-pocket maximum is that the
    member owes no more than it, regardless of which services got them there.
    Reported incomplete when the plan has no OOP max configured, since there is
    then no real ceiling to report.
    """
    if plan.oop_max <= 0:
        return AnnualScenario(
            name="worst_case", annual_premium=round(annual_premium, 2), care_cost=0.0,
            line_items=[], complete=False,
        )
    remaining = max(0.0, plan.oop_max - plan.oop_met)
    return AnnualScenario(
        name="worst_case", annual_premium=round(annual_premium, 2),
        care_cost=round(remaining, 2), line_items=[], complete=True,
    )
