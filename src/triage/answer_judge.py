"""
Independent check of automatic answers with an LLM judge (silver labels).

Every quality number so far uses one proxy: char n-gram closeness between the
served past answer and the real answer on that call. It rewards shared wording,
not shared advice. Here a different signal grades the same cases: an LLM reads
the farmer's question, the real advisor's answer and the answer the system would
serve, and says whether the farmer would get substantially the same advice.

Cases: test-month questions in the low-risk pool (built exactly as in
`answerability_train`, rephrasings cached) that each policy answers, sampled per
policy and language. Each case is judged once even if both policies answer it.

The judge is a model, not an agronomist: these are silver labels. They are used
(1) to check the Stage 5 decision with a label it was not tuned on, and (2) to
measure how often the char n-gram proxy agrees with a reading of the advice.

    python -m src.triage.answer_judge
"""
from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd

from src.triage.answerability import FEATURES, AnswerPolicy
from src.triage.answerability_train import MIN_SIMILARITY, N_DEV_TEST, TEST_SAMPLE, build_pool
from src.triage.classifier import QueryClassifier
from src.triage.config import REPO_ROOT, gate_thresholds, load_config, path
from src.triage.embeddings import load_question_embeddings
from src.triage.evaluate import EVAL_COLUMNS, Closeness
from src.triage.gate import Gate
from src.triage.retrieval import Retriever

CACHE = REPO_ROOT / "data" / "runtime" / "answer_judgements.json"
OUT = REPO_ROOT / "reports" / "stage5" / "answer_judge_report.md"
# One judge for every case: on a test pair gpt-oss-20b said "partly" where qwen and
# gpt-oss-120b said "same", so mixing judges would add noise that could favour one policy.
JUDGE_MODEL = "qwen/qwen3.8-27b"
PER_POLICY_EN = 200
SEED = 5

PROMPT = (
    "You check answers given by a farmers' helpline in Maharashtra. You get the farmer's question "
    "(as the operator noted it), the answer a real agriculture advisor gave on that call, and a "
    "candidate answer copied from an earlier call. Answers may be in Marathi, Hindi or English.\n"
    "Decide whether the candidate gives the farmer substantially the same advice as the real "
    "answer for this question:\n"
    "- same: same practical advice (same varieties/practice/source, wording may differ)\n"
    "- partly: overlaps but misses or changes something the farmer needs\n"
    "- different: other advice, other topic, or wrong for this question\n"
    'Reply as JSON: {"verdict": "same" | "partly" | "different", "reason": "<one short sentence in English>"}'
)


def _judge_one(client, model: str, question: str, real: str, candidate: str) -> dict:
    result = client.chat.completions.create(
        model=model, temperature=0, max_completion_tokens=300, response_format={"type": "json_object"},
        reasoning_effort="none",
        messages=[{"role": "system", "content": PROMPT},
                  {"role": "user", "content": f"Question: {question}\n\nReal answer: {real[:1200]}\n\n"
                                              f"Candidate answer: {candidate[:1200]}"}],
    )
    out = json.loads(result.choices[0].message.content)
    if out.get("verdict") not in ("same", "partly", "different"):
        raise ValueError("bad verdict")
    return {"verdict": out["verdict"], "reason": str(out.get("reason", ""))[:300], "model": model}


def judge_all(cases: pd.DataFrame) -> dict:
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    todo = cases[~cases["key"].isin(cache)]
    if len(todo):
        from src.assistant.config import get_groq_client

        client = get_groq_client()
        if client is None:
            raise SystemExit("GROQ_API_KEY is required to judge new cases")
        for n, row in enumerate(todo.itertuples(), 1):
            for attempt in range(10):
                try:
                    cache[row.key] = _judge_one(client, JUDGE_MODEL, row.q_core, row.ans_clean, row.best_answer)
                    break
                except Exception as exc:  # rate limit / malformed output: wait and retry
                    print(f"  case {n}: {type(exc).__name__}, retrying", flush=True)
                    time.sleep(5 * (attempt + 1))
            if n % 25 == 0 or n == len(todo):
                CACHE.parent.mkdir(parents=True, exist_ok=True)
                CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
                print(f"  judged {n}/{len(todo)}", flush=True)
            time.sleep(1.0)
    return cache


def main() -> str:
    split = load_config()["split"]
    stage2 = gate_thresholds()
    close_t = stage2["answer_close_threshold"]
    policy = AnswerPolicy.load()
    if policy is None or policy.mode != "model":
        raise SystemExit("the adopted answer policy is not a model; nothing to compare")

    corpus = pd.read_parquet(path("views") / "corpus_tagged.parquet", columns=EVAL_COLUMNS)
    corpus = corpus[corpus["is_valid_qa"] & (corpus["q_core"].str.len() >= 3)]
    q_index, q_emb = load_question_embeddings()
    test_rows = corpus[corpus["split"] == "test"].sample(min(TEST_SAMPLE, (corpus["split"] == "test").sum()),
                                                         random_state=42)
    print("Rebuilding the test pool (cached rephrasings) ...", flush=True)
    retr = Retriever.from_views(cutoff=split["valid_end"])
    pool, _ = build_pool(test_rows, retr, QueryClassifier.load(), Gate({**stage2, "answer_min_similarity": -1.0}),
                         policy.closeness, q_index, q_emb, N_DEV_TEST, close_t)
    del retr
    pool["proxy_close"] = pool["close"]
    p = policy.model.predict_proba(pool[FEATURES].to_numpy())[:, 1]
    pool["by_stage2"] = pool["similarity"] >= stage2["answer_min_similarity"]
    pool["by_model"] = (p >= policy.threshold) & (pool["similarity"] >= MIN_SIMILARITY)
    pool["key"] = pool["lang"] + "|" + pool["q_core"] + "|" + pool["best_answer"].str[:80] + "|" + pool["ans_clean"].str[:80]

    rng = np.random.default_rng(SEED)
    picks = []
    for col in ("by_stage2", "by_model"):
        for lang in ("en", "mr", "hi"):
            idx = np.flatnonzero((pool[col] & (pool["lang"] == lang)).to_numpy())
            cap = PER_POLICY_EN if lang == "en" else len(idx)
            picks.extend(rng.choice(idx, size=min(cap, len(idx)), replace=False).tolist())
    cases = pool.iloc[sorted(set(picks))].drop_duplicates("key")
    print(f"Judging {len(cases)} distinct answered cases ...", flush=True)
    verdicts = judge_all(cases)
    cases = cases.assign(verdict=cases["key"].map(lambda k: verdicts[k]["verdict"]))
    cases["acceptable"] = cases["verdict"] == "same"

    def rate(part: pd.DataFrame) -> str:
        n = len(part)
        if not n:
            return "-"
        k = int(part["acceptable"].sum())
        boots = [rng.choice(part["acceptable"].to_numpy(), n).mean() for _ in range(1000)]
        return f"{k}/{n} ({k / n:.0%}) [{np.percentile(boots, 2.5):.0%}-{np.percentile(boots, 97.5):.0%}]"

    lines = [
        "# Stage 5 - Independent check with an LLM judge (silver labels)", "",
        "Generated by `python -m src.triage.answer_judge`. Method in the module docstring. Judge: "
        f"`{JUDGE_MODEL}` for every case, temperature 0. The judge is a model, not an "
        "agronomist.", "",
        "## 1. Answers judged the same advice as the real advisor's", "",
        f"Test months; English: random {PER_POLICY_EN} answered cases per policy; Marathi/Hindi: every answered case.", "",
        "| Policy | English | Marathi + Hindi |", "|---|---|---|",
    ]
    for col, name in (("by_stage2", "Stage 2 similarity rule"), ("by_model", "Answerability model")):
        part = cases[cases[col]]
        lines.append(f"| {name} | {rate(part[part['lang'] == 'en'])} | {rate(part[part['lang'] != 'en'])} |")
    both = cases[cases["by_stage2"] & cases["by_model"]]
    only_s2 = cases[cases["by_stage2"] & ~cases["by_model"]]
    lines += ["", "Where the two policies disagree (English):", "",
              "| Cases | Judged same advice |", "|---|---|",
              f"| Answered by both | {rate(both[both['lang'] == 'en'])} |",
              f"| Answered only by the Stage 2 rule (the model sends them to an expert) | {rate(only_s2[only_s2['lang'] == 'en'])} |"]
    only_m = cases[~cases["by_stage2"] & cases["by_model"] & (cases["lang"] == "en")]
    if len(only_m):
        lines.append(f"| Answered only by the model | {rate(only_m)} |")

    agree = (cases["proxy_close"] == cases["acceptable"]).mean()
    tab = pd.crosstab(cases["proxy_close"].map({True: "proxy close", False: "proxy not close"}), cases["verdict"])
    lines += ["", "## 2. How far the char n-gram proxy can be trusted", "",
              f"Proxy and judge agree on **{agree:.0%}** of {len(cases)} judged cases.", "",
              "| | " + " | ".join(tab.columns) + " |", "|---|" + "---:|" * len(tab.columns)]
    for idx, row in tab.iterrows():
        lines.append(f"| {idx} | " + " | ".join(str(v) for v in row.values) + " |")
    lines += ["", "## 3. Examples", "", "| Lang | Question | Served answer | Real answer | Judge | Reason |",
              "|---|---|---|---|---|---|"]
    for row in cases.sample(min(12, len(cases)), random_state=SEED).itertuples():
        cells = [row.lang, row.q_core, row.best_answer[:140], row.ans_clean[:140], row.verdict,
                 verdicts[row.key]["reason"]]
        lines.append("| " + " | ".join(str(c).replace("|", "/").replace("\n", " ") for c in cells) + " |")
    lines.append("")
    report = "\n".join(lines)
    OUT.write_text(report, encoding="utf-8")
    cases.drop(columns=FEATURES).to_parquet(REPO_ROOT / "data" / "runtime" / "answer_judge_cases.parquet")
    return report


if __name__ == "__main__":
    print(main())
