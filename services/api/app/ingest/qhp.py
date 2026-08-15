"""Ingest CMS QHP Public Use Files — marketplace plans and their cost-sharing.

Two files, published annually at https://download.cms.gov/marketplace-puf/<year>/:

  plan-attributes-puf.zip        one row per plan variant: metal level, plan type,
                                 HSA eligibility, deductible, out-of-pocket max
  benefits-and-cost-sharing-puf  one row per (plan, benefit): the copay or
                                 coinsurance for each service category

This is the structured replacement for reading Summary of Benefits and Coverage
PDFs by hand. It matters to ABYSS because a plan does not have one cost-sharing
rule — an MRI, a specialist visit and a generic prescription are each priced
differently, and applying a single blended coinsurance to all of them is wrong.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable, Iterator

CSV_FIELD_LIMIT = 10 * 1024 * 1024

# CMS benefit names -> the categories ABYSS prices against. Only these are
# stored; the PUF carries ~900 benefit names, most of which never come up in a
# "what will this cost me" question.
BENEFIT_CATEGORIES: dict[str, str] = {
    "Primary Care Visit to Treat an Injury or Illness": "pcp",
    "Specialist Visit": "specialist",
    "Urgent Care Centers or Facilities": "urgent_care",
    "Emergency Room Services": "emergency_room",
    "Emergency Transportation/Ambulance": "ambulance",
    "Imaging (CT/PET Scans, MRIs)": "advanced_imaging",
    "X-rays and Diagnostic Imaging": "xray",
    "Laboratory Outpatient and Professional Services": "lab",
    "Outpatient Facility Fee (e.g., Ambulatory Surgery Center)": "outpatient_facility",
    "Outpatient Surgery Physician/Surgical Services": "outpatient_surgery",
    "Inpatient Hospital Services (e.g., Hospital Stay)": "inpatient_facility",
    "Inpatient Physician and Surgical Services": "inpatient_physician",
    "Generic Drugs": "rx_generic",
    "Preferred Brand Drugs": "rx_preferred_brand",
    "Non-Preferred Brand Drugs": "rx_nonpreferred_brand",
    "Specialty Drugs": "rx_specialty",
    "Rehabilitative Occupational and Rehabilitative Physical Therapy": "physical_therapy",
    "Chiropractic Care": "chiropractic",
    "Prenatal and Postnatal Care": "prenatal",
    "Delivery and All Inpatient Services for Maternity Care": "delivery",
    "Mental/Behavioral Health Outpatient Services": "mental_health_outpatient",
    "Substance Abuse Disorder Outpatient Services": "substance_use_outpatient",
}

# Exact codes that must not be decided by range. Kept as overrides in front of
# the ranges below, for codes whose neighbours behave differently.
CODE_TYPE_TO_CATEGORY = {
    "outpatient_surgery": {"45378", "45380", "45385", "43239"},
    "urgent_care": {"99051"},
}

# CPT/HCPCS ranges, most specific first.
#
# This replaced a hand-written list of 39 exact codes. That list was the ceiling
# on the whole product: a code outside it produced no cost-sharing rule at all,
# and every estimate for it silently fell back to the plan's blended rate.
#
# Ranges are used because CPT is organised by them, and are ordered so that the
# narrow diagnostic ranges win over the broad section they sit inside — an MRI
# and a chest x-ray are both "radiology", and charging one at the other's rate is
# wrong by an order of magnitude.
#
# Only mappings that are safe get made. Anything ambiguous is deliberately left
# out and returns None, which `cost_share_for` now reports honestly rather than
# treating as "no coinsurance".
_CPT_RANGES: tuple[tuple[int, int, str], ...] = (
    # --- CT, MRI, MRA, PET and nuclear: the "advanced imaging" benefit --------
    (70336, 70336, "advanced_imaging"),   # MRI temporomandibular joint
    (70450, 70498, "advanced_imaging"),   # CT / CTA head and neck
    (70540, 70559, "advanced_imaging"),   # MRI / MRA head and neck
    (71250, 71275, "advanced_imaging"),   # CT / CTA chest
    (71550, 71555, "advanced_imaging"),   # MRI / MRA chest
    (72125, 72133, "advanced_imaging"),   # CT spine
    (72141, 72159, "advanced_imaging"),   # MRI / MRA spine
    (72191, 72198, "advanced_imaging"),   # CT / MRI pelvis
    (73200, 73206, "advanced_imaging"),   # CT upper extremity
    (73218, 73225, "advanced_imaging"),   # MRI / MRA upper extremity
    (73700, 73706, "advanced_imaging"),   # CT lower extremity
    (73718, 73725, "advanced_imaging"),   # MRI / MRA lower extremity
    (74150, 74178, "advanced_imaging"),   # CT abdomen
    (74181, 74185, "advanced_imaging"),   # MRI / MRA abdomen
    (75557, 75574, "advanced_imaging"),   # cardiac MRI and CT
    (76380, 76380, "advanced_imaging"),   # limited CT
    (78012, 79999, "advanced_imaging"),   # nuclear medicine, including PET

    # --- plain radiography, ultrasound, mammography: the "x-ray" benefit -----
    (76506, 76999, "xray"),               # diagnostic ultrasound
    (77046, 77067, "xray"),               # breast MRI and mammography
    (70010, 76499, "xray"),               # everything else in diagnostic imaging

    # --- laboratory and pathology -------------------------------------------
    (80047, 89398, "lab"),

    # --- evaluation and management ------------------------------------------
    # Starts at 99201, not 99202: the AMA retired 99201 in 2021, but hospital
    # chargemasters lag and 288 rows in the ingested data still use it.
    (99201, 99215, "pcp"),                # office and outpatient visits
    (99241, 99255, "specialist"),         # consultations
    (99281, 99288, "emergency_room"),
    (99381, 99429, "pcp"),                # preventive medicine visits

    # --- therapies ----------------------------------------------------------
    (90791, 90899, "mental_health_outpatient"),
    (97010, 97799, "physical_therapy"),
    (98940, 98943, "chiropractic"),

    # --- maternity ----------------------------------------------------------
    (59400, 59622, "delivery"),
    (59000, 59076, "prenatal"),

    # Surgery (10004-69990) is deliberately absent: CPT alone does not say
    # whether a procedure is inpatient or outpatient, and those are different
    # benefits. `category_for_code` uses the rate's own `setting` column for it.
)

# Code systems that describe a whole admission rather than one procedure.
_INPATIENT_CODE_TYPES = {"MS-DRG", "APR-DRG", "TRIS-DRG", "DRG"}

MONEY = re.compile(r"\$\s*([\d,]+(?:\.\d+)?)")
PERCENT = re.compile(r"([\d.]+)\s*%")


@dataclass(frozen=True)
class CostShare:
    """How a plan charges the member for one service category.

    `kind` is one of: copay, coinsurance, no_charge, not_covered, unknown.
    `after_deductible` means the deductible must be satisfied first.
    """

    kind: str
    amount: float = 0.0  # dollars for copay, fraction for coinsurance
    after_deductible: bool = False

    @property
    def is_priced(self) -> bool:
        return self.kind in ("copay", "coinsurance", "no_charge")


def parse_cost_share(copay_raw: str | None, coins_raw: str | None) -> CostShare:
    """Turn the PUF's human-readable cost-sharing strings into something usable.

    Observed value shapes, in descending frequency:
        "Not Applicable"                        -> defer to the other column
        "$0.00" / "$40.00"                      -> copay, before deductible
        "No Charge"                             -> covered in full, no deductible
        "No Charge after deductible"            -> free once the deductible is met
        "20.00% Coinsurance after deductible"   -> coinsurance, after deductible
        "50.00%"                                -> coinsurance, before deductible

    Absence of the words "after deductible" genuinely means the charge applies
    before it — that distinction is the difference between a $40 office visit
    and a $40 office visit that only starts after $6,000 of spending.
    """
    for raw in (copay_raw, coins_raw):
        if not raw:
            continue
        text = raw.strip()
        if not text or text.lower() == "not applicable":
            continue

        after = "after deductible" in text.lower()

        if "no charge" in text.lower():
            return CostShare("no_charge", 0.0, after)

        pct = PERCENT.search(text)
        if pct:
            rate = float(pct.group(1)) / 100.0
            if rate == 0.0:
                return CostShare("no_charge", 0.0, after)
            return CostShare("coinsurance", rate, after)

        money = MONEY.search(text)
        if money:
            return CostShare("copay", float(money.group(1).replace(",", "")), after)

    return CostShare("unknown")


def parse_money(raw: str | None) -> float | None:
    """`$1,500 `, `$3000 per group`, `Not Applicable` -> float or None."""
    if not raw:
        return None
    m = MONEY.search(raw)
    return float(m.group(1).replace(",", "")) if m else None


def _member(zf: zipfile.ZipFile) -> str:
    names = [n for n in zf.namelist() if n.lower().endswith(".csv") and not n.startswith("__MACOSX/")]
    if not names:
        raise ValueError(f"no CSV in {zf.filename}")
    return max(names, key=lambda n: zf.getinfo(n).file_size)


def _rows(path: Path) -> Iterator[dict]:
    """Stream a zipped CSV without extracting it — BenCS is 375 MB unzipped."""
    csv.field_size_limit(CSV_FIELD_LIMIT)
    with zipfile.ZipFile(path) as zf:
        name = _member(zf)
        with zf.open(name) as fh:
            reader = csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8-sig", errors="replace"))
            yield from reader


def parse_plan_attributes(path: Path, states: set[str] | None = None) -> Iterator[tuple]:
    """Yield plan rows from Plan_Attributes_PUF."""
    for row in _rows(path):
        state = (row.get("StateCode") or "").strip()
        if states and state not in states:
            continue
        if (row.get("DentalOnlyPlan") or "").strip().lower() == "yes":
            continue
        plan_id = (row.get("PlanId") or "").strip()
        if not plan_id:
            continue

        # TEHB = total essential health benefits (medical + drug combined);
        # MEHB = medical only. Prefer the combined figure, fall back to medical.
        ded = parse_money(row.get("TEHBDedInnTier1Individual")) or parse_money(
            row.get("MEHBDedInnTier1Individual")
        )
        ded_fam = parse_money(row.get("TEHBDedInnTier1FamilyPerGroup")) or parse_money(
            row.get("MEHBDedInnTier1FamilyPerGroup")
        )
        moop = parse_money(row.get("TEHBInnTier1IndividualMOOP")) or parse_money(
            row.get("MEHBInnTier1IndividualMOOP")
        )
        moop_fam = parse_money(row.get("TEHBInnTier1FamilyPerGroupMOOP")) or parse_money(
            row.get("MEHBInnTier1FamilyPerGroupMOOP")
        )

        yield (
            plan_id,
            state,
            (row.get("IssuerId") or "").strip(),
            (row.get("IssuerMarketPlaceMarketingName") or "").strip(),
            (row.get("PlanMarketingName") or "").strip(),
            (row.get("MetalLevel") or "").strip(),
            (row.get("PlanType") or "").strip(),
            1 if (row.get("IsHSAEligible") or "").strip().lower() == "yes" else 0,
            ded,
            ded_fam,
            moop,
            moop_fam,
            (row.get("BusinessYear") or "").strip(),
        )


def parse_benefits(path: Path, states: set[str] | None = None) -> Iterator[tuple]:
    """Yield (plan_id, category, kind, amount, after_deductible, covered) rows."""
    for row in _rows(path):
        state = (row.get("StateCode") or "").strip()
        if states and state not in states:
            continue
        category = BENEFIT_CATEGORIES.get((row.get("BenefitName") or "").strip())
        if not category:
            continue
        plan_id = (row.get("PlanId") or "").strip()
        if not plan_id:
            continue

        covered = (row.get("IsCovered") or "").strip().lower() == "covered"
        if not covered:
            yield (plan_id, category, "not_covered", 0.0, 0, 0, 0)
            continue

        cs = parse_cost_share(row.get("CopayInnTier1"), row.get("CoinsInnTier1"))
        yield (
            plan_id,
            category,
            cs.kind,
            cs.amount,
            1 if cs.after_deductible else 0,
            1,
            1 if (row.get("IsExclFromInnMOOP") or "").strip().lower() == "yes" else 0,
        )


def category_for_code(
    code: str, code_type: str | None = None, setting: str | None = None
) -> str | None:
    """Map a billing code onto the plan cost-sharing category that governs it.

    Returns None when the code cannot be classified confidently. That is a real
    answer, not a failure: `cost_share_for` reports it rather than quietly
    charging the member the plan's blended rate.
    """
    if not code:
        return None
    code = code.strip().upper()

    for category, codes in CODE_TYPE_TO_CATEGORY.items():
        if code in codes:
            return category

    kind = (code_type or "").strip().upper()

    # A DRG is an entire inpatient stay, whatever the procedure inside it.
    if kind in _INPATIENT_CODE_TYPES:
        return "inpatient_facility"
    # Enhanced Ambulatory Patient Groups are the outpatient equivalent.
    if kind == "EAPG":
        return "outpatient_facility"
    # An NDC identifies a drug but not the tier the plan prices it in — generic,
    # preferred, non-preferred and specialty are four different benefits and the
    # code cannot distinguish them.
    if kind == "NDC":
        return None

    # HCPCS Level II, letters then digits. Only ambulance is unambiguous; J-codes
    # are provider-administered drugs billed under the medical benefit rather
    # than the pharmacy one, so they are left unmapped on purpose.
    if code[0].isalpha():
        return "ambulance" if code.startswith("A0") else None

    if not code[:5].isdigit():
        return None
    number = int(code[:5])

    for low, high, category in _CPT_RANGES:
        if low <= number <= high:
            return category

    # Surgery: the procedure code does not say where it happens, so the rate's
    # own setting decides. Without it, nothing is claimed.
    if 10004 <= number <= 69990:
        place = (setting or "").strip().lower()
        if place == "inpatient":
            return "inpatient_facility"
        if place == "outpatient":
            return "outpatient_surgery"
    return None


Opener = Callable[[], BinaryIO]
