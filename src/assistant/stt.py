"""Groq Whisper transcription and English translation adapters."""
from __future__ import annotations

import io
from pathlib import Path

from src.assistant.config import get_config, get_groq_client
from src.assistant.translate import AssistantUnavailable


ALLOWED_AUDIO_TYPES = {"audio/webm", "audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp4", "audio/ogg"}


def _validate_audio(audio: bytes, content_type: str) -> None:
    limits = get_config()["limits"]
    if not audio:
        raise ValueError("audio is empty")
    if len(audio) > limits["max_audio_bytes"]:
        raise ValueError("audio exceeds the 10 MB limit")
    if content_type.split(";", 1)[0].lower() not in ALLOWED_AUDIO_TYPES:
        raise ValueError("unsupported audio format")


def _audio_file(audio: bytes, filename: str):
    return (Path(filename).name, io.BytesIO(audio))


def transcribe_audio(audio: bytes, filename: str, content_type: str = "audio/webm", *, client=None) -> dict:
    """Return original transcript and detected language; no audio is persisted."""
    _validate_audio(audio, content_type)
    client = client if client is not None else get_groq_client()
    if client is None:
        raise AssistantUnavailable("voice unavailable: Groq is not configured")
    cfg = get_config()["groq"]
    try:
        result = client.audio.transcriptions.create(
            file=_audio_file(audio, filename),
            model=cfg["transcription_model"],
            response_format="verbose_json",
        )
        transcript = (result.text or "").strip()
        if not transcript:
            raise AssistantUnavailable("transcription returned no text")
        duration = getattr(result, "duration", None)
        if duration is not None and duration > get_config()["limits"]["max_audio_seconds"]:
            raise ValueError("audio exceeds the 60 second limit")
        return {"text": transcript, "language": getattr(result, "language", None), "duration": duration}
    except (ValueError, AssistantUnavailable):
        raise
    except Exception as exc:
        raise AssistantUnavailable("voice unavailable: transcription failed") from exc


def translate_audio(audio: bytes, filename: str, content_type: str = "audio/webm", *, client=None) -> str:
    """Use Whisper's translation endpoint to translate audio directly to English."""
    _validate_audio(audio, content_type)
    client = client if client is not None else get_groq_client()
    if client is None:
        raise AssistantUnavailable("voice unavailable: Groq is not configured")
    try:
        result = client.audio.translations.create(
            file=_audio_file(audio, filename),
            model=get_config()["groq"]["translation_model"],
            response_format="json",
        )
        text = (result.text or "").strip()
        if not text:
            raise AssistantUnavailable("audio translation returned no text")
        return text
    except AssistantUnavailable:
        raise
    except Exception as exc:
        raise AssistantUnavailable("voice unavailable: audio translation failed") from exc
