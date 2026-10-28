"""Detect farmer message language using the existing Stage 1 word lists."""
from __future__ import annotations

from src.cleaning.language import classify_answer_lang, detect_script


def detect_language(text: str | None) -> str:
    """Return mr, hi or en; Latin script is treated as English per product rules."""
    script = detect_script(text)
    if script == "latin":
        return "en"
    lang, _confidence = classify_answer_lang(text, script)
    return {"marathi": "mr", "hindi": "hi"}.get(lang, "mr" if script == "devanagari" else "en")
