"""Patient-responsibility math.

Pure functions, no I/O, no database. This is the piece that has to be right:
everything else in ABYSS is plumbing around the number this file produces.

The model is the standard US commercial benefit sequence:

    allowed amount            the negotiated rate (what the plan recognises)
      -> deductible           patient pays 100% until the deductible is met
      -> coinsurance          patient pays a percentage of the remainder
      -> out-of-pocket max    patient pays nothing beyond this in the plan year

A copay plan short-circuits the first two steps: the patient pays a flat fee,
still capped by the out-of-pocket maximum.
"""

from __future__ import annotations

from dataclasses import dataclass, field


def _round(x: float) -> float:
    return round(x + 1e-9, 2)


@dataclass(frozen=True)
class ServiceCostShare:
    """How the plan charges for one specific service category.

    Real plans do not have a single coinsurance rate. The same plan may charge a
    $30 copay for a primary-care visit from day one and 25% coinsurance for an
    MRI only after a $2,000 deductible. Applying one blended percentage to both
    is wrong in opposite directions.

    Populated from the CMS Benefits and Cost Sharing PUF; see
    `app.ingest.qhp.parse_cost_share`.
    """

    kind: str  # copay | coinsurance | no_charge | not_covered
    amount: float = 0.0  # dollars for copay, fraction for coinsurance
    after_deductible: bool = False
    category: str | None = None


@dataclass(frozen=True)
class Plan:
    """A user's benefit design. All amounts in dollars, for the current plan year."""

    deductible: float = 0.0
    deductible_met: float = 0.0
    coinsurance_pct: float = 0.0  # 0.2 == patient pays 20% after deductible
    oop_max: float = 0.0
    oop_met: float = 0.0
    copay: float | None = None  # when set, replaces deductible+coinsurance
    payer_name: str | None = None
    label: str | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.coinsurance_pct <= 1.0:
            raise ValueError("coinsurance_pct must be a fraction between 0 and 1")
        for name in ("deductible", "deductible_met", "oop_max", "oop_met"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} cannot be negative")
        if self.copay is not None and self.copay < 0:
            raise ValueError("copay cannot be negative")

    @property
    def remaining_deductible(self) -> float:
        return max(0.0, self.deductible - self.deductible_met)

    @property
    def remaining_oop(self) -> float:
        """Dollars the patient can still be charged this year.

        An oop_max of 0 means "not configured", not "everything is free" — the
        difference matters, so it is treated as no cap rather than a zero cap.
        """
        if self.oop_max <= 0:
            return float("inf")
        return max(0.0, self.oop_max - self.oop_met)


@dataclass
class Estimate:
    """What the patient can expect to owe, and why."""

    expected: float
    low: float
    high: float
    allowed: float
    breakdown: list[dict] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    # False when the plan is linked but has no rule covering this service, so
    # the figure is only the part that can be proven — a floor, not a forecast.
    # The interface says "at least" rather than showing it as the answer.
    complete: bool = True

    def as_dict(self) -> dict:
        return {
            "expected": self.expected,
            "low": self.low,
            "high": self.high,
            "allowed": self.allowed,
            "breakdown": self.breakdown,
            "caveats": self.caveats,
            "complete": self.complete,
        }


# Attached to every estimate. These are not disclaimers for their own sake —
# each one is a real, common reason a final bill differs from this number.
BASE_CAVEATS = [
    "Facility fees may be billed separately from this charge.",
    "The physician's professional fee is usually billed separately from the facility charge.",
    "This is an estimate from the hospital's published data, not a guarantee of coverage.",
]


def _by_cost_share(
    allowed: float, plan: Plan, cs: ServiceCostShare
) -> tuple[float, list[dict], bool]:
    """Apply one service category's real cost-sharing rule.

    Returns (charged, breakdown, counts_toward_oop). A non-covered service is
    billed in full to the member and does **not** count toward the out-of-pocket
    maximum — that is exactly the case where people are blindsided, so it must
    not be silently capped.
    """
    breakdown: list[dict] = []

    if cs.kind == "not_covered":
        breakdown.append({
            "label": "Not covered",
            "amount": _round(allowed),
            "detail": "Your plan does not cover this service, so you pay the full amount "
                      "and it does not count toward your out-of-pocket maximum.",
        })
        return _round(allowed), breakdown, False

    if cs.kind == "no_charge" and not cs.after_deductible:
        breakdown.append({"label": "Covered in full", "amount": 0.0,
                          "detail": "Your plan covers this at no cost to you."})
        return 0.0, breakdown, True

    toward_deductible = 0.0
    if cs.after_deductible:
        toward_deductible = min(allowed, plan.remaining_deductible)
        if toward_deductible > 0:
            breakdown.append({
                "label": "Deductible",
                "amount": _round(toward_deductible),
                "detail": f"${plan.remaining_deductible:,.2f} of your deductible is unmet, "
                          f"and this service is charged after the deductible",
            })

    remainder = allowed - toward_deductible
    charged = toward_deductible

    if cs.kind == "copay":
        # A copay applies once the deductible is satisfied (or immediately, when
        # the plan does not gate it). It never exceeds the allowed amount.
        if remainder > 0:
            copay = min(cs.amount, remainder)
            charged += copay
            breakdown.append({
                "label": "Copay",
                "amount": _round(copay),
                "detail": f"Flat ${cs.amount:,.0f} copay for this service"
                          + (" once the deductible is met" if cs.after_deductible else ""),
            })
    elif cs.kind == "coinsurance":
        coins = remainder * cs.amount
        if coins > 0:
            charged += coins
            breakdown.append({
                "label": "Coinsurance",
                "amount": _round(coins),
                "detail": f"{cs.amount:.0%} of the remaining ${remainder:,.2f}",
            })
    # no_charge with after_deductible: the deductible portion above is all they owe.

    return _round(charged), breakdown, True


def patient_responsibility(
    allowed: float, plan: Plan, cost_share: ServiceCostShare | None = None
) -> tuple[float, list[dict]]:
    """Return (amount owed, itemised breakdown) for one allowed amount.

    When `cost_share` is supplied the plan's real per-service rule is applied.
    Without it, the plan's blended deductible/coinsurance is used — the best that
    can be done when the member typed their benefits in by hand.
    """
    if allowed <= 0:
        return 0.0, []

    if cost_share is not None:
        charged, breakdown, counts_toward_oop = _by_cost_share(allowed, plan, cost_share)
        if not counts_toward_oop:
            return charged, breakdown
        remaining_oop = plan.remaining_oop
        if charged > remaining_oop:
            breakdown.append({
                "label": "Out-of-pocket maximum",
                "amount": _round(remaining_oop - charged),
                "detail": f"Capped — you have ${remaining_oop:,.2f} left before your plan pays 100%",
            })
            charged = remaining_oop
        return _round(charged), breakdown

    breakdown = []

    if plan.copay is not None:
        charged = min(plan.copay, allowed)
        breakdown.append(
            {"label": "Copay", "amount": _round(charged),
             "detail": f"Flat copay for this service (allowed amount ${allowed:,.2f})"}
        )
    else:
        toward_deductible = min(allowed, plan.remaining_deductible)
        if toward_deductible > 0:
            breakdown.append(
                {"label": "Deductible", "amount": _round(toward_deductible),
                 "detail": f"${plan.remaining_deductible:,.2f} of your deductible is unmet"}
            )
        after_deductible = allowed - toward_deductible
        coinsurance = after_deductible * plan.coinsurance_pct
        if coinsurance > 0:
            breakdown.append(
                {"label": "Coinsurance", "amount": _round(coinsurance),
                 "detail": f"{plan.coinsurance_pct:.0%} of the remaining ${after_deductible:,.2f}"}
            )
        charged = toward_deductible + coinsurance

    remaining_oop = plan.remaining_oop
    if charged > remaining_oop:
        breakdown.append(
            {"label": "Out-of-pocket maximum", "amount": _round(remaining_oop - charged),
             "detail": f"Capped — you have ${remaining_oop:,.2f} left before your plan pays 100%"}
        )
        charged = remaining_oop

    return _round(charged), breakdown


def estimate(
    allowed: float,
    plan: Plan,
    *,
    low_allowed: float | None = None,
    high_allowed: float | None = None,
    extra_caveats: list[str] | None = None,
    cost_share: ServiceCostShare | None = None,
    cost_share_status: str | None = None,
) -> Estimate:
    """Estimate patient responsibility, with a range when rates vary.

    `low_allowed`/`high_allowed` come from the spread of negotiated rates across
    payers for the same code. They are never synthesised — when the hospital
    publishes a single rate, low == expected == high, and the UI says so.
    """
    expected, breakdown = patient_responsibility(allowed, plan, cost_share)
    low, _ = patient_responsibility(
        low_allowed if low_allowed is not None else allowed, plan, cost_share
    )
    high, _ = patient_responsibility(
        high_allowed if high_allowed is not None else allowed, plan, cost_share
    )
    low, high = min(low, high, expected), max(low, high, expected)

    caveats = list(BASE_CAVEATS)
    if plan.oop_max <= 0:
        caveats.append(
            "No out-of-pocket maximum is set on your plan, so this estimate is not capped."
        )
    if plan.copay is not None and cost_share is None:
        caveats.append("Copay plans can still bill separately for labs or imaging.")
    if cost_share is not None and cost_share.kind == "not_covered":
        caveats.append(
            "This service is not covered by your plan, so nothing counts toward your "
            "deductible or out-of-pocket maximum."
        )
    if cost_share is not None and cost_share.kind == "copay" and not cost_share.after_deductible:
        caveats.append(
            "Copays usually count toward your out-of-pocket maximum but not your deductible."
        )
    # A linked plan with no rule for this service is the dangerous case. Its
    # blended coinsurance is 0 — plans that price per service store their real
    # rules in plan_benefit and leave the blended field empty — so the fallback
    # quietly reports "you owe only your deductible". That is a confident,
    # specific and usually wrong number, and it is wrong in the direction that
    # costs the member money. Say what is actually known instead.
    complete = True
    if cost_share is None and cost_share_status in ("unclassified", "uncovered"):
        has_blended_rule = plan.coinsurance_pct > 0 or plan.copay is not None
        if not has_blended_rule and (plan.deductible > 0 or plan.oop_max > 0):
            complete = False
            caveats.insert(0, (
                "Your plan doesn't list a rule for this particular service, so this is only "
                "what your deductible accounts for — the real total is likely higher. Your "
                "insurer's benefits summary will say how this service is charged."
            ))

    if extra_caveats:
        caveats.extend(extra_caveats)

    return Estimate(
        expected=expected,
        low=low,
        high=high,
        allowed=_round(allowed),
        breakdown=breakdown,
        caveats=caveats,
        complete=complete,
    )
