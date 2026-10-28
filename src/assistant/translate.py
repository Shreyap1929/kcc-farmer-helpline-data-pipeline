"""Translation-only LLM adapter for English retrieval queries."""
from __future__ import annotations

from src.assistant.config import get_config, get_groq_client


class AssistantUnavailable(RuntimeError):
    """Raised when a configured external assistant operation fails."""


def translate_to_english(text: str, language: str, *, client=None) -> str:
    """Translate farmer text without adding advice; empty credentials return input."""
    text = (text or "").strip()
    if not text or language == "en":
        return text
    if len(text) > get_config()["limits"]["max_text_chars"]:
        raise ValueError("text exceeds the 1000 character limit")
    client = client if client is not None else get_groq_client()
    if client is None:
        return text
    cfg = get_config()["groq"]
    try:
        result = client.chat.completions.create(
            model=cfg["chat_model"],
            temperature=0,
            max_completion_tokens=512,
            messages=[
                {"role": "system", "content": (
                    "Translate the user's message into English. Return only the translation. "
                    "Do not answer the question, add facts, or give agricultural advice."
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
