"""ABYSS runtime policy shared by API and model adapters."""

import os
from functools import lru_cache
from pathlib import Path
from typing import Mapping

from abyss.agent import SYSTEM_PROMPT as SYSTEM_PROMPT
from abyss.knowledge import (
    HospitalKnowledgeCatalog,
    SeededHospitalKnowledgeCatalog,
    SQLiteHospitalKnowledgeCatalog,
)

OUTPUT_SAMPLE_RATE = 24_000
LIVE_MODEL = os.getenv("GEMINI_LIVE_MODEL", "gemini-2.5-flash-native-audio-preview-12-2025")


@lru_cache(maxsize=1)
def gemini_api_key() -> str | None:
    """Temporary compatibility hook for the imported audio/document adapters."""
    return os.getenv("GEMINI_API_KEY")


def hospital_knowledge_catalog(
    environment: Mapping[str, str] | None = None,
) -> HospitalKnowledgeCatalog:
    """Resolve the hospital catalog without silently masking bad configuration.

    A synthetic fixture is suitable only when no external catalog was requested.
    If ``ABYSS_KNOWLEDGE_DB`` is present, the SQLite adapter validates the path
    and schema immediately and raises a visible configuration error on failure.
    """
    values = environment if environment is not None else os.environ
    configured = values.get("ABYSS_KNOWLEDGE_DB")
    if configured is None or not configured.strip():
        return SeededHospitalKnowledgeCatalog()
    return SQLiteHospitalKnowledgeCatalog(Path(configured.strip()))
