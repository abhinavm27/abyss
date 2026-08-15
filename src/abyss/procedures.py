"""Deterministic procedure terminology catalog and ambiguity handling."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProcedureResolution:
    code: str | None
    canonical_name: str | None
    confidence: str
    candidates: tuple[str, ...] = ()
    needs_confirmation: bool = False


class ProcedureCatalog:
    """Validates model/user terminology against known seeded procedure facts."""

    _records = {
        "73721": "MRI knee without contrast",
        "73722": "MRI knee with contrast",
    }

    def names_for(self, codes: tuple[str, ...]) -> tuple[str, ...]:
        """Return only source-backed display names for known candidate codes."""
        return tuple(self._records[code] for code in codes if code in self._records)

    def resolve(self, phrase: str, *, confirmed_code: str | None = None) -> ProcedureResolution:
        normalized = " ".join(phrase.lower().replace("-", " ").split())
        if confirmed_code in self._records:
            return ProcedureResolution(confirmed_code, self._records[confirmed_code], "confirmed")
        if normalized in {"73721", "mri knee without contrast", "knee mri without contrast", "mri knee no contrast"}:
            return ProcedureResolution("73721", self._records["73721"], "source_backed")
        if normalized in {"73722", "mri knee with contrast", "knee mri with contrast"}:
            return ProcedureResolution("73722", self._records["73722"], "source_backed")
        if normalized in {"mri knee", "knee mri", "mri scan for knee", "knee scan"} or ("mri" in normalized and "knee" in normalized and "contrast" not in normalized):
            return ProcedureResolution(None, None, "ambiguous", ("73721", "73722"), True)
        return ProcedureResolution(None, None, "not_found", (), True)
