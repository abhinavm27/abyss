"""Deterministic procedure terminology catalog and ambiguity handling."""

from __future__ import annotations

import re
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
        "76700": "Complete abdominal ultrasound",
        "85025": "Complete blood count with differential",
    }

    def names_for(self, codes: tuple[str, ...]) -> tuple[str, ...]:
        """Return only source-backed display names for known candidate codes."""
        return tuple(self._records[code] for code in codes if code in self._records)

    @staticmethod
    def _normalized(phrase: str) -> str:
        return " ".join(re.sub(r"[^a-z0-9]+", " ", phrase.lower()).split())

    def merge(
        self, existing: str, proposed: str, utterance: str
    ) -> tuple[str, ProcedureResolution]:
        """Merge a multi-turn procedure without accumulating duplicate prose.

        The model may return either a fragment (``abdomen``) or a replacement
        phrase (``complete abdominal MRI``). Source-backed terminology decides
        whether a candidate is resolved; unresolved text is kept compact so a
        later turn cannot grow ``MRI; MRI; MRI`` indefinitely.
        """
        candidates = (
            f"{proposed} {utterance}",
            f"{existing} {proposed} {utterance}",
            f"{existing} {utterance}",
            proposed,
        )
        for candidate in candidates:
            resolution = self.resolve(candidate)
            if not resolution.needs_confirmation:
                return resolution.canonical_name or proposed, resolution

        existing_normalized = self._normalized(existing)
        proposed_normalized = self._normalized(proposed)
        modalities = {"mri", "ultrasound", "blood", "cbc", "xray", "ct"}
        proposed_tokens = set(proposed_normalized.split())
        if existing_normalized in proposed_normalized:
            merged = proposed
        elif proposed_normalized in existing_normalized:
            merged = existing
        elif modalities & proposed_tokens:
            # A complete new procedure phrase supersedes the earlier vague one.
            merged = proposed
        else:
            words: list[str] = []
            seen: set[str] = set()
            for word in f"{existing} {proposed}".split():
                key = self._normalized(word)
                if key and key not in seen:
                    words.append(word)
                    seen.add(key)
            merged = " ".join(words)
        return merged, self.resolve(merged)

    def clarification_question(self, phrase: str, resolution: ProcedureResolution) -> str:
        """Ask only for procedure-family details that can resolve the catalog."""
        if resolution.candidates:
            choices = " or ".join(self.names_for(resolution.candidates))
            return (f"Should this be {choices}?" if choices
                    else "Which specific procedure did your clinician order?")

        normalized = self._normalized(phrase)
        tokens = set(normalized.split())
        if {"blood", "cbc", "lab", "laboratory"} & tokens:
            return (
                "Which blood test did your clinician order—for example, a complete blood "
                "count (CBC) with differential, a metabolic panel, or another named test?"
            )
        if "mri" in tokens:
            if not ({"knee", "abdomen", "abdominal", "head", "brain", "shoulder", "hip"} & tokens):
                return "What body area is the MRI for, and was it ordered with or without contrast?"
            return "What exact MRI procedure is written on the order, including contrast details?"
        if "ultrasound" in tokens:
            return (
                "What body area and specific type of ultrasound did your clinician order? "
                "I need those details to find the matching catalog entry."
            )
        return "What exact procedure name or code is written on your clinician's order?"

    def resolve(self, phrase: str, *, confirmed_code: str | None = None) -> ProcedureResolution:
        normalized = self._normalized(phrase)
        tokens = set(normalized.split())
        if confirmed_code in self._records:
            return ProcedureResolution(confirmed_code, self._records[confirmed_code], "confirmed")
        if normalized in {
            "abdominal ultrasound complete", "complete abdominal ultrasound",
            "ultrasound abdomen complete", "complete ultrasound abdomen",
            "us exam abdomen complete", "us exam abdom complete",
        } or (
            "ultrasound" in tokens
            and "complete" in tokens
            and bool({"abdomen", "abdominal"} & tokens)
        ):
            return ProcedureResolution("76700", self._records["76700"], "source_backed")
        if normalized in {
            "cbc with differential", "cbc with diff",
            "complete blood count with differential",
            "complete blood count with diff",
            "complete cbc with auto diff wbc",
        } or (
            ("cbc" in tokens or {"complete", "blood", "count"} <= tokens)
            and bool({"differential", "diff"} & tokens)
        ):
            return ProcedureResolution("85025", self._records["85025"], "source_backed")
        if normalized in {"73721", "mri knee without contrast", "knee mri without contrast", "mri knee no contrast"}:
            return ProcedureResolution("73721", self._records["73721"], "source_backed")
        if normalized in {"73722", "mri knee with contrast", "knee mri with contrast"}:
            return ProcedureResolution("73722", self._records["73722"], "source_backed")
        if normalized in {"mri knee", "knee mri", "mri scan for knee", "knee scan"} or ("mri" in normalized and "knee" in normalized and "contrast" not in normalized):
            return ProcedureResolution(None, None, "ambiguous", ("73721", "73722"), True)
        return ProcedureResolution(None, None, "not_found", (), True)
