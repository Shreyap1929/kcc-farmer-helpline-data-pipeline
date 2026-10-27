"""
Gate calibration and offline evaluation.

1. Calibrate on the validation months with a train-only knowledge base:
   - answer_min_similarity: lowest best-match similarity at which answered
     cases agree with the real advisor answer at least `answer_relative_target`
     times as often as two real advisors agree with each other on the same
     question. If no threshold reaches that, the ANSWER route is disabled
     (threshold above 1) rather than silently falling back to a default.
   - out_of_scope_max_similarity: 1st percentile of best-match similarity over
     real validation questions that contain no farm words, i.e. the only kind
     of question the out-of-scope rule can ever apply to.
2. Evaluate the calibrated gate on the test months with a knowledge base
   frozen at the end of validation (no future records), realistic and hard.
3. Run the hand-written probes (config/gate_probes.csv) through the full engine.

"Close answer" proxy: character n-gram TF-IDF cosine >= answer_close_threshold
between a served historical answer and the real answer on that call. It is a
stand-in until the golden set exists, and is reported as such.

    python -m src.triage.evaluate
"""
from __future__ import annotations

import json
from collections import Counter

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer

from src.triage.classifier import QueryClassifier
from src.triage.config import CONFIG_DIR, gate_thresholds, load_config, path
from src.triage.crops import detect_crops
from src.triage.embeddings import load_question_embeddings
from src.triage.engine import TriageEngine, season_for_month
from src.triage.gate import Gate, GateInput, Route
from src.triage.policy import question_signals
from src.triage.retrieval import Retriever

EVAL_COLUMNS = [
    "q_core", "q_key", "ans_clean", "split", "year_month", "district_clean", "query_type_clean",
    "is_valid_qa", "pol_time_sensitive", "pol_ans_chemical", "pol_q_scheme",
]
ROUTES = [r.value for r in Route]
# Rows where only the similarity threshold decides between ANSWER and EXPERT_REVIEW.
LOW_RISK_POOL_REASONS = {"RETRIEVED_LOW_RISK", "LOW_CONFIDENCE"}
ANSWER_DISABLED = 1.01


# ---------------------------------------------------------------------------
# Batch replay of the gate over dataset rows
# ---------------------------------------------------------------------------

def replay(rows: pd.DataFrame, retriever: Retriever, clf: QueryClassifier, gate: Gate,
           q_index: pd.Series, q_emb: np.ndarray) -> pd.DataFrame:
    """Run the gate over dataset rows exactly as the engine would at runtime.

    The caller profile carries district and month (as the source of truth
    specifies); the crop must come from the question itself.
    """
    rows = rows.reset_index(drop=True)
    texts = rows["q_core"].tolist()
    vecs = np.asarray(q_emb[q_index.loc[rows["q_core"].values].values])

    uniq = rows["q_core"].unique()
    sig = {q: question_signals(q) for q in uniq}
    crops = {q: detect_crops(q) for q in uniq}
    preds = clf.predict_batch(texts, vecs)

    crop_used = []
    for t, p in zip(texts, preds):
        c, _ = gate.resolve_crop(GateInput(t, sig[t], crops[t], p, hits=[]))
        crop_used.append(c)
    seasons = [season_for_month(int(ym[-2:])) for ym in rows["year_month"]]
    hits = retriever.search_batch(vecs, crops=crop_used, districts=rows["district_clean"].tolist(), seasons=seasons)

    out = []
    for i, t in enumerate(texts):
        d = gate.decide(GateInput(t, sig[t], crops[t], preds[i], hits[i]))
        best = d.answer_source or (hits[i][0] if hits[i] else None)
        out.append({
            "route": d.route.value,
            "reason": d.reasons[0].code,
            "top_similarity": hits[i][0].similarity if hits[i] else 0.0,
            "served_answer": d.reply if d.route == Route.ANSWER else None,
            "served_chemical": bool(d.answer_source.chemical) if d.route == Route.ANSWER and d.answer_source else False,
            "best_answer": best.answer if best else "",
            "best_similarity": best.similarity if best else 0.0,
            "farm_words": bool(sig[t].agri or sig[t].dose or crops[t]),
            "pred_type": preds[i]["query_type"]["label"],
        })
    return pd.concat([rows, pd.DataFrame(out)], axis=1)


class Closeness:
    """Char n-gram cosine between two answers (Marathi-friendly, no tokeniser)."""

    def __init__(self, corpus: list[str]):
        self.vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), min_df=3, sublinear_tf=True)
        self.vec.fit(corpus)

    def __call__(self, a: list[str], b: list[str]) -> np.ndarray:
        if not a:
            return np.array([])
        xa, xb = self.vec.transform(a), self.vec.transform(b)
        return np.asarray(xa.multiply(xb).sum(axis=1)).ravel()


def advisor_agreement(rows: pd.DataFrame, records: pd.DataFrame, closeness: Closeness,
                      close_t: float, seed: int = 0) -> dict:
    """
    How often does a *second real advisor* give a close answer to the same
    question? For each row whose q_key is in the knowledge base, draw one
    historical answer to that q_key (weighted by how often it was given) and
    compare it with the real answer on this call.
    """
    rec = records[records["q_key"].isin(set(rows["q_key"]))]
    groups = {k: (g["ans_clean"].to_numpy(), g["qa_count"].to_numpy() / g["qa_count"].sum())
              for k, g in rec.groupby("q_key")}
    rng = np.random.default_rng(seed)
    a, b = [], []
    for q_key, real in zip(rows["q_key"], rows["ans_clean"]):
        if q_key in groups:
            answers, weights = groups[q_key]
            a.append(real)
            b.append(answers[rng.choice(len(answers), p=weights)])
    sims = closeness(a, b)
    return {"n": len(a), "close_rate": float((sims >= close_t).mean()) if len(a) else None,
            "mean_closeness": float(sims.mean()) if len(a) else None}


def choose_answer_threshold(sim: np.ndarray, close: np.ndarray, target: float,
                            min_answered: int = 200) -> tuple[float | None, pd.DataFrame]:
    """Lowest threshold whose answered cases reach the target close rate."""
    grid = np.round(np.arange(0.80, 1.0001, 0.0025), 4)
    curve = []
    for t in grid:
        sel = sim >= t
        n = int(sel.sum())
        curve.append({
            "threshold": float(t),
            "answered": n,
            "coverage_of_pool": n / max(len(sim), 1),
            "close_rate": float(close[sel].mean()) if n else float("nan"),
        })
    curve_df = pd.DataFrame(curve)
    ok = curve_df[(curve_df["close_rate"] >= target) & (curve_df["answered"] >= min_answered)]
    return (float(ok["threshold"].min()) if len(ok) else None), curve_df


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------

def calibrate(valid: pd.DataFrame, retriever: Retriever, clf, q_index, q_emb,
              closeness: Closeness) -> tuple[dict, pd.DataFrame]:
    cfg = gate_thresholds()
    close_t = cfg["answer_close_threshold"]
    # Open the answer and out-of-scope gates so every case that reaches the
    # threshold decision is visible.
    open_gate = Gate({**cfg, "answer_min_similarity": -1.0, "out_of_scope_max_similarity": -1.0})
    res = replay(valid, retriever, clf, open_gate, q_index, q_emb)

    pool = res[res["route"] == Route.ANSWER.value]
    close = closeness(pool["served_answer"].tolist(), pool["ans_clean"].tolist()) >= close_t
    agreement = advisor_agreement(pool, retriever.records, closeness, close_t)
    target = cfg["answer_relative_target"] * agreement["close_rate"]
    answer_t, curve = choose_answer_threshold(pool["best_similarity"].to_numpy(), close, target)

    no_farm = res.loc[~res["farm_words"], "top_similarity"]
    oos_t = float(np.floor(np.percentile(no_farm, 1) * 1000) / 1000)

    thresholds = {
        "answer_min_similarity": answer_t if answer_t is not None else ANSWER_DISABLED,
        "answer_route_enabled": answer_t is not None,
        "out_of_scope_max_similarity": oos_t,
        "calibrated_on": "valid",
        "low_risk_pool_valid": int(len(pool)),
        "pool_close_rate_answer_all": float(close.mean()),
        "advisor_agreement_valid": agreement,
        "answer_target_close_rate": float(target),
        "out_of_scope_reference_rows": int(len(no_farm)),
    }
    return thresholds, curve


def plot_curve(curve: pd.DataFrame, chosen: float | None, target: float, agreement: float, out_file) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7.5, 4.2), dpi=130)
    ax.plot(curve["threshold"], curve["close_rate"], color="#2f6b3a", lw=2, label="Answered cases close to the real answer")
    ax.plot(curve["threshold"], curve["coverage_of_pool"], color="#c58b16", lw=2, label="Share of low-risk pool answered")
    ax.axhline(agreement, color="#6b35c9", ls="-.", lw=1, label=f"Two real advisors agree ({agreement:.0%})")
    ax.axhline(target, color="#2f6b3a", ls=":", lw=1, label=f"Target ({target:.0%})")
    if chosen is not None:
        ax.axvline(chosen, color="#555", ls="--", lw=1)
        ax.text(chosen, 0.93, f" chosen {chosen:.4f}", fontsize=8, color="#333")
    ax.set_xlabel("Answer threshold (cosine similarity of best match)")
    ax.set_ylim(0, 1.02)
    ax.set_title("Answer-gate calibration on validation months", fontsize=10)
    ax.legend(loc="center left", fontsize=7.5, frameon=False)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(out_file)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Test evaluation
# ---------------------------------------------------------------------------

def _share(mask: pd.Series) -> float | None:
    return round(float(mask.mean()), 4) if len(mask) else None


def summarise(res: pd.DataFrame, records: pd.DataFrame, closeness: Closeness, close_t: float) -> dict:
    n = len(res)
    routes = res["route"].value_counts()
    answered = res[res["route"] == Route.ANSWER.value]
    close = closeness(answered["served_answer"].tolist(), answered["ans_clean"].tolist())
    # Same population without a threshold: answer every low-risk-pool row.
    pool = res[res["reason"].isin(LOW_RISK_POOL_REASONS)]
    pool_close = closeness(pool["best_answer"].tolist(), pool["ans_clean"].tolist())
    agreement = advisor_agreement(answered, records, closeness, close_t)

    live = res[res["pol_time_sensitive"]]
    chem = res[res["pol_ans_chemical"] & ~res["pol_time_sensitive"]]
    schemes = res[res["query_type_clean"] == "Government Schemes"]
    return {
        "rows": n,
        "route_share": {r: round(float(routes.get(r, 0) / n), 4) for r in ROUTES},
        "auto_answer_coverage": round(float(len(answered) / n), 4),
        "answered_close_rate": round(float((close >= close_t).mean()), 4) if len(close) else None,
        "answered_mean_closeness": round(float(close.mean()), 4) if len(close) else None,
        "low_risk_pool_rows": int(len(pool)),
        "low_risk_pool_close_rate_answer_all": round(float((pool_close >= close_t).mean()), 4) if len(pool) else None,
        "advisor_agreement_on_answered": agreement,
        "served_chemical_answers": int(answered["served_chemical"].sum()),
        "answered_where_real_answer_was_chemical": _share(answered["pol_ans_chemical"]),
        "time_sensitive_rows": int(len(live)),
        "time_sensitive_to_pointer": _share(live["route"].isin(["LIVE_DATA_POINTER", "SCHEME_POINTER"])),
        "time_sensitive_answered": _share(live["route"] == "ANSWER"),
        "chemical_rows": int(len(chem)),
        "chemical_to_expert_or_clarify": _share(chem["route"].isin(["EXPERT_REVIEW", "CLARIFY"])),
        "chemical_answered": _share(chem["route"] == "ANSWER"),
        "scheme_rows": int(len(schemes)),
        "scheme_to_scheme_pointer": _share(schemes["route"] == "SCHEME_POINTER"),
        "top_reasons": dict(Counter(res["reason"]).most_common(10)),
    }


def run_probes(engine: TriageEngine) -> list[dict]:
    probes = pd.read_csv(CONFIG_DIR / "gate_probes.csv", dtype=str, keep_default_na=False)
    out = []
    for p in probes.itertuples():
        r = engine.triage(p.text, crop=p.profile_crop or None)
        out.append({
            "text": p.text, "lang": p.lang, "profile_crop": p.profile_crop, "note": p.note,
            "expected": p.expected_route, "got": r["route"], "pass": r["route"] == p.expected_route,
            "reason": r["reasons"][0]["code"], "top_similarity": r["sources"][0]["similarity"] if r["sources"] else None,
            "pred_type": r["prediction"]["query_type"]["label"],
        })
    return out


def eval_report(thr: dict, test_real: dict, test_hard: dict, probes: list[dict], cfg: dict) -> str:
    def fmt(v, pattern):
        if v is None:
            return "-"
        return pattern.format(v) if isinstance(v, float) else f"{v:,}"

    def row(label, key, pattern="{:.1%}"):
        return f"| {label} | {fmt(test_real.get(key), pattern)} | {fmt(test_hard.get(key), pattern)} |"

    agree_v = thr["advisor_agreement_valid"]
    ar, ah = test_real["advisor_agreement_on_answered"], test_hard["advisor_agreement_on_answered"]
    passed = sum(p["pass"] for p in probes)
    if thr["answer_route_enabled"]:
        answer_line = (
            f"- **Answer threshold:** `{thr['answer_min_similarity']:.4f}`, the lowest best-match similarity "
            f"at which answered cases are close to the real answer at least {thr['answer_target_close_rate']:.1%} "
            f"of the time ({cfg['answer_relative_target']:.0%} of advisor agreement)."
        )
    else:
        answer_line = (
            "- **Answer route DISABLED:** no threshold reached the target close rate "
            f"({thr['answer_target_close_rate']:.1%}), so every low-risk case goes to an expert."
        )
    lines = [
        "# Stage 2 - Gate calibration and evaluation",
        "",
        "Generated by `python -m src.triage.evaluate`.",
        "",
        "> **How \"close\" is measured.** Character n-gram cosine >= "
        f"{cfg['answer_close_threshold']} between a served historical answer and the real answer",
        "> given on that call. It rewards matching what an advisor said, not agronomic correctness.",
        "> Advisors themselves word answers very differently, so the proxy is read *relative to",
        "> advisor agreement*: how often a second real advisor's answer to the same question is close.",
        "> It stays a proxy until the hand-checked golden set exists.",
        "",
        "## 1. Calibration (validation months, KB = train months only)",
        "",
        f"- **Advisor agreement:** for {agree_v['n']:,} validation calls whose question was already in the KB,",
        f"  another real advisor's answer to the same question was close only **{agree_v['close_rate']:.1%}** of the time",
        f"  (mean closeness {agree_v['mean_closeness']:.3f}). An absolute target like 80% is unreachable by construction.",
        answer_line,
        f"  Answering the whole low-risk pool ({thr['low_risk_pool_valid']:,} rows) would be close "
        f"{thr['pool_close_rate_answer_all']:.1%} of the time.",
        f"- **Out-of-scope threshold:** `{thr['out_of_scope_max_similarity']:.3f}`, the 1st percentile of best-match",
        f"  similarity over {thr['out_of_scope_reference_rows']:,} real validation questions *without farm words* (the",
        "  only questions the rule can apply to). Questions with farm words are never called out of scope.",
        "",
        "![Answer threshold curve](figures/answer_threshold_curve.png)",
        "",
        "## 2. Test months (2025-01..07), KB frozen at 2024-12",
        "",
        "Random sample of test rows; caller profile = district + month, crop only from the",
        "question. *Hard* = questions whose `q_key` never appeared before 2025.",
        "",
        "| Metric | Realistic | Hard |",
        "|---|---:|---:|",
        row("Rows evaluated", "rows", "{:,}"),
    ]
    for r in ROUTES:
        lines.append(f"| Route share: `{r}` | {test_real['route_share'][r]:.1%} | {test_hard['route_share'][r]:.1%} |")
    lines += [
        row("**Auto-answer coverage**", "auto_answer_coverage"),
        row("**Answered cases close to the real answer**", "answered_close_rate"),
        f"| Reference: second real advisor close, same answered questions | "
        f"{fmt(ar['close_rate'], '{:.1%}')} (n={ar['n']:,}) | {fmt(ah['close_rate'], '{:.1%}')} (n={ah['n']:,}) |",
        row("Same low-risk pool answered without a threshold", "low_risk_pool_close_rate_answer_all"),
        row("Mean closeness when answering", "answered_mean_closeness", "{:.3f}"),
        row("**Chemical answers served automatically**", "served_chemical_answers", "{:,}"),
        row("Answered although the real answer was chemical", "answered_where_real_answer_was_chemical"),
        row("Time-sensitive rows", "time_sensitive_rows", "{:,}"),
        row("... sent to a live/scheme pointer", "time_sensitive_to_pointer"),
        row("**... answered from history**", "time_sensitive_answered"),
        row("Rows whose real answer was chemical", "chemical_rows", "{:,}"),
        row("... sent to expert or clarify", "chemical_to_expert_or_clarify"),
        row("**... answered automatically**", "chemical_answered"),
        row("Government-scheme rows", "scheme_rows", "{:,}"),
        row("... sent to the scheme pointer", "scheme_to_scheme_pointer"),
        "",
        "Hard-mode advisor agreement covers only answered questions whose `q_key` exists in the KB,",
        "which by definition excludes most hard rows; read it as indicative.",
        "",
        "**Limit of the safety rows.** \"Chemical\" and \"time-sensitive\" are decided by the same",
        "policy detectors that build the KB, so these rows prove the *gate* never serves what the",
        "detectors flag; they cannot reveal what the detectors miss. Detector misses were hunted by",
        "reading samples and served answers by hand; two found that way (per-piece mandi prices,",
        "instalment-date phrasings) are fixed and covered by `tests/test_policy.py`.",
        "",
        "## 3. Probe set (full engine, production KB)",
        "",
        f"Hand-written probes in `config/gate_probes.csv`: **{passed}/{len(probes)} routed as expected.**",
        "These are a smoke test written by the developer, not the golden set. Failures are kept",
        "visible on purpose.",
        "",
        "| Lang | Question | Expected | Got | Reason | Best sim |",
        "|---|---|---|---|---|---:|",
    ]
    for p in probes:
        mark = "" if p["pass"] else " ✗"
        sim = "-" if p["top_similarity"] is None else f"{p['top_similarity']:.3f}"
        lines.append(f"| {p['lang']} | {p['text']} | {p['expected']} | {p['got']}{mark} | {p['reason']} | {sim} |")
    failures = [p for p in probes if not p["pass"]]
    if failures:
        lines += ["", "Failed probes:", ""]
        lines += [f"- *{p['text']}* -> {p['got']} ({p['reason']}). {p['note']}" for p in failures]
    lines.append("")
    return "\n".join(lines)


def main(test_sample: int = 40000) -> None:
    split = load_config()["split"]
    corpus = pd.read_parquet(path("views") / "corpus_tagged.parquet", columns=EVAL_COLUMNS)
    corpus = corpus[corpus["is_valid_qa"] & (corpus["q_core"].str.len() >= 3)]
    q_index, q_emb = load_question_embeddings()
    clf = QueryClassifier.load()

    kb_answers = pd.read_parquet(path("views") / "kb_candidates.parquet", columns=["ans_clean"])["ans_clean"]
    closeness = Closeness(kb_answers.sample(60000, random_state=0).tolist())

    print("Calibrating on validation months ...")
    art = path("artifacts")
    (art / "gate_thresholds.json").unlink(missing_ok=True)  # calibrate from config defaults, not a previous run
    retr_train = Retriever.from_views(cutoff=split["train_end"])
    thr, curve = calibrate(corpus[corpus["split"] == "valid"], retr_train, clf, q_index, q_emb, closeness)
    del retr_train
    (art / "gate_thresholds.json").write_text(json.dumps(thr, indent=2), encoding="utf-8")
    print(f"  thresholds: {thr}")
    if not thr["answer_route_enabled"]:
        print("  WARNING: no answer threshold met the target; ANSWER route disabled.")

    rep = path("reports")
    (rep / "figures").mkdir(parents=True, exist_ok=True)
    cfg = gate_thresholds()
    plot_curve(curve, thr["answer_min_similarity"] if thr["answer_route_enabled"] else None,
               thr["answer_target_close_rate"], thr["advisor_agreement_valid"]["close_rate"],
               rep / "figures" / "answer_threshold_curve.png")

    print("Evaluating on test months ...")
    test = corpus[corpus["split"] == "test"].sample(min(test_sample, (corpus["split"] == "test").sum()), random_state=42)
    seen = set(corpus.loc[corpus["split"].isin(["train", "valid"]), "q_key"])
    retr_valid = Retriever.from_views(cutoff=split["valid_end"])
    res = replay(test, retr_valid, clf, Gate(cfg), q_index, q_emb)
    res["hard"] = ~res["q_key"].isin(seen)
    close_t = cfg["answer_close_threshold"]
    test_real = summarise(res, retr_valid.records, closeness, close_t)
    test_hard = summarise(res[res["hard"]], retr_valid.records, closeness, close_t)
    del retr_valid

    print("Running probes with the production engine ...")
    probes = run_probes(TriageEngine.load())

    metrics = {"thresholds": thr, "test_realistic": test_real, "test_hard": test_hard,
               "probes": probes, "calibration_curve": curve.to_dict(orient="records")}
    (rep / "gate_metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    (rep / "gate_report.md").write_text(eval_report(thr, test_real, test_hard, probes, cfg), encoding="utf-8")
    print(f"Probes: {sum(p['pass'] for p in probes)}/{len(probes)} as expected")
    print(f"Wrote {rep / 'gate_report.md'}")


if __name__ == "__main__":
    main()
