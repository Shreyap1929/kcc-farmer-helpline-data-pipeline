"""
Text processing and Unicode normalization utilities.
"""
import re
import unicodedata
from src.cleaning.constants import CORE_QUERY_PREFIX_RE, DEV_TO_ASCII_DIGITS

# All Unicode whitespace characters and zero-width characters to strip from boundaries
ZERO_WIDTH_AND_WS_CHARS = (
    " \t\r\n\v\f\xa0\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005"
    "\u2006\u2007\u2008\u2009\u200a\u200b\u200c\u200d\u202f\u205f\u3000\ufeff"
)


def clean_unicode_and_ws(val: str | None) -> str:
    """
    Step 5:
    1. Normalise Unicode to NFC.
    2. Replace tabs, newlines, carriage returns, non-breaking spaces, and repeated spaces with a single space.
    3. Strip leading and trailing whitespace and zero-width characters.
    Preserves internal casing, scripts, greetings, and punctuation.
    """
    if val is None or not isinstance(val, str):
        return ""
    val = unicodedata.normalize("NFC", val)
    # Replace tabs, newlines, carriage returns and non-breaking spaces with a regular space
    val = re.sub(r"[\r\n\t\xa0\u1680\u2000-\u200a\u202f\u205f\u3000]+", " ", val)
    # Collapse multiple spaces into one
    val = re.sub(r" +", " ", val)
    # Strip leading/trailing whitespace and zero-width characters
    return val.strip(ZERO_WIDTH_AND_WS_CHARS)


def make_normalized_text(text: str | None) -> str:
    """
    Create q_norm / ans_norm:
    Lowercase Latin, remove punctuation and symbols, collapse spaces.
    Used for template detection and deduplication keys.
    """
    if not text:
        return ""
    t = text.lower()
    # Replace punctuation and symbols with space (keeping alphanumeric letters and digits in any script)
    t = re.sub(r"[^\w\s]", " ", t)
    # Collapse underscore (matched by \w) and whitespace
    t = re.sub(r"[\s_]+", " ", t)
    return t.strip()


def extract_q_core(q_clean: str) -> str:
    """
    Extract q_core by removing boilerplate query prefixes.
    If stripping leaves fewer than 3 characters, keep q_clean.
    """
    if not q_clean:
        return ""
    core = CORE_QUERY_PREFIX_RE.sub("", q_clean).strip(" :-\t")
    if len(core) < 3:
        return q_clean
    return core


def to_ascii_digits(text: str) -> str:
    """
    Convert Devanagari digits (०–९) to ASCII digits (0-9).
    """
    if not text:
        return ""
    return text.translate(DEV_TO_ASCII_DIGITS)
