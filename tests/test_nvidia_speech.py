import io
import json
import os
import unittest
import wave
from unittest.mock import patch

from services.api.app.nvidia_speech import (
    NvidiaSpeechClient,
    NvidiaSpeechConfig,
    pcm16_to_wav,
    speech_safe_text,
)


class FakeResponse:
    def __init__(self, payload: bytes, *, status: int = 200, chunk_size: int | None = None):
        self.payload = payload
        self.status = status
        self.offset = 0
        self.chunk_size = chunk_size

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size: int = -1) -> bytes:
        if self.chunk_size is not None:
            size = min(size, self.chunk_size)
        if size < 0:
            size = len(self.payload) - self.offset
        result = self.payload[self.offset:self.offset + size]
        self.offset += len(result)
        return result


class NvidiaSpeechTests(unittest.TestCase):
    def test_pcm16_is_wrapped_as_mono_16khz_wav(self) -> None:
        wav_bytes = pcm16_to_wav(b"\x01\x00\xff\x7f")
        with wave.open(io.BytesIO(wav_bytes), "rb") as wav:
            self.assertEqual(wav.getnchannels(), 1)
            self.assertEqual(wav.getsampwidth(), 2)
            self.assertEqual(wav.getframerate(), 16_000)
            self.assertEqual(wav.readframes(2), b"\x01\x00\xff\x7f")

    def test_config_uses_defaults_and_environment_overrides(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            defaults = NvidiaSpeechConfig.from_env()
        self.assertEqual(defaults.output_sample_rate, 22_050)
        self.assertEqual(defaults.asr_base_url, "http://127.0.0.1:9001")
        with patch.dict(os.environ, {"NVIDIA_TTS_SAMPLE_RATE": "16000"}, clear=True):
            overridden = NvidiaSpeechConfig.from_env()
        self.assertEqual(overridden.output_sample_rate, 16_000)

    def test_transcription_posts_wav_and_returns_text(self) -> None:
        response = FakeResponse(json.dumps({"text": "Book a blood test. "}).encode())
        with patch("services.api.app.nvidia_speech.urlopen", return_value=response) as mocked:
            text = NvidiaSpeechClient(NvidiaSpeechConfig()).transcribe_pcm(b"\x00\x00" * 4000)
        self.assertEqual(text, "Book a blood test.")
        request = mocked.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:9001/v1/audio/transcriptions")
        self.assertIn(b'filename="utterance.wav"', request.data)
        self.assertIn(b"RIFF", request.data)

    def test_magpie_output_is_forwarded_in_chunks(self) -> None:
        response = FakeResponse(b"abcdefghij", chunk_size=4)
        chunks: list[bytes] = []
        with patch("services.api.app.nvidia_speech.urlopen", return_value=response) as mocked:
            NvidiaSpeechClient(NvidiaSpeechConfig()).stream_speech(
                "Cost — estimate", chunks.append
            )
        self.assertEqual(chunks, [b"abcd", b"efgh", b"ij"])
        request = mocked.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:9002/v1/audio/synthesize_online")
        self.assertIn(b"Cost , estimate", request.data)
        self.assertIn(b"22050", request.data)

    def test_speech_safe_text_preserves_meaning_without_unsupported_punctuation(self) -> None:
        self.assertEqual(speech_safe_text("A — B → C"), "A , B then C")


if __name__ == "__main__":
    unittest.main()
