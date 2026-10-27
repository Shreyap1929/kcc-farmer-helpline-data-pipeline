"""
Dense retrieval over the knowledge-base view.

Index unit: each distinct question text (q_core) in the KB, embedded once.
A hit is then expanded to the historical Q&A pairs (qa_key) behind it, and the
best answer per normalised question (q_key) is chosen with small metadata
boosts (crop, district, season) and answer popularity.

`cutoff` restricts the KB to records on or before a year_month, which is how
the offline evaluation avoids reading the future.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import faiss
import numpy as np
import pandas as pd

from src.triage.config import load_config, path
from src.triage.embeddings import load_question_embeddings

KB_COLUMNS = [
    "KCCCallID", "source_file", "source_row", "created_on", "year_month", "season_derived",
    "district_clean", "district_display", "crop_clean", "query_type_clean", "q_core", "q_key",
    "qa_key", "ans_clean", "answer_lang", "pol_risk", "pol_ans_chemical", "pol_ans_dose_advice",
]


@dataclass
class Hit:
    kcc_call_id: str
    question: str
    answer: str
    similarity: float
    score: float
    created_on: str
    district: str
    crop: str
    season: str
    query_type: str
    answer_lang: str
    risk: str
    chemical: bool
    times_asked: int
    distinct_answers: int
    answer_share: float
    source_file: str
    source_row: int

    def to_dict(self) -> dict:
        return asdict(self)


class Retriever:
    def __init__(self, kb: pd.DataFrame, q_index: pd.Series, q_emb: np.ndarray, cutoff: str | None = None):
        if cutoff:
            kb = kb[kb["year_month"] <= cutoff]
        cfg = load_config()["retrieval"]
        self.top_k = cfg["top_k"]
        self.boosts = (cfg["crop_boost"], cfg["district_boost"], cfg["season_boost"])

        # One record per distinct Q&A pair: the most recent occurrence, with its frequency.
        kb = kb.sort_values("created_on")
        counts = kb.groupby("qa_key").size().rename("qa_count")
        rec = kb.drop_duplicates("qa_key", keep="last").join(counts, on="qa_key")
        q_totals = rec.groupby("q_key")["qa_count"].agg(["sum", "size"])
        rec = rec.join(q_totals.rename(columns={"sum": "q_total", "size": "q_answers"}), on="q_key")
        rec["answer_share"] = rec["qa_count"] / rec["q_total"]
        self.records = rec.reset_index(drop=True)
        # Plain arrays for the ranking hot loop (pandas row access is ~100x slower).
        self._q_key = self.records["q_key"].to_numpy()
        self._crop = self.records["crop_clean"].to_numpy()
        self._district = self.records["district_clean"].to_numpy()
        self._season = self.records["season_derived"].to_numpy()
        self._share = self.records["answer_share"].to_numpy()

        self.questions = np.array(sorted(self.records["q_core"].unique()))
        self.q_to_records = self.records.groupby("q_core").indices
        vecs = np.ascontiguousarray(q_emb[q_index.loc[self.questions].values], dtype=np.float32)
        self.index = faiss.IndexFlatIP(vecs.shape[1])
        self.index.add(vecs)

    @classmethod
    def from_views(cls, cutoff: str | None = None) -> "Retriever":
        kb = pd.read_parquet(path("views") / "kb_candidates.parquet", columns=KB_COLUMNS)
        q_index, q_emb = load_question_embeddings()
        return cls(kb, q_index, q_emb, cutoff=cutoff)

    def __len__(self) -> int:
        return len(self.records)

    def search_batch(
        self,
        query_vecs: np.ndarray,
        k: int | None = None,
        crops: list[str | None] | None = None,
        districts: list[str | None] | None = None,
        seasons: list[str | None] | None = None,
        exclude_q_keys: list[str | None] | None = None,
        fanout: int = 25,
    ) -> list[list[Hit]]:
        k = k or self.top_k
        n = len(query_vecs)
        crops, districts, seasons = crops or [None] * n, districts or [None] * n, seasons or [None] * n
        exclude_q_keys = exclude_q_keys or [None] * n
        sims, idxs = self.index.search(np.ascontiguousarray(query_vecs, dtype=np.float32), fanout)
        return [
            self._rank(sims[i], idxs[i], k, crops[i], districts[i], seasons[i], exclude_q_keys[i])
            for i in range(n)
        ]

    def search(self, query_vec: np.ndarray, **kwargs) -> list[Hit]:
        single = {key: [value] for key, value in kwargs.items() if key not in ("k", "fanout")}
        extra = {key: kwargs[key] for key in ("k", "fanout") if key in kwargs}
        return self.search_batch(query_vec.reshape(1, -1), **single, **extra)[0]

    def _rank(self, sims, idxs, k, crop, district, season, exclude_q_key) -> list[Hit]:
        crop_b, dist_b, season_b = self.boosts
        best_per_qkey: dict[str, tuple[float, float, int]] = {}
        for sim, qi in zip(sims, idxs):
            if qi < 0:
                continue
            for ri in self.q_to_records[self.questions[qi]]:
                q_key = self._q_key[ri]
                if exclude_q_key is not None and q_key == exclude_q_key:
                    continue
                score = (
                    float(sim)
                    + crop_b * (crop is not None and self._crop[ri] == crop)
                    + dist_b * (district is not None and self._district[ri] == district)
                    + season_b * (season is not None and self._season[ri] == season)
                    + 0.002 * self._share[ri]
                )
                prev = best_per_qkey.get(q_key)
                if prev is None or score > prev[0]:
                    best_per_qkey[q_key] = (score, float(sim), ri)

        ranked = sorted(best_per_qkey.values(), key=lambda t: -t[0])[:k]
        return [self._hit(ri, sim, score) for score, sim, ri in ranked]

    def _hit(self, ri: int, sim: float, score: float) -> Hit:
        r = self.records.iloc[ri]
        return Hit(
            kcc_call_id=str(r["KCCCallID"]),
            question=r["q_core"],
            answer=r["ans_clean"],
            similarity=round(sim, 4),
            score=round(score, 4),
            created_on=str(r["created_on"])[:10],
            district=r["district_display"] or r["district_clean"] or "",
            crop=r["crop_clean"] or "",
            season=r["season_derived"] or "",
            query_type=r["query_type_clean"] or "",
            answer_lang=r["answer_lang"] or "",
            risk=r["pol_risk"],
            chemical=bool(r["pol_ans_chemical"]),
            times_asked=int(r["q_total"]),
            distinct_answers=int(r["q_answers"]),
            answer_share=round(float(r["answer_share"]), 3),
            source_file=r["source_file"],
            source_row=int(r["source_row"]),
        )
