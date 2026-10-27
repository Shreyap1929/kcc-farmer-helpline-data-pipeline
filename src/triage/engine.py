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
from src.triage.policy import question_signals


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
        from src.triage.classifier import QueryClassifier
        from src.triage.embeddings import embed_texts
        from src.triage.retrieval import Retriever

        engine = cls(Retriever.from_views(cutoff=cutoff), QueryClassifier.load(), Gate(), embed_texts)
        # Load the sentence model now, so the first real call is not ~9 s slower.
        engine.triage("warm-up")
        return engine

    def triage(self, text: str, district: str | None = None, crop: str | None = None,
               month: int | None = None) -> dict:
        start = time.perf_counter()
        text = (text or "").strip()
        # Marathi/Hindi questions get English glossary terms appended before
        # embedding and classification; the gate's signals read the original.
        expanded = expand_query(text)
        vec = self.embed([expanded])[0]
        signals = question_signals(text)
        crops_mentioned = detect_crops(text)
        prediction = self.classifier.predict_one(expanded, vec)

        # Resolve the crop once so retrieval can boost matching records.
        probe = GateInput(text, signals, crops_mentioned, prediction, hits=[], profile_crop=crop)
        crop_used, _ = self.gate.resolve_crop(probe)
        season = season_for_month(month)
        hits = self.retriever.search(vec, crops=[crop_used], districts=[district], seasons=[season])

        decision = self.gate.decide(
            GateInput(text, signals, crops_mentioned, prediction, hits, profile_crop=crop)
        )
        out = decision.to_dict()
        out.update({
            "query": {"text": text, "district": district, "crop": crop, "month": month, "season": season,
                      "retrieval_text": expanded},
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
        }
