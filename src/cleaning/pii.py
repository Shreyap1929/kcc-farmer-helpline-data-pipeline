"""
PII Detection and Redaction Module (Step 12).
Redacts Indian mobile numbers while strictly preserving helpline/scheme numbers.
"""
import re
from src.cleaning.constants import DEV_TO_ASCII_DIGITS, PHONE_NUMBER_RE, HELPLINE_PREFIXES
from src.cleaning.text_utils import clean_unicode_and_ws


def redact_phone_numbers(text: str | None) -> tuple[str, bool, list[str]]:
    """
    Detect Indian mobile numbers (in ASCII or Devanagari digits).
    Replace matches with [PHONE].
    Preserves toll-free and scheme shortcodes (1800*, 1947, 14447, 155261).
    Returns (cleaned_text, was_redacted, list_of_redacted_numbers).
    """
    if not text:
        return text or "", False, []

    # Map Devanagari digits to ASCII for uniform regex matching
    text_ascii = text.translate(DEV_TO_ASCII_DIGITS)
    matches = list(PHONE_NUMBER_RE.finditer(text_ascii))
    if not matches:
        return text, False, []

    spans_to_replace: list[tuple[int, int]] = []
    redacted_numbers: list[str] = []

    for m in matches:
        raw_match = m.group(0)
        digits_only = re.sub(r"[\s-]", "", raw_match)
        # Check against helpline numbers
        if any(digits_only.startswith(h) for h in HELPLINE_PREFIXES):
            continue
        spans_to_replace.append((m.start(), m.end()))
        redacted_numbers.append(digits_only)

    if not spans_to_replace:
        return text, False, []

    # Replace from back to front so character indices remain valid
    chars = list(text)
    for start, end in reversed(spans_to_replace):
        chars[start:end] = list("[PHONE]")

    redacted_str = "".join(chars)
    # Ensure no leading/trailing whitespace after substitution
    return clean_unicode_and_ws(redacted_str), True, redacted_numbers
