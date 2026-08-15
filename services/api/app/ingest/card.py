"""Read an insurance card photo.

What a card actually carries is narrow, and being honest about that is the whole
design. The front of a member ID card gives the payer, a plan or product name,
the member and group numbers, and sometimes a handful of copays. It does **not**
give the deductible, the out-of-pocket maximum, or the coinsurance rate — the
three figures every estimate in ABYSS depends on.

So a scan identifies the plan and hands off to the Summary of Benefits. It never
invents the numbers it cannot see: a model asked for a deductible will happily
produce a plausible one, and a plausible deductible is exactly the kind of
confident wrong answer this app exists to avoid.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config import gemini_api_key

MODEL = "gemini-2.5-flash"

PROMPT = """You are reading a photograph of a health insurance member ID card.

Return ONLY what is printed on the card. Rules:
- If a field is not visibly printed, return null. Never infer or complete it.
- Do not guess the deductible, out-of-pocket maximum or coinsurance. Cards
  almost never show these. Returning null is the correct answer.
- copays: only those actually printed, with the label used on the card.
- Transcribe member and group numbers exactly, including letters.
"""


@dataclass
class CardResult:
    payer_name: str | None = None
    plan_name: str | None = None
    plan_type: str | None = None  # HMO | PPO | EPO | POS
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
            # Stated in the payload rather than only in the UI, so any client
            # reading this cannot mistake a scan for a full plan.
            "provides_cost_sharing": False,
        }


_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "payer_name": {"type": "STRING", "nullable": True},
        "plan_name": {"type": "STRING", "nullable": True},
        "plan_type": {"type": "STRING", "nullable": True},
        "member_id": {"type": "STRING", "nullable": True},
        "group_number": {"type": "STRING", "nullable": True},
        "rx_bin": {"type": "STRING", "nullable": True},
        "copays": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {"label": {"type": "STRING"}, "amount": {"type": "NUMBER"}},
                "required": ["label", "amount"],
            },
        },
    },
}


def parse(image_bytes: bytes, mime_type: str = "image/jpeg") -> CardResult:
    """Extract what is printed on an insurance card."""
    result = CardResult()
    if not image_bytes:
        result.warnings.append("no image was received")
        return result

    api_key = gemini_api_key()
    if not api_key:
        # Same shape as the SBC parser's behaviour: degrade with a plain
        # explanation rather than failing in a way that looks like a bug.
        result.warnings.append("GEMINI_API_KEY is not configured, so the card was not read")
        return result

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    try:
        response = client.models.generate_content(
            model=MODEL,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                types.Part(text=PROMPT),
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=_SCHEMA,
                temperature=0,
            ),
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the member, not raised
        result.warnings.append(f"the card could not be read: {exc}")
        return result

    import json

    try:
        data = json.loads(response.text or "{}")
    except json.JSONDecodeError:
        result.warnings.append("the card could not be read")
        return result

    result.payer_name = data.get("payer_name") or None
    result.plan_name = data.get("plan_name") or None
    result.plan_type = (data.get("plan_type") or "").upper() or None
    result.member_id = data.get("member_id") or None
    result.group_number = data.get("group_number") or None
    result.rx_bin = data.get("rx_bin") or None
    for entry in data.get("copays") or []:
        label = str(entry.get("label") or "").strip()
        if label:
            result.copays[label] = float(entry.get("amount") or 0)

    if not result.payer_name and not result.plan_name:
        result.warnings.append(
            "Nothing readable was found on this image. A straight-on photo of the front of the "
            "card, in good light, works best."
        )
    return result
