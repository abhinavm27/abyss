"""Parse a Summary of Benefits and Coverage PDF.

Every US health plan must publish an SBC in a federally standardized format,
which makes it the one document that exists for *every* plan — employer
coverage, state-run marketplaces like Massachusetts, and anything else absent
from the CMS Public Use Files. It is also the document EMME reads by hand today.

Why this is model-assisted rather than a regex
----------------------------------------------
The format is standardized on paper, not in the PDF. Text extraction interleaves
the columns: a row reading "Primary care visit … $15 copay/office visit" comes
out as "Primary care visit to treat an $15 copay/office visit … injury or
illness then 20% coinsurance", with the out-of-network and limitations columns
woven through it.

A deterministic parser was written first and measured against three real
documents with hand-checked ground truth. It got the in-network out-of-pocket
maximum wrong on all three, because the first dollar figure after the question
text is usually the family or out-of-network number:

    SC State Health Plan   actual $3,000   regex $6,000    model $3,000
    Northwestern Essential actual $7,000   regex $14,000   model $7,000
    NY MVP                 actual $6,350   regex $12,700   model $6,350

Overstating a member's out-of-pocket maximum makes every large estimate look
cheaper than it is, so the regex approach was dropped.

What keeps the model honest
---------------------------
Every number it returns is checked against the numbers actually present in the
document. Anything that does not appear verbatim as a figure in the source is
discarded and recorded in `warnings`, so the model cannot introduce an amount
that is not in the PDF. It can still mis-assign a real number to the wrong row,
which is why the caller must show the member what was read and let them correct
it before it is used.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

from ..config import gemini_api_key
from .qhp import MONEY, PERCENT, CostShare

EXTRACTION_MODEL = "gemini-2.5-flash"
MAX_CHARS = 24_000  # an SBC is 6-8 pages; the benefit tables are in the first few

# The categories ABYSS prices, described using the federal SBC wording so the
# model is matching labels rather than interpreting them.
SBC_SERVICES: dict[str, str] = {
    "pcp": "Primary care visit to treat an injury or illness",
    "specialist": "Specialist visit",
    "urgent_care": "Urgent care",
    "emergency_room": "Emergency room care",
    "ambulance": "Emergency medical transportation",
    "advanced_imaging": "Imaging (CT/PET scans, MRIs)",
    "xray": "Diagnostic test (x-ray, blood work)",
    "lab": "Diagnostic test (x-ray, blood work)",
    "outpatient_facility": "Facility fee (e.g., ambulatory surgery center)",
    "outpatient_surgery": "Physician/surgeon fees for outpatient surgery",
    "inpatient_facility": "Facility fee (e.g., hospital room)",
    "inpatient_physician": "Physician/surgeon fees for a hospital stay",
    "rx_generic": "Generic drugs",
    "rx_preferred_brand": "Preferred brand drugs",
    "rx_nonpreferred_brand": "Non-preferred brand drugs",
    "rx_specialty": "Specialty drugs",
    "physical_therapy": "Rehabilitation services",
    "prenatal": "Office visits for pregnancy (prenatal care)",
    "delivery": "Childbirth/delivery professional services",
    "mental_health_outpatient": "Mental/behavioral health outpatient services",
}

# Phrases meaning the deductible is NOT applied. Without one of these, an SBC
# row sits behind the deductible — the opposite of the PUF convention, and
# getting it backwards understates every estimate.
NO_DEDUCTIBLE = re.compile(
    r"deductible\s+does\s+not\s+apply|no\s+deductible|deductible\s+waived|"
    r"not\s+subject\s+to\s+(?:the\s+)?deductible",
    re.I,
)
NOT_COVERED = re.compile(r"\bnot\s+covered\b", re.I)
NO_CHARGE = re.compile(r"\bno\s+charge\b", re.I)

_WS = re.compile(r"\s+")
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")

PROMPT = """You are reading a Summary of Benefits and Coverage (SBC) document.

Return, for each listed service, the IN-NETWORK "What You Will Pay" cell exactly
as written in the document.

Critical rules:
- Use the IN-NETWORK column only. Never the out-of-network column.
- Use the INDIVIDUAL figure for the deductible and out-of-pocket maximum, never
  the family figure.
- Copy values as they appear. Do not compute, convert, average or infer anything.
- If a service is not listed, omit that field entirely. Do not guess.
- The column text may be interleaved with other columns in the extracted text.
  Attribute each value to the correct row and column.

Services to find:
{services}
"""


@dataclass
class SbcResult:
    """What was read from the document, and what could not be trusted."""

    plan_name: str | None = None
    coverage_period: str | None = None
    plan_type: str | None = None
    deductible: float | None = None
    oop_max: float | None = None
    benefits: dict[str, CostShare] = field(default_factory=dict)
    raw_cells: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "plan_name": self.plan_name,
            "coverage_period": self.coverage_period,
            "plan_type": self.plan_type,
            "deductible": self.deductible,
            "oop_max": self.oop_max,
            "benefits": {
                cat: {
                    "kind": cs.kind,
                    "amount": cs.amount,
                    "after_deductible": cs.after_deductible,
                    "source_text": self.raw_cells.get(cat, ""),
                }
                for cat, cs in self.benefits.items()
            },
            "warnings": self.warnings,
        }


def parse_sbc_cost_share(text: str) -> CostShare:
    """Read one SBC "What You Will Pay" cell.

    Real examples: "$15 copay/office visit then 20% coinsurance",
    "20% coinsurance", "No charge", "Not covered", "$200copayment per visit",
    "$25 copay/visit, deductible does not apply".
    """
    if not text or not text.strip():
        return CostShare("unknown")

    if NOT_COVERED.search(text):
        return CostShare("not_covered")

    after_deductible = not bool(NO_DEDUCTIBLE.search(text))

    # A cell often lists several settings: "Lab Office - No charge; Lab Facility
    # - No charge ... $15". Whichever term comes FIRST is the one that applies to
    # the primary setting, so position decides — not the order these are checked
    # in. Reading that cell as a $15 copay when it opens with "No charge"
    # overstates the member's cost.
    candidates: list[tuple[int, CostShare]] = []

    money = MONEY.search(text)
    if money:
        candidates.append(
            (money.start(), CostShare("copay", float(money.group(1).replace(",", "")), after_deductible))
        )

    percent = PERCENT.search(text)
    if percent:
        rate = float(percent.group(1)) / 100.0
        candidates.append(
            (
                percent.start(),
                CostShare("no_charge" if rate == 0.0 else "coinsurance", rate, after_deductible),
            )
        )

    free = NO_CHARGE.search(text)
    if free:
        candidates.append((free.start(), CostShare("no_charge", 0.0, after_deductible)))

    if not candidates:
        return CostShare("unknown")
    return min(candidates, key=lambda c: c[0])[1]


def extract_text(source: str | Path | BinaryIO) -> str:
    import pdfplumber

    with pdfplumber.open(source) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)


def _numbers_in(text: str) -> set[str]:
    """Every numeric token in the document, normalised for comparison."""
    return {n.replace(",", "").rstrip("0").rstrip(".") or "0" for n in _NUMBER.findall(text)}


def _appears_in_source(value: float | str, source_numbers: set[str]) -> bool:
    """True when every figure in `value` occurs somewhere in the document."""
    text = str(value)
    found = _NUMBER.findall(text)
    if not found:
        return True  # nothing numeric to verify ("No charge", "Not covered")
    return all(
        (n.replace(",", "").rstrip("0").rstrip(".") or "0") in source_numbers for n in found
    )


def _build_schema() -> dict:
    props: dict = {
        "plan_name": {"type": "STRING"},
        "plan_type": {"type": "STRING"},
        "coverage_period": {"type": "STRING"},
        "deductible_individual": {"type": "NUMBER"},
        "out_of_pocket_max_individual": {"type": "NUMBER"},
    }
    for category in SBC_SERVICES:
        props[category] = {"type": "STRING"}
    return {"type": "OBJECT", "properties": props}


def parse(source: str | Path | BinaryIO, *, text: str | None = None) -> SbcResult:
    """Read an SBC PDF into a plan profile.

    Numbers the document does not contain are discarded rather than returned.
    """
    result = SbcResult()
    document = text if text is not None else extract_text(source)
    if not document.strip():
        result.warnings.append("no text could be extracted from this PDF")
        return result

    api_key = gemini_api_key()
    if not api_key:
        result.warnings.append("GEMINI_API_KEY is not configured, so the SBC was not read")
        return result

    from google import genai
    from google.genai import types

    services = "\n".join(f"- {cat}: {label}" for cat, label in SBC_SERVICES.items())
    client = genai.Client(api_key=api_key)
    try:
        response = client.models.generate_content(
            model=EXTRACTION_MODEL,
            contents=PROMPT.format(services=services) + "\n\n---SBC---\n" + document[:MAX_CHARS],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=_build_schema(),
                temperature=0,
            ),
        )
        data = json.loads(response.text)
    except Exception as exc:
        result.warnings.append(f"could not read this SBC: {type(exc).__name__}")
        return result

    source_numbers = _numbers_in(document)

    result.plan_name = (data.get("plan_name") or "").strip() or None
    result.plan_type = (data.get("plan_type") or "").strip() or None
    result.coverage_period = (data.get("coverage_period") or "").strip() or None

    for field_name, attr, label in (
        ("deductible_individual", "deductible", "deductible"),
        ("out_of_pocket_max_individual", "oop_max", "out-of-pocket maximum"),
    ):
        value = data.get(field_name)
        if value is None:
            result.warnings.append(f"no {label} was found in this document")
            continue
        if not _appears_in_source(value, source_numbers):
            result.warnings.append(
                f"the {label} read as ${value:,.0f} does not appear in the document and was discarded"
            )
            continue
        setattr(result, attr, float(value))

    for category in SBC_SERVICES:
        cell = (data.get(category) or "").strip()
        if not cell:
            continue
        if not _appears_in_source(cell, source_numbers):
            result.warnings.append(
                f"{category}: \"{cell[:40]}\" contains a figure not in the document, discarded"
            )
            continue
        cs = parse_sbc_cost_share(cell)
        if cs.kind == "unknown":
            continue
        result.benefits[category] = cs
        result.raw_cells[category] = cell

    if not result.benefits:
        result.warnings.append("no service costs could be read from this document")

    return result
