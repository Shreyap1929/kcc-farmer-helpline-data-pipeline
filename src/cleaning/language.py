"""
Script and language detection heuristics (Step 11).
"""
import re
from src.cleaning.constants import HINDI_FUNCTION_WORDS, MARATHI_FUNCTION_WORDS

DEV_RE = re.compile(r"[\u0900-\u097F]")
LAT_RE = re.compile(r"[a-zA-Z]")
DEV_WORDS_RE = re.compile(r"[\u0900-\u097F]+")


def detect_script(text: str | None) -> str:
    """
    Detect script from the share of Devanagari characters among Devanagari + Latin characters.
    above 0.9 = 'devanagari'
    below 0.1 = 'latin'
    else 'mixed'
    'none' if no letters.
    """
    if not text:
        return "none"
    dev_count = len(DEV_RE.findall(text))
    lat_count = len(LAT_RE.findall(text))
    total = dev_count + lat_count
    if total == 0:
        return "none"
    ratio = dev_count / total
    if ratio > 0.9:
        return "devanagari"
    elif ratio < 0.1:
        return "latin"
    else:
        return "mixed"


def classify_answer_lang(text: str | None, script: str) -> tuple[str, float]:
    """
    Step 11 First-Pass Language Heuristic:
    - 'english' if ans_script == 'latin' (confidence 1.0)
    - For Devanagari/mixed text, count unambiguous function words:
        Marathi: आहे, आहेत, नाही, करावी, करावा, द्यावे, घ्यावे, मध्ये
        Hindi: है, हैं, नहीं, करें, कृपया, में, आपको
    - 'marathi' or 'hindi' if one side has at least 2 hits and at least twice the other.
    - Otherwise 'unclear'.
    - lang_confidence: winning share of function word hits, or 0.0 if 0 hits.
    """
    if script == "latin":
        return "english", 1.0
    if not text or script == "none":
        return "unclear", 0.0

    words = DEV_WORDS_RE.findall(text)
    m_hits = sum(1 for w in words if w in MARATHI_FUNCTION_WORDS)
    h_hits = sum(1 for w in words if w in HINDI_FUNCTION_WORDS)
    total_hits = m_hits + h_hits

    if m_hits >= 2 and m_hits >= 2 * h_hits:
        conf = round(m_hits / total_hits, 4) if total_hits > 0 else 1.0
        return "marathi", conf
    elif h_hits >= 2 and h_hits >= 2 * m_hits:
        conf = round(h_hits / total_hits, 4) if total_hits > 0 else 1.0
        return "hindi", conf
    else:
        conf = round(max(m_hits, h_hits) / total_hits, 4) if total_hits > 0 else 0.0
        return "unclear", conf
