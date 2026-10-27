"""
Constants and schema specifications for KCC data cleaning pipeline.
"""
import re

MISSING_TOKENS = frozenset({"", "na", "n/a", "null", "none", "-"})

# Devanagari to ASCII digit translation
DEV_TO_ASCII_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")

# Language detection function words (strictly unambiguous)
MARATHI_FUNCTION_WORDS = frozenset({
    "आहे", "आहेत", "नाही", "करावी", "करावा", "द्यावे", "घ्यावे", "मध्ये"
})

HINDI_FUNCTION_WORDS = frozenset({
    "है", "हैं", "नहीं", "करें", "कृपया", "में", "आपको"
})

# Core query prefix pattern to strip boilerplate prefixes
CORE_QUERY_PREFIX_RE = re.compile(
    r"^(?:FARMER ASKED QUERY ON|FARMER ASKED QUERY ABOUT|FARMER ASKED ABOUT|FARMER ASKED)\b[:\s-]*",
    re.IGNORECASE,
)

# Indian mobile number regex (ASCII digits)
# Allows optional +91 or 91 country code prefix and internal single spaces or hyphens
PHONE_NUMBER_RE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9](?:[\s-]?\d){9}(?!\d)")

# Helpline numbers to preserve (never redact)
HELPLINE_PREFIXES = ("1800", "1947", "14447", "155261")

# Master DataFrame Column Ordering as defined in Section 4 of Specification
MASTER_COLUMNS = [
    # Identity and provenance
    "KCCCallID",
    "source_file",
    "source_row",
    # Raw (unchanged)
    "BlockName",
    "Category",
    "CreatedOn",
    "Crop",
    "DistrictName",
    "KccAns",
    "QueryText",
    "QueryType",
    "Season",
    "Sector",
    "StateName",
    "day",
    "month",
    "year",
    # Time
    "created_on",
    "date",
    "year_month",
    "day_of_week",
    "season_derived",
    "year_i",
    "month_i",
    # Cleaned labels and places
    "query_type_clean",
    "category_clean",
    "crop_clean",
    "sector_clean",
    "district_clean",
    "district_display",
    "block_clean",
    # Cleaned text
    "q_clean",
    "q_core",
    "q_norm",
    "ans_clean",
    "ans_norm",
    "ans_digits_ascii",
    "q_len",
    "ans_len",
    # Language
    "ans_script",
    "answer_lang",
    "lang_confidence",
    # Flags
    "flag_q_empty",
    "flag_ans_empty",
    "flag_incomplete_call",
    "flag_weather_template",
    "flag_mandi_template",
    "flag_dated_answer",
    "flag_q_too_long",
    "flag_ans_too_long",
    "flag_sector_numeric",
    "flag_district_invalid",
    "flag_date_mismatch",
    "flag_pii_phone_redacted",
    "is_valid_qa",
    "exclude_reason",
    # Duplicates
    "qa_key",
    "qa_dup_count",
    "q_key",
    "q_dup_count",
    "is_first_occurrence",
]
