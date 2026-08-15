"""Minimal authenticated client for the NemoClaw Hermes gateway."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class HermesError(RuntimeError):
    """A sanitized Hermes gateway error that never includes credentials."""


@dataclass(frozen=True, slots=True)
class HermesConfig:
    base_url: str
    api_key: str
    model: str
    timeout_seconds: float = 180.0

    @classmethod
    def from_env(cls) -> "HermesConfig":
        base_url = os.getenv("HERMES_BASE_URL", "http://127.0.0.1:8642/v1").rstrip("/")
        api_key = os.getenv("HERMES_API_KEY", "")
        model = os.getenv(
            "HERMES_MODEL", "nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4"
        )
        if not api_key:
            raise HermesError("HERMES_API_KEY is not set")
        return cls(base_url=base_url, api_key=api_key, model=model)


class HermesClient:
    def __init__(self, config: HermesConfig | None = None) -> None:
        self.config = config or HermesConfig.from_env()

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 512,
        temperature: float = 0.0,
    ) -> str:
        if not messages:
            raise ValueError("at least one message is required")

        payload = {
            "model": self.config.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        response = self._post("/chat/completions", payload)
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise HermesError("Hermes returned an unexpected response shape") from error
        if not isinstance(content, str) or not content.strip():
            raise HermesError("Hermes returned no final text content")
        return content

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            f"{self.config.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.config.timeout_seconds) as response:
                return json.load(response)
        except HTTPError as error:
            raise HermesError(f"Hermes gateway returned HTTP {error.code}") from error
        except URLError as error:
            raise HermesError("Cannot reach Hermes; check the private SSH tunnel") from error
        except json.JSONDecodeError as error:
            raise HermesError("Hermes returned invalid JSON") from error
