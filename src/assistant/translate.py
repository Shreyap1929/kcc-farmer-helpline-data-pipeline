"""Translation-only LLM adapter: farmer questions to English, expert answers to the farmer's language."""
from __future__ import annotations

from src.assistant.config import chat_options, get_config, get_groq_client

LANGUAGE_NAMES = {"en": "English", "mr": "Marathi", "hi": "Hindi"}


class AssistantUnavailable(RuntimeError):
    """Raised when a configured external assistant operation fails."""


def translate_text(text: str, target_language: str, *, client=None, max_tokens: int = 512) -> str:
    """Translate without adding advice. Raises AssistantUnavailable when Groq is missing or fails."""
    text = (text or "").strip()
    if not text:
        return text
    if len(text) > get_config()["limits"]["max_text_chars"] * 2:
        raise ValueError("text is too long to translate")
    client = client if client is not None else get_groq_client()
    if client is None:
        raise AssistantUnavailable("translation unavailable: Groq is not configured")
    try:
        result = client.chat.completions.create(
            **chat_options(),
            max_completion_tokens=max_tokens,
            messages=[
                {"role": "system", "content": (
                    f"Translate the user's message into {LANGUAGE_NAMES[target_language]}. Return only the "
                    "translation. Do not answer the question, add facts, or give agricultural advice. "
                    "Keep every number, unit, product and variety name exactly as given."
                )},
                {"role": "user", "content": text},
            ],
        )
        translated = (result.choices[0].message.content or "").strip()
        if not translated:
            raise AssistantUnavailable("translation returned no text")
        return translated
    except AssistantUnavailable:
        raise
    except Exception as exc:
        raise AssistantUnavailable("translation service unavailable") from exc


def translate_to_english(text: str, language: str, *, client=None) -> str:
    """Farmer question to English for the expert; without Groq the original text is kept."""
    text = (text or "").strip()
    if not text or language == "en":
        return text
    if len(text) > get_config()["limits"]["max_text_chars"]:
        raise ValueError("text exceeds the 1000 character limit")
    client = client if client is not None else get_groq_client()
    if client is None:
        return text
    return translate_text(text, "en", client=client)
