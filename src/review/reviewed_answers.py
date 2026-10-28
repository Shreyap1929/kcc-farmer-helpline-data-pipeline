"""
Reuse expert answers for repeat questions (Stage 4 feedback loop).

The historical KB cannot answer Marathi/Hindi questions (cross-lingual parity 0/80:
Marathi questions sit at 0.86-0.91 against English KB questions, below the 0.98
threshold). Expert cases, however, keep the farmer's own words, so a later question in
the same language can be matched like for like.

A reviewed answer is served only when every condition holds:
- the expert's answer was tagged reusable (neither chemical nor time-sensitive);
- the gate sent the new question to an expert for a reason that is not about chemicals
  (low confidence or crop mismatch), and the question asks for no dose, price, weather
  or scheme status;
- same language as the reviewed case, same crops mentioned;
- embedding similarity >= review.reuse_min_similarity (see reports/stage4/reviewed_reuse_report.md).
"""
from __future__ import annotations

import threading
from typing import Callable

import numpy as np

from src.assistant.config import get_config
from src.assistant.sessions import SessionStore
from src.triage.crops import detect_crops
from src.triage.policy import question_signals

# Gate reasons that only mean "no close enough historical answer", never "this is risky".
REUSABLE_REASONS = {"LOW_CONFIDENCE", "CROP_MISMATCH"}


def reuse_threshold() -> float:
    return float(get_config()["review"]["reuse_min_similarity"])


def delivered_text(case: dict) -> str:
    """The answer as the farmer received it, without the 'Expert answer for case X:' header."""
    reply = case.get("farmer_reply") or ""
    return reply.split("\n", 1)[1].strip() if "\n" in reply else reply.strip()


class ReviewedAnswers:
    def __init__(self, store: SessionStore, embed: Callable[[list[str]], np.ndarray],
                 threshold: float | None = None):
        self.store, self.embed = store, embed
        self.threshold = reuse_threshold() if threshold is None else threshold
        self._lock = threading.Lock()
        self._cases: list[dict] = []
        self._vectors = np.zeros((0, 0), dtype=np.float32)
        self.refresh()

    def __len__(self) -> int:
        return len(self._cases)

    def refresh(self) -> None:
        cases = [c for c in self.store.list_cases(status="answered", limit=100_000) if c.get("reusable")]
        vectors = self.embed([c["original_text"] for c in cases]) if cases else np.zeros((0, 0), dtype=np.float32)
        with self._lock:
            self._cases, self._vectors = cases, np.asarray(vectors, dtype=np.float32)

    def add(self, case: dict) -> None:
        if case.get("status") != "answered" or not case.get("reusable"):
            return
        vector = np.asarray(self.embed([case["original_text"]]), dtype=np.float32)
        with self._lock:
            self._cases = [*self._cases, case]
            self._vectors = vector if not self._vectors.size else np.vstack([self._vectors, vector])

    def remove(self, case_id: str) -> None:
        with self._lock:
            keep = [i for i, c in enumerate(self._cases) if c["case_id"] != case_id]
            self._cases = [self._cases[i] for i in keep]
            self._vectors = self._vectors[keep] if self._vectors.size else self._vectors

    def match(self, text: str, language: str, decision: dict) -> dict | None:
        """The reviewed case to serve for this question, or None."""
        if decision.get("route") != "EXPERT_REVIEW" or not self._cases:
            return None
        codes = {r.get("code") if isinstance(r, dict) else getattr(r, "code", None)
                 for r in decision.get("reasons") or []}
        if not codes or not codes <= REUSABLE_REASONS:
            return None
        signals = question_signals(text)
        if signals.dose or signals.is_live or signals.scheme:
            return None
        crops = set(detect_crops(text))
        vector = np.asarray(self.embed([text]), dtype=np.float32)[0]
        with self._lock:
            sims = self._vectors @ vector
            order = np.argsort(-sims)
            for i in order:
                if sims[i] < self.threshold:
                    break
                case = self._cases[i]
                if case["language"] == language and set(detect_crops(case["original_text"])) == crops:
                    return {**case, "similarity": float(sims[i])}
        return None
