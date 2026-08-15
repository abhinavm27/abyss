"""ABYSS runtime policy shared by API and model adapters."""

import os
from functools import lru_cache

from abyss.agent import SYSTEM_PROMPT as SYSTEM_PROMPT

OUTPUT_SAMPLE_RATE = 24_000
LIVE_MODEL = os.getenv("GEMINI_LIVE_MODEL", "gemini-2.5-flash-native-audio-preview-12-2025")


@lru_cache(maxsize=1)
def gemini_api_key() -> str | None:
    """Temporary compatibility hook for the imported audio/document adapters."""
    return os.getenv("GEMINI_API_KEY")
