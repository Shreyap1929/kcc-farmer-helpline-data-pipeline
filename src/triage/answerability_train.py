"""
Train and evaluate the answerability model (source of truth, section 8B), and
decide whether the gate should use it.

Data. The "low-risk pool": questions that pass every safety rule and reach the
one decision the model replaces (answer from history, or send to an expert as
LOW_CONFIDENCE). Built by running the real gate with the answer threshold open.
- English: real KCC questions (call-taker summaries). Training = validation
  months with a train-only KB, exactly as the Stage 2 calibration; test = the
  same 40,000-row test-month sample as `src.triage.evaluate`, KB frozen at 2024-12.
- Marathi / Hindi: the KCC data has no farmer-language questions, so a sample of
  pool questions is rephrased as a farmer would ask it (Groq, cached in
  data/runtime/answerability_rephrasings.json) and sent through the production
  Devanagari path (glossary expansion, embedding, classifier, gate) with the
  original call's district and month.
Label (every language): the best retrieved answer is "close" to the real answer
given on that call (Stage 2 proxy: char n-gram cosine >= answer_close_threshold).

Models: logistic regression and gradient-boosted trees on `answerability.FEATURES`,
out-of-fold on the validation pool with folds grouped by the original question,
so a question and its rephrasings never sit on both sides. The operating point is
the lowest probability at which answered cases reach the Stage 2 target close
rate (80% of advisor agreement) for Latin and for Devanagari questions separately.

Compared with two rules: the Stage 2 global similarity threshold, and a
per-script threshold (the Stage 2 one for Latin, recalibrated on the Devanagari
validation pool the same way).

Decision rule, fixed before the first run:
  Adopt the model if, on the test months,
    (a) answered cases are close at least at the target rate for English and for
        Devanagari (mr + hi together; vacuous if none are answered),
    (b) it gives more close answers than both rules,
    (c) no dose question (rephrased dose set) is answered and no chemical answer
        is served, and
    (d) the hand-written gate probes routed as expected do not drop.
  Otherwise adopt the per-script threshold if it meets (a), (c), (d) and gives
  more close answers than the global rule. Otherwise keep the Stage 2 rule.

Machine-written questions are cleaner than real farmer speech; Devanagari
numbers are an upper bound until real recordings exist.

    python -m src.triage.answerability_train
"""
from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from src.triage.answerability import FEATURES, AnswerPolicy, feature_rows, is_devanagari
from src.triage.classifier import QueryClassifier
from src.triage.config import REPO_ROOT, gate_thresholds, load_config, path
from src.triage.crops import detect_crops
from src.triage.embeddings import embed_texts, load_question_embeddings
from src.triage.engine import TriageEngine, season_for_month
from src.triage.evaluate import EVAL_COLUMNS, Closeness, run_probes
from src.triage.expansion import expand_query
from src.triage.gate import Gate, GateInput, Route
from src.triage.policy import question_signals
from src.triage.retrieval import Retriever

REPORT_DIR = REPO_ROOT / "reports" / "stage5"
REPHRASE_CACHE = REPO_ROOT / "data" / "runtime" / "answerability_rephrasings.json"
PARITY_CACHE = REPO_ROOT / "data" / "runtime" / "parity_translations.json"
LANGS = {"mr": "Marathi", "hi": "Hindi"}
REPHRASE_MODELS = ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]
BATCH = 20
N_DEV_VALID = 600
N_DEV_TEST = 400
TEST_SAMPLE = 40000
SEED = 11
MIN_ANSWERED = {"latin": 200, "devanagari": 25}
MIN_SIMILARITY = 0.85


# ---------------------------------------------------------------------------
# Rephrasing (Groq, cached)
# ---------------------------------------------------------------------------

def _rephrase_batch(client, model: str, texts: list[str], lang: str) -> list[str]:
    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts))
    result = client.chat.completions.create(
        model=model, temperature=0.3, reasoning_effort="low", max_completion_tokens=4000,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": (
                "Each line is a note a helpline operator wrote about a farmer's call. For each one, write "
                f"the question the farmer in Maharashtra would actually have asked, in {LANGS[lang]}, in "
                "Devanagari script, as one short spoken sentence. Keep crop names and numbers; do not add "
                "facts. Reply as JSON: {\"items\": [{\"n\": 1, \"q\": \"...\"}, ...]} with one item per line.")},
            {"role": "user", "content": numbered},
        ],
    )
    items = json.loads(result.choices[0].message.content)["items"]
    by_n = {int(it["n"]): str(it["q"]).strip() for it in items}
    out = [by_n.get(i + 1, "") for i in range(len(texts))]
    if sum(bool(is_devanagari(q)) for q in out) < len(texts) * 0.8:
        raise ValueError("rephrase batch came back incomplete")
    return out


def rephrasings(texts: list[str]) -> dict:
    cache = json.loads(REPHRASE_CACHE.read_text(encoding="utf-8")) if REPHRASE_CACHE.exists() else {}
    todo = {lang: [t for t in texts if f"{lang}|{t}" not in cache] for lang in LANGS}
    if not any(todo.values()):
        return cache
    from src.assistant.config import get_groq_client

    client = get_groq_client()
    if client is None:
        print(f"  no GROQ_API_KEY: {sum(map(len, todo.values()))} rephrasings missing, Devanagari rows skipped")
        return cache
    for lang, pending in todo.items():
        for start in range(0, len(pending), BATCH):
            chunk = pending[start:start + BATCH]
            for attempt in range(8):
                model = REPHRASE_MODELS[attempt % len(REPHRASE_MODELS)]
                try:
                    out = _rephrase_batch(client, model, chunk, lang)
                    break
                except Exception as exc:  # rate limits, malformed JSON: wait and retry
                    print(f"  {lang} batch {start}: {model} failed ({type(exc).__name__}), retrying")
                    time.sleep(5 * (attempt + 1))
            else:
                raise SystemExit("rephrasing failed repeatedly; rerun later (progress is cached)")
            for t, q in zip(chunk, out):
                if q:
                    cache[f"{lang}|{t}"] = q
            REPHRASE_CACHE.parent.mkdir(parents=True, exist_ok=True)
            REPHRASE_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"  {lang}: {min(start + BATCH, len(pending))}/{len(pending)}", flush=True)
            time.sleep(2.5)
    return cache


# ---------------------------------------------------------------------------
# The low-risk pool
# ---------------------------------------------------------------------------

def pool_items(rows: pd.DataFrame, texts: list[str], vecs: np.ndarray, retrieval_texts: list[str],
               retriever: Retriever, clf: QueryClassifier, gate: Gate) -> tuple[pd.DataFrame, list[tuple]]:
    """
    Run the gate (answer threshold open) over questions exactly as the engine
    does: classifier and retrieval see the retrieval text, safety signals and
    crops come from the question itself, the profile carries district + month.
    Returns the rows that reach the answer decision and their feature inputs.
    """
    preds = clf.predict_batch(retrieval_texts, vecs)
    sig = [question_signals(t) for t in texts]
    crops = [detect_crops(t) for t in texts]
    crop_used = [gate.resolve_crop(GateInput(t, s, c, p, hits=[]))[0]
                 for t, s, c, p in zip(texts, sig, crops, preds)]
    seasons = [season_for_month(int(ym[-2:])) for ym in rows["year_month"]]
    hits = retriever.search_batch(vecs, crops=crop_used, districts=rows["district_clean"].tolist(), seasons=seasons)

    keep, items = [], []
    for i, t in enumerate(texts):
        d = gate.decide(GateInput(t, sig[i], crops[i], preds[i], hits[i]))
        if d.route != Route.ANSWER:
            continue
        best = d.answer_source
        candidates = [h for h in hits[i] if Gate._crop_compatible(h, crop_used[i])]
        keep.append(i)
        items.append((t, preds[i], crop_used[i], best, candidates, hits[i]))
    out = rows.iloc[keep].reset_index(drop=True).copy()
    out["text"] = [texts[i] for i in keep]
    out["best_answer"] = [it[3].answer for it in items]
    out["similarity"] = [it[3].similarity for it in items]
    return out, items


def build_pool(rows: pd.DataFrame, retriever: Retriever, clf, gate: Gate, closeness: Closeness,
               q_index: pd.Series, q_emb: np.ndarray, n_dev: int, close_t: float) -> tuple[pd.DataFrame, dict]:
    rows = rows.reset_index(drop=True)
    latin = rows[~rows["q_core"].map(is_devanagari)].reset_index(drop=True)
    vecs = np.asarray(q_emb[q_index.loc[latin["q_core"].values].values])
    texts = latin["q_core"].tolist()
    en, en_items = pool_items(latin, texts, vecs, texts, retriever, clf, gate)
    en["lang"] = "en"
    parts, all_items, asked = [en], [en_items], {"en": len(latin)}

    # Devanagari: rephrase a sample of distinct English pool questions, one call each.
    src = en[en["q_core"].str.len() >= 12].drop_duplicates("q_core")
    src = src.sample(min(n_dev, len(src)), random_state=SEED)
    cache = rephrasings(src["q_core"].tolist())
    for lang in LANGS:
        have = src[src["q_core"].map(lambda q: f"{lang}|{q}" in cache)]
        if not len(have):
            continue
        native = [cache[f"{lang}|{q}"] for q in have["q_core"]]
        rtexts = [expand_query(t) for t in native]
        dvecs = embed_texts(rtexts)
        base = have.drop(columns=["text", "best_answer", "similarity", "lang"])
        dev, dev_items = pool_items(base, native, dvecs, rtexts, retriever, clf, gate)
        dev["lang"] = lang
        asked[lang] = len(have)
        print(f"  {lang}: {len(have)} rephrased, {len(dev)} reach the answer decision", flush=True)
        parts.append(dev)
        all_items.append(dev_items)

    pool = pd.concat(parts, ignore_index=True)
    items = [it for chunk in all_items for it in chunk]
    pool["close"] = closeness(pool["best_answer"].tolist(), pool["ans_clean"].tolist()) >= close_t
    pool["script"] = np.where(pool["lang"] == "en", "latin", "devanagari")
    X = feature_rows(items, closeness)
    return pool.join(pd.DataFrame(X, columns=FEATURES)), asked


# ---------------------------------------------------------------------------
# Models and operating points
# ---------------------------------------------------------------------------

def make_models() -> dict:
    return {
        "logistic": make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=2000)),
        "boosted_trees": HistGradientBoostingClassifier(
            max_depth=3, learning_rate=0.05, max_iter=250, min_samples_leaf=40, l2_regularization=1.0,
            random_state=0),
    }


def out_of_fold(model, X: np.ndarray, y: np.ndarray, groups: np.ndarray, folds: int = 5) -> np.ndarray:
    oof = np.zeros(len(y))
    for tr, te in GroupKFold(n_splits=folds).split(X, y, groups):
        m = make_models()[model] if isinstance(model, str) else model
        m.fit(X[tr], y[tr])
        oof[te] = m.predict_proba(X[te])[:, 1]
    return oof


def lowest_feasible(score: np.ndarray, close: np.ndarray, script: np.ndarray, target: float,
                    grid: np.ndarray) -> float | None:
    """Lowest cut-off where each script's answered cases reach the target close rate."""
    for t in grid:
        sel = score >= t
        ok = sel.sum() >= MIN_ANSWERED["latin"]
        for s in ("latin", "devanagari"):
            m = sel & (script == s)
            if m.sum() and close[m].mean() < target:
                ok = False
        if ok:
            return float(t)
    return None


def script_threshold(sim: np.ndarray, close: np.ndarray, target: float, min_answered: int) -> float:
    for t in np.round(np.arange(0.80, 1.0001, 0.0025), 4):
        sel = sim >= t
        if sel.sum() >= min_answered and close[sel].mean() >= target:
            return float(t)
    return 1.01


def answered_mask(name: str, pool: pd.DataFrame, policy: dict) -> np.ndarray:
    sim = pool["similarity"].to_numpy()
    if name == "global_threshold":
        return sim >= policy["global"]
    if name == "per_script_threshold":
        t = np.where(pool["script"] == "latin", policy["script"]["latin"], policy["script"]["devanagari"])
        return sim >= t
    p = policy["proba"][name]
    return (p >= policy["model_threshold"][name]) & (sim >= MIN_SIMILARITY)


def summarise(pool: pd.DataFrame, answered: np.ndarray, seed: int = 0) -> dict:
    out = {}
    rng = np.random.default_rng(seed)
    for lang in ["en", "mr", "hi", "devanagari", "all"]:
        if lang == "all":
            m = np.ones(len(pool), bool)
        elif lang == "devanagari":
            m = (pool["script"] == "devanagari").to_numpy()
        else:
            m = (pool["lang"] == lang).to_numpy()
        a = answered & m
        close = pool["close"].to_numpy()[a]
        ci = None
        if len(close) >= 10:
            boots = [rng.choice(close, len(close)).mean() for _ in range(1000)]
            ci = [float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))]
        out[lang] = {"pool": int(m.sum()), "answered": int(a.sum()), "close": int(close.sum()),
                     "close_rate": float(close.mean()) if len(close) else None, "close_rate_ci95": ci}
    return out


# ---------------------------------------------------------------------------
# End-to-end checks with the production engine
# ---------------------------------------------------------------------------

def parity_reference(engine: TriageEngine) -> dict:
    """The Stage 4 parity set, labelled by the Stage 2 engine: English answer, or a dose question."""
    cache = json.loads(PARITY_CACHE.read_text(encoding="utf-8")) if PARITY_CACHE.exists() else {}
    ref = {}
    for text in sorted({k.split("|", 1)[1] for k in cache}):
        en = engine.triage(text)
        if any(r["code"] == "DOSE_QUESTION" for r in en["reasons"]):
            ref[text] = {"dose": True, "answer": None}
        elif en["route"] == "ANSWER":
            ref[text] = {"dose": False, "answer": en["answer_source"]["answer"]}
    return {"items": ref, "cache": cache}


def engine_checks(engine: TriageEngine, reference: dict, closeness: Closeness, close_t: float) -> dict:
    probes = run_probes(engine)
    out = {"probes_pass": sum(p["pass"] for p in probes), "probes": len(probes), "parity": {}, "dose": {}}
    for lang in LANGS:
        answered = close = dose_answered = n_ans = n_dose = 0
        for text, ref in reference["items"].items():
            item = reference["cache"].get(f"{lang}|{text}")
            if not item:
                continue
            d = engine.triage(item["native"])
            if ref["dose"]:
                n_dose += 1
                dose_answered += d["route"] == "ANSWER"
                continue
            n_ans += 1
            if d["route"] == "ANSWER":
                answered += 1
                close += closeness([d["answer_source"]["answer"]], [ref["answer"]])[0] >= close_t
        out["parity"][lang] = {"n": n_ans, "answered": answered, "same_as_english": int(close)}
        out["dose"][lang] = {"n": n_dose, "answered": dose_answered}
    return out


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _pct(a, n):
    return f"{a}/{n} ({a / n:.0%})" if n else "0/0"


def _rate(s):
    if s["close_rate"] is None:
        return "-"
    ci = f" [{s['close_rate_ci95'][0]:.0%}-{s['close_rate_ci95'][1]:.0%}]" if s["close_rate_ci95"] else ""
    return f"{s['close_rate']:.1%}{ci}"


def write_report(m: dict) -> str:
    target = m["target"]
    lines = [
        "# Stage 5 - Answerability model", "",
        "Generated by `python -m src.triage.answerability_train`. Method and the decision rule (fixed before "
        "the first run) are in the module docstring.", "",
        "> \"Close\" is the Stage 2 proxy: char n-gram cosine >= "
        f"{m['close_threshold']} between the served past answer and the real answer on that call. Target close "
        f"rate for answered cases: **{target:.1%}** (80% of the {m['advisor_agreement']:.1%} at which two real "
        "advisors agree). Marathi/Hindi questions are machine rephrasings of real calls: an upper bound until "
        "real farmer recordings exist.", "",
        "## 1. Data (the low-risk pool)", "",
        "| Split | Language | Questions sent | Reach the answer decision | Best answer close |",
        "|---|---|---:|---:|---:|",
    ]
    for split in ("valid", "test"):
        for lang, d in m["data"][split].items():
            lines.append(f"| {split} | {lang} | {d['asked']:,} | {d['pool']:,} | {_pct(d['close'], d['pool'])} |")
    lines += ["", "## 2. Models (validation, out-of-fold, grouped by question)", "",
              "| Model | AUC all | AUC Latin | AUC Devanagari | Brier | Cut-off chosen |", "|---|---:|---:|---:|---:|---:|"]
    for name, s in m["models"].items():
        cut = "-" if s["threshold"] is None else f"{s['threshold']:.2f}"
        lines.append(f"| {name} | {s['auc']:.3f} | {s['auc_latin']:.3f} | {s['auc_dev']:.3f} | {s['brier']:.3f} | {cut} |")
    lines += ["", f"Similarity alone (the Stage 2 rule's signal): AUC all {m['sim_auc']['all']:.3f}, Latin "
              f"{m['sim_auc']['latin']:.3f}, Devanagari {m['sim_auc']['devanagari']:.3f}.", "",
              f"Rules: global similarity threshold **{m['policy']['global']:.4f}** (Stage 2); per-script: Latin "
              f"{m['policy']['script']['latin']:.4f}, Devanagari **{m['policy']['script']['devanagari']:.4f}** "
              "(recalibrated on the Devanagari validation pool). The model also needs similarity >= "
              f"{MIN_SIMILARITY} as a floor.", "",
              "![Coverage and close rate](figures/answerability_tradeoff.png)", "",
              "## 3. Test months (KB frozen at 2024-12)", "",
              "Answered / close answers / close rate of answered [95% bootstrap CI], per language pool.", "",
              "| Policy | English | Marathi | Hindi | Close answers, all |", "|---|---|---|---|---:|"]
    for name, s in m["test"].items():
        cells = [f"{s[l]['answered']} / {s[l]['close']} / {_rate(s[l])}" for l in ("en", "mr", "hi")]
        lines.append(f"| {name} | " + " | ".join(cells) + f" | **{s['all']['close']}** |")
    eh = m["test_english_hard"]
    lines += ["", "English questions never seen before 2025 (*hard*): " + "; ".join(
        f"{k} {v['answered']} answered, {_rate(v)} close" for k, v in eh.items()) + ".", "",
        f"Whole test sample ({m['test_rows']:,} rows, all routes): auto-answer coverage "
        + ", ".join(f"{k} {v:.2%}" for k, v in m["coverage"].items()) + ".", "",
        "## 4. End-to-end checks (production engine)", "",
        "| Check | Stage 2 rule | Candidate |", "|---|---|---|"]
    before, after = m["engine"]["before"], m["engine"]["after"]
    lines.append(f"| Gate probes routed as expected | {before['probes_pass']}/{before['probes']} | "
                 f"{after['probes_pass']}/{after['probes']} |")
    for lang in LANGS:
        if lang in before["parity"]:
            b, a = before["parity"][lang], after["parity"][lang]
            lines.append(f"| Stage 4 parity set, {lang}: answered / same answer as English | "
                         f"{b['answered']}/{b['n']} / {b['same_as_english']} | {a['answered']}/{a['n']} / {a['same_as_english']} |")
            bd, ad = before["dose"][lang], after["dose"][lang]
            lines.append(f"| Dose questions answered, {lang} (must be 0) | {bd['answered']}/{bd['n']} | {ad['answered']}/{ad['n']} |")
    lines += ["", f"Candidate checked end to end: **{m['candidate']}**.", "",
              "## 5. Decision", "", "Rule (fixed before running): see the module docstring.", ""]
    lines += [f"- {c}" for c in m["decision_log"]]
    lines += ["", f"**Adopted: {m['decision']}.**", ""]
    return "\n".join(lines)


def plot_tradeoff(curves: dict, out_file) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(9.5, 3.8), dpi=130, sharey=True)
    colors = {"global_threshold": "#888888", "per_script_threshold": "#c58b16",
              "logistic": "#2f6b3a", "boosted_trees": "#6b35c9"}
    for ax, script in zip(axes, ("latin", "devanagari")):
        for name, pts in curves[script].items():
            ax.plot([p[0] for p in pts], [p[1] for p in pts], label=name.replace("_", " "),
                    color=colors[name], lw=1.8)
        ax.axhline(curves["target"], color="#2f6b3a", ls=":", lw=1)
        ax.set_title(f"{script.title()} questions (validation)", fontsize=9)
        ax.set_xlabel("Share of pool answered")
        ax.grid(alpha=0.25)
    axes[0].set_ylabel("Answered cases close to real answer")
    axes[0].legend(fontsize=7, frameon=False)
    fig.tight_layout()
    fig.savefig(out_file)
    plt.close(fig)


def _curve(score, close, mask, grid):
    pts = []
    for t in grid:
        sel = (score >= t) & mask
        if sel.sum() >= 10:
            pts.append((sel.sum() / mask.sum(), close[sel].mean()))
    return pts


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> dict:
    cfg_all = load_config()
    split = cfg_all["split"]
    stage2 = gate_thresholds()
    close_t = stage2["answer_close_threshold"]
    target = stage2["answer_target_close_rate"]
    open_gate = Gate({**stage2, "answer_min_similarity": -1.0})

    corpus = pd.read_parquet(path("views") / "corpus_tagged.parquet", columns=EVAL_COLUMNS)
    corpus = corpus[corpus["is_valid_qa"] & (corpus["q_core"].str.len() >= 3)]
    q_index, q_emb = load_question_embeddings()
    clf = QueryClassifier.load()
    kb_answers = pd.read_parquet(path("views") / "kb_candidates.parquet", columns=["ans_clean"])["ans_clean"]
    closeness = Closeness(kb_answers.sample(60000, random_state=0).tolist())

    print("Validation pool (KB = train months) ...", flush=True)
    retr = Retriever.from_views(cutoff=split["train_end"])
    valid, asked_valid = build_pool(corpus[corpus["split"] == "valid"], retr, clf, open_gate, closeness,
                                    q_index, q_emb, N_DEV_VALID, close_t)
    del retr
    print("Test pool (KB frozen at valid_end) ...", flush=True)
    test_rows = corpus[corpus["split"] == "test"].sample(min(TEST_SAMPLE, (corpus["split"] == "test").sum()),
                                                         random_state=42)
    seen = set(corpus.loc[corpus["split"].isin(["train", "valid"]), "q_key"])
    retr = Retriever.from_views(cutoff=split["valid_end"])
    test, asked_test = build_pool(test_rows, retr, clf, open_gate, closeness, q_index, q_emb, N_DEV_TEST, close_t)
    test["hard"] = ~test["q_key"].isin(seen)
    del retr

    X, y = valid[FEATURES].to_numpy(), valid["close"].to_numpy()
    groups, script = valid["q_key"].to_numpy(), valid["script"].to_numpy()
    sim_v = valid["similarity"].to_numpy()
    lat, dev = script == "latin", script == "devanagari"

    def auc(score, m):
        return float(roc_auc_score(y[m], score[m])) if m.sum() and len(set(y[m])) == 2 else float("nan")

    p_grid = np.round(np.arange(0.05, 0.951, 0.01), 2)
    models, oof, finals = {}, {}, {}
    for name in make_models():
        oof[name] = out_of_fold(name, X, y, groups)
        thr = lowest_feasible(oof[name], y, script, target, p_grid)
        models[name] = {"auc": auc(oof[name], np.ones(len(y), bool)), "auc_latin": auc(oof[name], lat),
                        "auc_dev": auc(oof[name], dev), "brier": float(brier_score_loss(y, oof[name])),
                        "threshold": thr, "oof_close_answers": int(y[(oof[name] >= thr) & (sim_v >= MIN_SIMILARITY)].sum())
                        if thr is not None else 0}
        finals[name] = make_models()[name].fit(X, y)
    sim_auc = {"all": auc(sim_v, np.ones(len(y), bool)), "latin": auc(sim_v, lat), "devanagari": auc(sim_v, dev)}

    policy = {
        "global": stage2["answer_min_similarity"],
        "script": {"latin": stage2["answer_min_similarity"],
                   "devanagari": script_threshold(sim_v[dev], y[dev], target, MIN_ANSWERED["devanagari"])},
        "model_threshold": {n: (s["threshold"] if s["threshold"] is not None else 1.01) for n, s in models.items()},
    }
    best_model = max(models, key=lambda n: models[n]["oof_close_answers"])

    # Validation trade-off curves for the figure.
    grid_s = np.round(np.arange(0.80, 1.0001, 0.0025), 4)
    curves = {"target": target}
    for s_name, m in (("latin", lat), ("devanagari", dev)):
        curves[s_name] = {"global_threshold": _curve(sim_v, y, m, grid_s)}
        for name in models:
            curves[s_name][name] = _curve(np.where(sim_v >= MIN_SIMILARITY, oof[name], 0), y, m, p_grid)
    REPORT_DIR.joinpath("figures").mkdir(parents=True, exist_ok=True)
    plot_tradeoff(curves, REPORT_DIR / "figures" / "answerability_tradeoff.png")

    # Test months.
    Xt = test[FEATURES].to_numpy()
    policy["proba"] = {n: finals[n].predict_proba(Xt)[:, 1] for n in finals}
    names = ["global_threshold", "per_script_threshold", *models]
    test_summary = {n: summarise(test, answered_mask(n, test, policy)) for n in names}
    hard = test[test["hard"] & (test["lang"] == "en")]
    hard_policy = {**policy, "proba": {n: finals[n].predict_proba(hard[FEATURES].to_numpy())[:, 1] for n in finals}}
    test_hard = {n: summarise(hard, answered_mask(n, hard, hard_policy))["en"] for n in names}
    en_rows = int((~test_rows["q_core"].map(is_devanagari)).sum())
    coverage = {n: test_summary[n]["en"]["answered"] / en_rows for n in names}

    # End-to-end: production engine with the Stage 2 rule vs the candidate.
    print("End-to-end checks ...", flush=True)
    engine = TriageEngine.load()
    reference = parity_reference(engine)
    before = engine_checks(engine, reference, closeness, close_t)
    candidate_policy = AnswerPolicy(mode="model", threshold=policy["model_threshold"][best_model],
                                    min_similarity=MIN_SIMILARITY, model=finals[best_model], closeness=closeness)
    script_policy = AnswerPolicy(mode="per_script", threshold=policy["script"]["devanagari"],
                                 min_similarity=MIN_SIMILARITY, script_thresholds=policy["script"])
    engine.gate = Gate(answer_policy=candidate_policy)
    after_model = engine_checks(engine, reference, closeness, close_t)
    engine.gate = Gate(answer_policy=script_policy)
    after_script = engine_checks(engine, reference, closeness, close_t)

    # Decision (rule in the module docstring).
    def meets_a(s):
        ok_en = s["en"]["close_rate"] is None or s["en"]["close_rate"] >= target
        ok_dev = s["devanagari"]["close_rate"] is None or s["devanagari"]["close_rate"] >= target
        return ok_en and ok_dev

    def meets_cd(after):
        dose = sum(v["answered"] for v in after["dose"].values())
        return dose == 0 and after["probes_pass"] >= before["probes_pass"]

    g, ps, mb = (test_summary[n] for n in ("global_threshold", "per_script_threshold", best_model))
    log = [
        f"Best model on validation (most close answers out-of-fold at its cut-off): `{best_model}`.",
        f"(a) close rate >= {target:.1%}: model en {_rate(mb['en'])}, devanagari {_rate(mb['devanagari'])} -> "
        f"{'met' if meets_a(mb) else 'NOT met'}; per-script en {_rate(ps['en'])}, devanagari {_rate(ps['devanagari'])} -> "
        f"{'met' if meets_a(ps) else 'NOT met'}.",
        f"(b) close answers on the test pool: model {mb['all']['close']}, per-script {ps['all']['close']}, "
        f"global {g['all']['close']}.",
        f"(c) dose questions answered: model {sum(v['answered'] for v in after_model['dose'].values())}, per-script "
        f"{sum(v['answered'] for v in after_script['dose'].values())}; chemical answers served: 0 by construction "
        "(the policy is only reached after the CHEMICAL_ANSWER rule).",
        f"(d) probes: Stage 2 {before['probes_pass']}, model {after_model['probes_pass']}, per-script "
        f"{after_script['probes_pass']} (of {before['probes']}).",
        f"Not part of the rule, for reading it: the Stage 2 rule itself is close {_rate(g['en'])} on English test "
        f"questions, {'above' if (g['en']['close_rate'] or 0) >= target else 'BELOW'} the {target:.1%} target. "
        "Criterion (b) counts close answers without asking whether the baseline meets (a).",
    ]
    if meets_a(mb) and meets_cd(after_model) and mb["all"]["close"] > max(ps["all"]["close"], g["all"]["close"]):
        decision, adopted, after, cand = f"model ({best_model})", candidate_policy, after_model, best_model
    elif meets_a(ps) and meets_cd(after_script) and ps["all"]["close"] > g["all"]["close"]:
        decision, adopted, after, cand = "per-script similarity threshold", script_policy, after_script, "per_script_threshold"
    else:
        decision, after, cand = "keep the Stage 2 rule", after_model, best_model
        adopted = AnswerPolicy(mode="none", threshold=1.01, min_similarity=MIN_SIMILARITY)

    def data_rows(pool, asked):
        return {lang: {"asked": asked.get(lang, 0), "pool": int((pool["lang"] == lang).sum()),
                       "close": int(pool.loc[pool["lang"] == lang, "close"].sum())} for lang in ["en", *LANGS]}

    data = {"valid": data_rows(valid, asked_valid), "test": data_rows(test, asked_test)}

    adopted.meta = {"decision": decision, "target_close_rate": target, "trained_rows": int(len(y)),
                    "features": FEATURES, "built": time.strftime("%Y-%m-%d %H:%M")}
    adopted.save()

    metrics = {
        # Same reference the Stage 2 target came from (validation calls, train-only KB).
        "target": target, "close_threshold": close_t,
        "advisor_agreement": stage2["advisor_agreement_valid"]["close_rate"],
        "data": data, "models": models, "sim_auc": sim_auc,
        "policy": {k: v for k, v in policy.items() if k != "proba"},
        "test": test_summary, "test_english_hard": test_hard, "test_rows": en_rows, "coverage": coverage,
        "engine": {"before": before, "after": after}, "candidate": cand,
        "engine_model": after_model, "engine_per_script": after_script,
        "decision": decision, "decision_log": log,
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "answerability_metrics.json").write_text(json.dumps(metrics, indent=2, default=float), encoding="utf-8")
    report = write_report(metrics)
    (REPORT_DIR / "answerability_report.md").write_text(report, encoding="utf-8")
    print(report)
    return metrics


if __name__ == "__main__":
    main()
