"""The one row shape both MRF parsers emit.

CMS lets hospitals publish either JSON or a flat CSV, and the two encode the
same facts very differently. Everything downstream (retrieval, estimation) reads
only `Rate`, so the format difference stops here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Hospitals encode CPT under "HCPCS" (CPT is HCPCS Level I). Verified against
# the Anna Jaques file: 17,727 records typed HCPCS, zero typed CPT. Callers ask
# for "CPT" all the time, so normalise the spellings to a single vocabulary.
CODE_TYPE_ALIASES = {
    "hcpcs": "HCPCS",
    "cpt": "HCPCS",
    "cpt4": "HCPCS",
    "hcpcs/cpt": "HCPCS",
    "aprdrg": "APR-DRG",
    "apr-drg": "APR-DRG",
    "apr drg": "APR-DRG",
    "msdrg": "MS-DRG",
    "ms-drg": "MS-DRG",
    "ms drg": "MS-DRG",
    "drg": "MS-DRG",
    "ndc": "NDC",
    "rc": "REV",
    "rev": "REV",
    "revenue code": "REV",
    "cdm": "CDM",
    "local": "CDM",
    "icd": "ICD",
    "icd10": "ICD",
}

def norm_code_type(raw: str | None) -> str | None:
    if not raw:
        return None
    key = str(raw).strip().lower().replace("_", " ")
    return CODE_TYPE_ALIASES.get(key, str(raw).strip().upper())


def norm_setting(raw: str | None) -> str | None:
    if not raw:
        return None
    v = str(raw).strip().lower()
    if v.startswith("in"):
        return "inpatient"
    if v.startswith("out"):
        return "outpatient"
    if v == "both":
        return "both"
    return v or None


def to_float(raw: object) -> float | None:
    """Parse a money-ish cell. Returns None for blanks and non-numerics.

    MRF cells arrive as "1234.56", "$1,234.56", "", "N/A", or already-float.
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip().replace("$", "").replace(",", "")
    if not s or s.lower() in {"n/a", "na", "none", "null", "-"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


@dataclass
class Rate:
    code: str | None
    code_type: str | None
    description: str | None
    setting: str | None
    billing_class: str | None
    payer_name: str | None
    plan_name: str | None
    methodology: str | None
    negotiated_dollar: float | None
    gross_charge: float | None = None
    discounted_cash: float | None = None
    min_rate: float | None = None
    max_rate: float | None = None

    @property
    def estimable(self) -> bool:
        """True only when this row can produce a patient-responsibility number.

        A row with a methodology but no dollar amount is the hospital saying
        "this is a formula, not a price". Marking it non-estimable is what keeps
        the app from inventing a figure for it later.
        """
        return self.negotiated_dollar is not None and self.negotiated_dollar > 0

    def as_row(self, hospital_id: int) -> tuple:
        return (
            hospital_id,
            self.code,
            self.code_type,
            self.description,
            self.setting,
            self.billing_class,
            self.payer_name,
            self.plan_name,
            self.methodology,
            self.negotiated_dollar,
            self.gross_charge,
            self.discounted_cash,
            self.min_rate,
            self.max_rate,
            1 if self.estimable else 0,
        )


INSERT_SQL = """
INSERT INTO rate (
  hospital_id, code, code_type, description, setting, billing_class,
  payer_name, plan_name, methodology, negotiated_dollar,
  gross_charge, discounted_cash, min_rate, max_rate, estimable
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
"""


@dataclass
class ParseStats:
    """Counts what the parser could not use, so gaps stay visible."""

    rows_written: int = 0
    rows_skipped: int = 0
    skip_reasons: dict[str, int] = field(default_factory=dict)

    def skip(self, reason: str) -> None:
        self.rows_skipped += 1
        self.skip_reasons[reason] = self.skip_reasons.get(reason, 0) + 1

    def summary(self) -> str:
        if not self.skip_reasons:
            return "none"
        return ", ".join(f"{k}={v}" for k, v in sorted(self.skip_reasons.items()))
