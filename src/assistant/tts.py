"""Text-to-speech providers behind one async interface; failures stay text-only."""
from __future__ import annotations

import asyncio
from io import BytesIO

from src.assistant.config import get_config


async def _edge_synthesize(text: str, voice: str) -> bytes:
    import edge_tts

    stream = edge_tts.Communicate(text, voice)
    parts = []
    async for item in stream.stream():
        if item["type"] == "audio":
            parts.append(item["data"])
    return b"".join(parts)


def _gtts_synthesize(text: str, lang: str) -> bytes:
    from gtts import gTTS

    result = BytesIO()
    gTTS(text=text, lang=lang).write_to_fp(result)
    return result.getvalue()


async def synthesize(text: str, language: str, *, provider: str | None = None) -> bytes | None:
    """Return MP3 data, or None when TTS is unavailable (caller keeps the text)."""
    text = (text or "").strip()
    if not text or len(text) > get_config()["limits"]["max_text_chars"]:
        return None
    cfg = get_config()["tts"]
    chosen = provider or cfg["provider"]
    try:
        if chosen == "edge":
            voice = cfg["edge"].get(language)
            audio = await _edge_synthesize(text, voice) if voice else None
            if audio or provider:
                return audio or None
            # Edge's endpoint is unofficial and has rejected older clients (HTTP 403);
            # fall back to gTTS rather than leave a voice caller without audio.
            chosen = "gtts"
        if chosen == "gtts":
            lang = cfg["gtts"].get(language)
            return await asyncio.to_thread(_gtts_synthesize, text, lang) if lang else None
        raise ValueError(f"unknown TTS provider: {chosen}")
    except Exception:
        if chosen == "edge" and not provider:
            return await synthesize(text, language, provider="gtts")
        return None
