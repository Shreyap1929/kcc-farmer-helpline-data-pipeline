"""
One triage call end to end: text + caller profile -> embedding -> signals,
crop, classifier -> retrieval -> gate -> decision.
"""
from __future__ import annotations

import time
from functools import lru_cache
from typing import Callable

import numpy as np
import yaml

from src.triage.config import CONFIG_DIR, load_config
from src.triage.crops import detect_crops
from src.triage.expansion import expand_query
from src.triage.gate import Gate, GateInput
from src.triage.policy import QuestionSignals, question_signals


def _union_signals(*items: QuestionSignals) -> QuestionSignals:
    """Preserve every original/translated safety keyword without duplicate terms."""
    merged = QuestionSignals()
    for field in QuestionSignals.__dataclass_fields__:
        setattr(merged, field, list(dict.fromkeys(
            term for item in items for term in getattr(item, field)
        )))
    return merged


@lru_cache(maxsize=1)
def _season_map() -> dict[int, str]:
    with open(CONFIG_DIR / "season_map.yaml", "r", encoding="utf-8") as f:
        return {int(k): v for k, v in yaml.safe_load(f)["months"].items()}


def season_for_month(month: int | None) -> str | None:
    return _season_map().get(int(month)) if month else None


class TriageEngine:
    def __init__(self, retriever, classifier, gate: Gate, embed: Callable[[list[str]], np.ndarray]):
        self.retriever = retriever
        self.classifier = classifier
        self.gate = gate
        self.embed = embed

    @classmethod
    def load(cls, cutoff: str | None = None) -> "TriageEngine":
        # Heavy imports kept local so the API module imports instantly in tests.
        from src.triage.answerability import AnswerPolicy
        from src.triage.classifier import QueryClassifier
        from src.triage.embeddings import embed_texts
        from src.triage.retrieval import Retriever

        # The answer policy is used only if its evaluation adopted it (and config allows).
        policy = AnswerPolicy.load() if load_config()["gate"].get("use_answer_policy", True) else None
        engine = cls(Retriever.from_views(cutoff=cutoff), QueryClassifier.load(),
                     Gate(answer_policy=policy), embed_texts)
        # Load the sentence model now, so the first real call is not ~9 s slower.
        engine.triage("warm-up")
        return engine

    def triage(self, text: str, district: str | None = None, crop: str | None = None,
               month: int | None = None, *, translated_text: str | None = None,
               retrieval_mode: str = "expanded") -> dict:
        start = time.perf_counter()
        text = (text or "").strip()
        if retrieval_mode not in {"plain", "expanded", "translate"}:
            raise ValueError("retrieval_mode must be plain, expanded, or translate")
        is_devanagari = any("\u0900" <= char <= "\u097f" for char in text)
        if retrieval_mode == "translate" and is_devanagari and not (translated_text or "").strip():
            raise ValueError("translated_text is required for translate-first retrieval")
        # Keep the historic expanded path as the default. English is unchanged
        # for all modes; translation affects retrieval/classification only.
        if not is_devanagari:
            retrieval_text = text
        elif retrieval_mode == "plain":
            retrieval_text = text
        elif retrieval_mode == "translate":
            retrieval_text = translated_text.strip()
        else:
            retrieval_text = expand_query(text)
        vec = self.embed([retrieval_text])[0]
        original_signals = question_signals(text)
        signals = _union_signals(original_signals, question_signals(translated_text)) \
            if translated_text and is_devanagari else original_signals
        translated_crops = detect_crops(translated_text) if is_devanagari and translated_text else []
        crops_mentioned = list(dict.fromkeys(detect_crops(text) + translated_crops))
        prediction = self.classifier.predict_one(retrieval_text, vec)

        # Resolve the crop once so retrieval can boost matching records.
        probe = GateInput(text, signals, crops_mentioned, prediction, hits=[], profile_crop=crop)
        crop_used, _ = self.gate.resolve_crop(probe)
        season = season_for_month(month)
        hits = self.retriever.search(vec, crops=[crop_used], districts=[district], seasons=[season])

        decision = self.gate.decide(
            GateInput(text, signals, crops_mentioned, prediction, hits, profile_crop=crop)
        )
        out = decision.to_dict()
        query = {"text": text, "district": district, "crop": crop, "month": month, "season": season,
                 "retrieval_text": retrieval_text}
        if retrieval_mode != "expanded":
            query["retrieval_mode"] = retrieval_mode
        if translated_text and is_devanagari:
            query["translated_text"] = translated_text
        out.update({
            "query": query,
            "prediction": prediction,
            "signals": {
                "live_market": signals.live_market,
                "live_weather": signals.live_weather,
                "scheme": signals.scheme,
                "dose": signals.dose,
                "crops_mentioned": crops_mentioned,
            },
            "latency_ms": round((time.perf_counter() - start) * 1000, 1),
        })
        return out

    def meta(self) -> dict:
        rec = self.retriever.records
        districts = (
            rec.loc[rec["district_clean"].fillna("") != "", ["district_clean", "district_display"]]
            .drop_duplicates("district_clean")
            .sort_values("district_display")
        )
        return {
            "districts": [{"value": r.district_clean, "label": r.district_display} for r in districts.itertuples()],
            "crops": sorted(self.classifier.crop.classes),
            "kb_records": len(self.retriever),
            "kb_questions": int(len(self.retriever.questions)),
            "embedding_model": load_config()["embedding"]["model"],
            "thresholds": {
                k: self.gate.t[k] for k in ("answer_min_similarity", "out_of_scope_max_similarity", "crop_min_confidence")
            },
            "answer_policy": None if self.gate.answer_policy is None else {
                "mode": self.gate.answer_policy.mode,
                "threshold": self.gate.answer_policy.threshold,
                "decision": self.gate.answer_policy.meta.get("decision"),
            },
        }
