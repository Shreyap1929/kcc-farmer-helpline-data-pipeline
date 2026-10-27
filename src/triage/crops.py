"""
Crop mention detection from free text, using config/crop_lexicon.yaml.
"""
from __future__ import annotations

from functools import lru_cache

from src.triage.config import load_crop_lexicon
from src.triage.policy import Lexicon, tokenize


@lru_cache(maxsize=1)
def _lexicons() -> dict[str, Lexicon]:
    return {crop: Lexicon(variants) for crop, variants in load_crop_lexicon().items()}


def detect_crops(text: str | None) -> list[str]:
    """
    Canonical crop labels mentioned in the text, most specific first.

    "green gram" must not also count as Bengal gram (whose variants include the
    bare token "gram"), so a crop whose every hit is a word inside another
    crop's multi-word hit is dropped.
    """
    tokens = tokenize(text)
    hits = {crop: lex.find(tokens) for crop, lex in _lexicons().items()}
    hits = {crop: h for crop, h in hits.items() if h}
    phrase_words = {
        crop: {w for h in h_list if " " in h for w in h.split()} for crop, h_list in hits.items()
    }
    kept = []
    for crop, h_list in hits.items():
        covered_by_other = any(
            all(h in words for h in h_list)
            for other, words in phrase_words.items()
            if other != crop
        )
        if not covered_by_other:
            kept.append((crop, max(len(h) for h in h_list)))
    kept.sort(key=lambda x: -x[1])
    return [crop for crop, _ in kept]
