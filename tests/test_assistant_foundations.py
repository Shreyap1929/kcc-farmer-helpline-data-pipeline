"""Offline tests for language, Groq adapters, configuration and TTS fallback."""
from types import SimpleNamespace
import asyncio

import pytest

from src.assistant import config, language, stt, translate, tts


def test_language_detection_handles_english_marathi_and_hindi():
    assert language.detect_language("How do I grow cotton?") == "en"
    assert language.detect_language("कापसाला काय करावे नाही") == "mr"
    assert language.detect_language("फसल में दवा नहीं है") == "hi"


def test_empty_text_defaults_to_english():
    assert language.detect_language("") == "en"


def test_config_has_limits_and_models():
    cfg = config.get_config()
    assert cfg["limits"] == {"max_audio_seconds": 60, "max_audio_bytes": 10_485_760, "max_text_chars": 1000}
    assert cfg["groq"]["transcription_model"]
    assert cfg["groq"]["translation_model"]
    assert cfg["groq"]["chat_model"]


def test_no_key_returns_no_client_without_loading_env(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: None)
    assert config.get_groq_client() is None


class FakeGroq:
    def __init__(self):
        self.audio = SimpleNamespace(
            transcriptions=SimpleNamespace(create=self.transcribe),
            translations=SimpleNamespace(create=self.translate_audio),
        )
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.translate_text))
        self.calls = []

    def transcribe(self, **kwargs):
        self.calls.append(("transcribe", kwargs))
        return SimpleNamespace(text="cotton question", language="mr", duration=4.2)

    def translate_audio(self, **kwargs):
        self.calls.append(("translate_audio", kwargs))
        return SimpleNamespace(text="How to grow cotton?")

    def translate_text(self, **kwargs):
        self.calls.append(("translate_text", kwargs))
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="How to grow cotton?"))])


def test_transcription_returns_text_language_and_duration():
    client = FakeGroq()
    got = stt.transcribe_audio(b"fake audio", "note.webm", client=client)
    assert got == {"text": "cotton question", "language": "mr", "duration": 4.2}
    assert client.calls[0][1]["model"] == config.get_config()["groq"]["transcription_model"]


def test_audio_translation_uses_translation_endpoint():
    client = FakeGroq()
    assert stt.translate_audio(b"fake audio", "note.webm", client=client) == "How to grow cotton?"
    assert client.calls[0][0] == "translate_audio"


@pytest.mark.parametrize("audio,content_type", [(b"", "audio/webm"), (b"x" * 10_485_761, "audio/webm"), (b"x", "text/plain")])
def test_audio_validation_rejects_empty_oversize_and_invalid_type(audio, content_type):
    with pytest.raises(ValueError):
        stt.transcribe_audio(audio, "bad", content_type)


def test_transcription_rejects_duration_over_limit():
    client = FakeGroq()
    client.audio.transcriptions.create = lambda **kwargs: SimpleNamespace(text="too long", language="mr", duration=61)
    with pytest.raises(ValueError, match="60 second"):
        stt.transcribe_audio(b"fake audio", "long.webm", client=client)


def test_translate_english_is_noop_and_non_english_is_translation_only():
    client = FakeGroq()
    assert translate.translate_to_english("cotton", "en", client=client) == "cotton"
    assert translate.translate_to_english("कापसाला काय करावे", "mr", client=client) == "How to grow cotton?"
    args = client.calls[0][1]
    assert args["temperature"] == 0
    assert "Translate" in args["messages"][0]["content"]


def test_translation_falls_back_to_input_without_api_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: None)
    assert translate.translate_to_english("नमस्कार", "mr") == "नमस्कार"


def test_tts_uses_selected_provider_and_returns_audio(monkeypatch):
    async def fake_edge(text, voice):
        assert voice == "mr-IN-AarohiNeural"
        return b"mp3"

    monkeypatch.setattr(tts, "_edge_synthesize", fake_edge)
    assert asyncio.run(tts.synthesize("नमस्कार", "mr", provider="edge")) == b"mp3"


def test_tts_failure_returns_text_only(monkeypatch):
    async def fail(*args):
        raise RuntimeError("network unavailable")

    monkeypatch.setattr(tts, "_edge_synthesize", fail)
    assert asyncio.run(tts.synthesize("नमस्कार", "mr", provider="edge")) is None
