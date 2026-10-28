"""Detect farmer message language using the existing Stage 1 word lists."""
from __future__ import annotations

from src.cleaning.constants import HINDI_FUNCTION_WORDS, MARATHI_FUNCTION_WORDS
from src.cleaning.language import DEV_WORDS_RE, classify_answer_lang, detect_script


def detect_language(text: str | None) -> str:
    """Return mr, hi or en; Latin script is treated as English per product rules."""
    script = detect_script(text)
    if script == "latin":
        return "en"
    lang, _confidence = classify_answer_lang(text, script)
    return {"marathi": "mr", "hindi": "hi"}.get(lang, "mr" if script == "devanagari" else "en")

# Question words the Stage 1 answer lists lack (they were built from advisor answers).
# Only words that are not shared between the two languages.
MARATHI_QUESTION_WORDS = MARATHI_FUNCTION_WORDS | {
    "काय", "कसे", "कशी", "कसा", "कधी", "कोणते", "कोणती", "कोणता", "माझ्या", "माझी", "माझा", "माझे",
    "आली", "आला", "आले", "पडत", "करावे", "साठी", "झाली", "झाला", "पिकावर", "पिकाला",
}
HINDI_QUESTION_WORDS = HINDI_FUNCTION_WORDS | {
    "क्या", "कैसे", "कब", "किस", "कौन", "मेरी", "मेरा", "मेरे", "रही", "रहा", "रहे", "लिए", "फसल", "चाहिए", "की", "के", "कैसा", "कैसी", "हफ्ते",
}


def reply_language(text: str | None, session_language: str | None) -> str:
    """
    Language to answer in. Devanagari is strong evidence, so Marathi typed into an
    English session gets Marathi back. Latin script is not: farmers often type
    romanized Marathi ("kapus var mashi"), so it keeps the language they picked.
    Inside Devanagari the session choice breaks ties, since short Marathi and Hindi
    questions often share every word.
    """
    script = detect_script(text)
    if script not in {"devanagari", "mixed"}:
        return session_language or "en"
    # The Stage 1 answer heuristic needs two function words; a farmer's question is often
    # one short sentence, so a plain majority of the same word lists decides here.
    words = DEV_WORDS_RE.findall(text)
    marathi = sum(w in MARATHI_QUESTION_WORDS for w in words)
    hindi = sum(w in HINDI_QUESTION_WORDS for w in words)
    if marathi != hindi:
        return "mr" if marathi > hindi else "hi"
    return session_language if session_language in {"mr", "hi"} else "mr"
