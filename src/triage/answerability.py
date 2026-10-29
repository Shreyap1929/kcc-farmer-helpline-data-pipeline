"""
Answerability model (source of truth, section 8B).

The Stage 2 gate answers a low-risk question only when the closest past question
is at least 0.9825 similar. That cut-off was calibrated on English call-taker
summaries; a Marathi or Hindi farmer question reaches the right record at
~0.86-0.91, so Devanagari questions were never answered (parity 0/80).

This module replaces that single number, and nothing else, with an estimate of
"will the best retrieved answer be close to what a real advisor would say?".
It is only consulted where the old similarity rule was: after every safety rule
(live data, schemes, doses, high-risk topics, crop checks, chemical answers) has
already passed the question through. It cannot answer anything the gate's safety
rules would have stopped.

Features are computed from what the gate already has (retrieved hits, the
classifier output, the question text), so the same function serves training
(`src.triage.answerability_train`) and runtime.

The trained artifact holds the decision the evaluation made (fixed rule, see
`answerability_train`): `model`, a per-script similarity threshold, or `none`.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

import joblib
import numpy as np

from src.triage.config import path

ARTIFACT = "answerability.joblib"
DEVANAGARI = re.compile(r"[ऀ-ॿ]")

FEATURES = [
    "sim1",            # similarity of the best crop-compatible past question
    "sim1_dev",        # same, only for Devanagari questions (lets a linear model shift the scale)
    "gap",             # best minus second-best candidate similarity
    "sim_mean",        # mean similarity of the retrieved hits
    "consensus_mean",  # how much the other retrieved answers agree with the best one
    "consensus_max",
    "log_times_asked", # popularity of the best question in the KB
    "distinct_answers",
    "answer_share",    # share of advisors who gave this exact answer to that question
    "crop_known",
    "crop_match",      # best hit is about the crop the gate resolved
    "type_conf",
    "type_match",      # predicted query type equals the best hit's type
    "devanagari",
    "n_tokens",
]


def is_devanagari(text: str) -> bool:
    return bool(DEVANAGARI.search(text or ""))


def feature_rows(items: list[tuple], closeness) -> np.ndarray:
    """
    items: (text, prediction, crop, best, candidates, hits) per question, where
    `best` is the hit the gate would serve and `candidates` the crop-compatible hits.
    Batched so the answer-consensus TF-IDF runs once for the whole set.
    """
    pairs_a, pairs_b, owner = [], [], []
    for i, (_, _, _, best, _, hits) in enumerate(items):
        for h in hits:
            if h.kcc_call_id != best.kcc_call_id:
                pairs_a.append(best.answer)
                pairs_b.append(h.answer)
                owner.append(i)
    sims = closeness(pairs_a, pairs_b) if pairs_a else np.array([])
    per_item: list[list[float]] = [[] for _ in items]
    for i, s in zip(owner, sims):
        per_item[i].append(float(s))

    rows = []
    for i, (text, pred, crop, best, candidates, hits) in enumerate(items):
        dev = is_devanagari(text)
        second = candidates[1].similarity if len(candidates) > 1 else (hits[1].similarity if len(hits) > 1 else 0.0)
        cons = per_item[i]
        qtype = pred["query_type"]
        rows.append([
            best.similarity,
            best.similarity if dev else 0.0,
            best.similarity - second,
            float(np.mean([h.similarity for h in hits])) if hits else 0.0,
            float(np.mean(cons)) if cons else 0.0,
            float(np.max(cons)) if cons else 0.0,
            math.log1p(best.times_asked),
            float(best.distinct_answers),
            float(best.answer_share),
            float(crop is not None),
            float(crop is not None and best.crop == crop),
            float(qtype["confidence"]),
            float(qtype["label"] == best.query_type),
            float(dev),
            float(len((text or "").split())),
        ])
    return np.asarray(rows, dtype=np.float64)


@dataclass
class Verdict:
    answer: bool
    detail: str
    probability: float | None = None


@dataclass
class AnswerPolicy:
    """
    The decision the evaluation adopted, applied where the gate used to compare
    similarity with one threshold.

    mode "model":      answer if P(close) >= threshold and similarity >= min_similarity
    mode "per_script": answer if similarity >= the threshold for the question's script
    mode "none":       the gate keeps its Stage 2 rule (the policy is not loaded)
    """
    mode: str
    threshold: float
    min_similarity: float
    script_thresholds: dict = field(default_factory=dict)
    model: object = None
    closeness: object = None
    meta: dict = field(default_factory=dict)

    def decide(self, text: str, prediction: dict, crop: str | None, best, candidates, hits) -> Verdict:
        if self.mode == "per_script":
            script = "devanagari" if is_devanagari(text) else "latin"
            t = self.script_thresholds[script]
            ok = best.similarity >= t
            return Verdict(ok, f"Closest past question {best.similarity:.3f} vs {t:.3f} for {script} questions.")
        x = feature_rows([(text, prediction, crop, best, candidates, hits)], self.closeness)
        p = float(self.model.predict_proba(x)[0, 1])
        if best.similarity < self.min_similarity:
            return Verdict(False, f"Closest past question too far ({best.similarity:.3f} < "
                                  f"{self.min_similarity:.3f}).", p)
        ok = p >= self.threshold
        cmp = ">=" if ok else "<"
        return Verdict(ok, f"Estimated chance the past answer fits: {p:.0%} {cmp} {self.threshold:.0%} "
                           f"(similarity {best.similarity:.3f}).", p)

    def save(self) -> None:
        joblib.dump(self, path("artifacts") / ARTIFACT)

    @staticmethod
    def load() -> "AnswerPolicy | None":
        """The adopted policy, or None when nothing was adopted or nothing was built."""
        f = path("artifacts") / ARTIFACT
        if not f.exists():
            return None
        policy = joblib.load(f)
        return policy if policy.mode in ("model", "per_script") else None
