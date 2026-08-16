"""NVIDIA Speech NIM adapters used by the permissioned voice gateway."""

from __future__ import annotations

import io
import json
import os
import re
import uuid
import wave
from dataclasses import dataclass
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class NvidiaSpeechError(RuntimeError):
    """A sanitized speech-service failure that never exposes request content."""


def pcm16_to_wav(pcm: bytes, *, sample_rate: int = 16_000) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return output.getvalue()


def speech_safe_text(text: str) -> str:
    """Keep Magpie input pronounceable without changing the grounded meaning."""
    replacements = {"—": ", ", "–": " to ", "‑": "-", "•": ", ", "→": " then "}
    for source, target in replacements.items():
        text = text.replace(source, target)
    return re.sub(r"\s+", " ", text).strip()


def _multipart(
    fields: dict[str, str],
    *,
    file_field: tuple[str, str, str, bytes] | None = None,
) -> tuple[bytes, str]:
    boundary = f"----abyss-{uuid.uuid4().hex}"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.extend([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
            value.encode(),
            b"\r\n",
        ])
    if file_field:
        name, filename, content_type, data = file_field
        parts.extend([
            f"--{boundary}\r\n".encode(),
            (
                f'Content-Disposition: form-data; name="{name}"; '
                f'filename="{filename}"\r\n'
            ).encode(),
            f"Content-Type: {content_type}\r\n\r\n".encode(),
            data,
            b"\r\n",
        ])
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


@dataclass(frozen=True, slots=True)
class NvidiaSpeechConfig:
    asr_base_url: str = "http://127.0.0.1:9001"
    tts_base_url: str = "http://127.0.0.1:9002"
    language: str = "en-US"
    # Neutral is materially more conversational than Calm on the deployed
    # Magpie NIM (about 4.0s versus 6.2s for the same test sentence).
    voice: str = "Magpie-Multilingual.EN-US.Mia.Neutral"
    input_sample_rate: int = 16_000
    output_sample_rate: int = 22_050
    timeout_seconds: float = 60.0

    @classmethod
    def from_env(cls) -> "NvidiaSpeechConfig":
        defaults = cls()
        return cls(
            asr_base_url=os.getenv("NVIDIA_ASR_URL", defaults.asr_base_url).rstrip("/"),
            tts_base_url=os.getenv("NVIDIA_TTS_URL", defaults.tts_base_url).rstrip("/"),
            language=os.getenv("NVIDIA_SPEECH_LANGUAGE", defaults.language),
            voice=os.getenv("NVIDIA_TTS_VOICE", defaults.voice),
            input_sample_rate=int(os.getenv("NVIDIA_ASR_SAMPLE_RATE", defaults.input_sample_rate)),
            output_sample_rate=int(os.getenv("NVIDIA_TTS_SAMPLE_RATE", defaults.output_sample_rate)),
            timeout_seconds=float(os.getenv("NVIDIA_SPEECH_TIMEOUT", defaults.timeout_seconds)),
        )


class NvidiaSpeechClient:
    def __init__(self, config: NvidiaSpeechConfig | None = None) -> None:
        self.config = config or NvidiaSpeechConfig.from_env()

    def transcribe_pcm(self, pcm: bytes) -> str:
        if not pcm:
            return ""
        wav = pcm16_to_wav(pcm, sample_rate=self.config.input_sample_rate)
        body, content_type = _multipart(
            {"language": self.config.language},
            file_field=("file", "utterance.wav", "audio/wav", wav),
        )
        request = Request(
            f"{self.config.asr_base_url}/v1/audio/transcriptions",
            data=body,
            headers={"Content-Type": content_type, "Accept": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.config.timeout_seconds) as response:
                payload = json.loads(response.read())
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
            raise NvidiaSpeechError("NVIDIA Parakeet transcription failed") from error
        text = payload.get("text") if isinstance(payload, dict) else None
        if not isinstance(text, str):
            raise NvidiaSpeechError("NVIDIA Parakeet returned an invalid response")
        return text.strip()

    def stream_speech(self, text: str, on_chunk: Callable[[bytes], None]) -> None:
        spoken = speech_safe_text(text)
        if not spoken:
            return
        body, content_type = _multipart({
            "text": spoken,
            "language": self.config.language,
            "voice": self.config.voice,
            "sample_rate_hz": str(self.config.output_sample_rate),
        })
        request = Request(
            f"{self.config.tts_base_url}/v1/audio/synthesize_online",
            data=body,
            headers={"Content-Type": content_type, "Accept": "application/octet-stream"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.config.timeout_seconds) as response:
                while chunk := response.read(16_384):
                    on_chunk(chunk)
        except (HTTPError, URLError, TimeoutError) as error:
            raise NvidiaSpeechError("NVIDIA Magpie speech synthesis failed") from error

    def health(self) -> dict[str, bool]:
        status: dict[str, bool] = {}
        for name, base_url in (
            ("parakeet", self.config.asr_base_url),
            ("magpie", self.config.tts_base_url),
        ):
            try:
                with urlopen(
                    f"{base_url}/v1/health/ready", timeout=min(3.0, self.config.timeout_seconds)
                ) as response:
                    status[name] = response.status == 200
            except (HTTPError, URLError, TimeoutError):
                status[name] = False
        return status
