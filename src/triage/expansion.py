"""
Glossary query expansion for Marathi/Hindi questions.

The knowledge base holds English call-taker summaries, and multilingual
embeddings alone match Devanagari questions to them poorly. Appending the
English names of recognised crops and farm terms gives the embedding an
anchor in the KB's language:

    "कापसावर पांढरी माशी आली आहे काय फवारणी करावी"
 -> "कापसावर पांढरी माशी आली आहे काय फवारणी करावी | whitefly spray cotton"

Only Devanagari input is expanded, so English questions are embedded exactly
as the knowledge base and the threshold calibration saw them.
"""
from __future__ import annotations

import re
from functools import lru_cache

import yaml

from src.triage.config import CONFIG_DIR, load_crop_lexicon
from src.triage.crops import detect_crops
from src.triage.policy import Lexicon, tokenize

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")


@lru_cache(maxsize=1)
def _glossary() -> dict[str, Lexicon]:
    with open(CONFIG_DIR / "query_glossary.yaml", "r", encoding="utf-8") as f:
        terms = yaml.safe_load(f)["terms"]
    return {english: Lexicon(variants) for english, variants in terms.items()}


def _english_crop_name(crop: str) -> str:
    return next((v for v in load_crop_lexicon()[crop] if v.isascii()), crop)


def english_terms(text: str) -> list[str]:
    tokens = tokenize(text)
    terms = [english for english, lex in _glossary().items() if lex.find(tokens)]
    terms += [_english_crop_name(c) for c in detect_crops(text)]
    return terms


def expand_query(text: str) -> str:
    if not text or not _DEVANAGARI.search(text):
        return text
    terms = english_terms(text)
    return f"{text} | {' '.join(terms)}" if terms else text
