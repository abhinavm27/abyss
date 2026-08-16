"""Parse OCR text from a synthetic health-insurance member ID card.

The browser performs OCR on-device and sends the recognized text beside the
image. This parser only transcribes labeled values; it never invents benefits
that are not printed on the card and it does not send member identifiers to a
hosted vision model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class CardResult:
    payer_name: str | None = None
    plan_name: str | None = None
    plan_type: str | None = None
    member_id: str | None = None
    group_number: str | None = None
    rx_bin: str | None = None
    copays: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "payer_name": self.payer_name,
            "plan_name": self.plan_name,
            "plan_type": self.plan_type,
            "member_id": self.member_id,
            "group_number": self.group_number,
            "rx_bin": self.rx_bin,
            "copays": self.copays,
            "warnings": self.warnings,
            "provides_cost_sharing": False,
        }


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" :#|-")


def _labeled(text: str, labels: tuple[str, ...]) -> str | None:
    label_pattern = "|".join(re.escape(label) for label in labels)
    match = re.search(
        rf"(?im)^\s*(?:{label_pattern})\s*(?:id|number|no\.?|#)?\s*[:#-]?\s*([A-Z0-9][A-Z0-9 .&'/-]{{2,}})\s*$",
        text,
    )
    return _clean(match.group(1)) if match else None


def parse_text(text: str) -> CardResult:
    result = CardResult()
    source = text.replace("\r", "\n")
    normalized = "\n".join(_clean(line) for line in source.splitlines() if _clean(line))
    if not normalized:
        result.warnings.append("No readable text was found on the card image")
        return result

    result.member_id = _labeled(normalized, ("member", "member id", "subscriber id", "id"))
    result.group_number = _labeled(normalized, ("group", "group number", "group no"))
    result.rx_bin = _labeled(normalized, ("rx bin", "rxbin", "bin"))
    result.plan_name = _labeled(normalized, ("plan", "product", "network"))

    plan_type = re.search(r"(?i)\b(PPO|HMO|EPO|POS|HDHP)\b", normalized)
    result.plan_type = plan_type.group(1).upper() if plan_type else None

    payer_patterns = (
        r"\bPremera(?: Blue Cross)?\b",
        r"\bRegence(?: BlueShield)?\b",
        r"\bUnitedHealthcare\b",
        r"\bBlue Cross(?: Blue Shield)?\b",
        r"\bAetna\b",
        r"\bCigna\b",
        r"\bKaiser Permanente\b",
        r"\bMolina Healthcare\b",
        r"\bHumana\b",
    )
    for pattern in payer_patterns:
        match = re.search(pattern, normalized, re.IGNORECASE)
        if match:
            result.payer_name = _clean(match.group(0))
            break
    if result.payer_name is None:
        result.payer_name = _labeled(normalized, ("payer", "carrier", "insurer"))

    for match in re.finditer(
        r"(?im)^\s*([A-Za-z][A-Za-z /&-]{2,30}?(?:copay|visit|care|office|specialist|emergency|urgent))\s*[:$ ]+\$?\s*(\d{1,4}(?:\.\d{1,2})?)\s*$",
        normalized,
    ):
        result.copays[_clean(match.group(1))] = float(match.group(2))

    if not any((result.payer_name, result.plan_name, result.member_id, result.group_number)):
        result.warnings.append(
            "No labeled insurance details were recognized. Retake a straight-on photo of the card front in good light."
        )
    result.warnings.append(
        "An insurance card identifies the plan but does not provide the deductible, out-of-pocket maximum, or coinsurance."
    )
    return result


def parse(
    image_bytes: bytes,
    mime_type: str = "image/jpeg",
    *,
    extracted_text: str | None = None,
) -> CardResult:
    """Parse browser-supplied OCR text while validating that an image exists."""
    del mime_type
    if not image_bytes:
        return CardResult(warnings=["No image was received"])
    if not extracted_text or not extracted_text.strip():
        return CardResult(warnings=[
            "The card image was received, but no readable on-device OCR text was supplied."
        ])
    return parse_text(extracted_text)
