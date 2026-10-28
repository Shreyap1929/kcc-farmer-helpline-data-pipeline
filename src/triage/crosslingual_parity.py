"""
Cross-lingual answer parity: does a Marathi or Hindi farmer get the answer an
English question gets?

The translate-first report compares retrieval topics on 12 phrases and routes on 14
probes, of which only one should be answered, so it cannot show the real gap: the
answer threshold (0.98) was calibrated on English questions, and Marathi/Hindi
questions reach the right record at ~0.86-0.91 similarity, so they are never answered.

Method:
1. Replay unseen English test-month questions through the production engine. Keep
   those it answers ("answerable") and those it sends to an expert for a dose
   ("dose", the safety set).
2. Rephrase each as a Marathi and a Hindi farmer question with one model
   (gpt-oss-20b), and translate those back to English with the production
   translator (a different model, so the round trip is not a copy).
3. Triage every Devanagari question twice: the production glossary-expanded path,
   and translate-first (English retrieval, gate signals from both texts).

Parity = answered with an answer close to the one the English question got (Stage 2
closeness: char n-gram cosine >= answer_close_threshold). Wrong = answered with a
non-close answer. Safety = any dose question answered (must be 0).

The questions are machine-written, cleaner than real farmer speech, so this is an
upper bound on parity; it is not a replacement for real recordings.

    python -m src.triage.crosslingual_parity
"""
from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd

from src.assistant.config import get_groq_client
from src.assistant.translate import translate_to_english
from src.triage.config import REPO_ROOT, load_config
from src.triage.engine import TriageEngine
from src.triage.evaluate import Closeness

OUT = REPO_ROOT / "reports" / "stage4" / "crosslingual_parity_report.md"
CACHE = REPO_ROOT / "data" / "runtime" / "parity_translations.json"
LANGS = {"mr": "Marathi", "hi": "Hindi"}
REPHRASE_MODEL = "openai/gpt-oss-20b"
SEED = 7
SCAN = 3000
MAX_ANSWERABLE = 80
MAX_DOSE = 40


def _sample(engine: TriageEngine) -> tuple[list[dict], list[dict]]:
    corpus = pd.read_parquet(REPO_ROOT / "data" / "views" / "corpus_tagged.parquet",
                             columns=["q_core", "split", "is_valid_qa", "crop_clean"])
    test = corpus[(corpus["split"] == "test") & corpus["is_valid_qa"]].drop_duplicates("q_core")
    latin = test[test["q_core"].str.fullmatch(r"[\x00-\x7f]+", na=False) & (test["q_core"].str.len() >= 12)]
    rows = latin.sample(min(SCAN, len(latin)), random_state=SEED)
    answerable, dose = [], []
    for row in rows.itertuples():
        if len(answerable) >= MAX_ANSWERABLE and len(dose) >= MAX_DOSE:
            break
        d = engine.triage(row.q_core)
        codes = {r["code"] for r in d["reasons"]}
        if d["route"] == "ANSWER" and len(answerable) < MAX_ANSWERABLE:
            answerable.append({"text": row.q_core, "answer": d["answer_source"]["answer"]})
        elif d["route"] == "EXPERT_REVIEW" and "DOSE_QUESTION" in codes and len(dose) < MAX_DOSE:
            dose.append({"text": row.q_core})
    return answerable, dose


def _rephrase(client, text: str, lang: str) -> str:
    result = client.chat.completions.create(
        model=REPHRASE_MODEL, temperature=0, reasoning_effort="low", max_completion_tokens=400,
        messages=[
            {"role": "system", "content": (
                f"Rewrite this question the way a farmer in Maharashtra would ask it in {LANGS[lang]}, "
                "in Devanagari script, in one short sentence. Keep crop names and numbers. "
                "Return only the question.")},
            {"role": "user", "content": text},
        ],
    )
    return (result.choices[0].message.content or "").strip()


def _patient(fn, *args, tries: int = 8):
    """Groq's free tier allows 30 requests a minute per model; wait and retry instead of failing."""
    for attempt in range(tries):
        try:
            return fn(*args)
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(4 * (attempt + 1))


def _translations(client, questions: list[str]) -> dict:
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    for text in questions:
        for lang in LANGS:
            key = f"{lang}|{text}"
            if key in cache:
                continue
            native = _patient(_rephrase, client, text, lang)
            back = _patient(lambda: translate_to_english(native, lang, client=client))
            cache[key] = {"native": native, "back": back}
            time.sleep(2.1)
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    return cache


def _score(engine, items, cache, closeness, close_t, *, answerable: bool) -> tuple[dict, list[dict]]:
    summary, rows = {}, []
    for lang in LANGS:
        for mode in ("expanded", "translate"):
            answered = close = 0
            for item in items:
                t = cache[f"{lang}|{item['text']}"]
                if mode == "translate":
                    d = engine.triage(t["native"], translated_text=t["back"], retrieval_mode="translate")
                else:
                    d = engine.triage(t["native"])
                is_answer = d["route"] == "ANSWER"
                is_close = bool(is_answer and answerable and closeness(
                    [d["answer_source"]["answer"]], [item["answer"]])[0] >= close_t)
                answered += is_answer
                close += is_close
                rows.append({"set": "answerable" if answerable else "dose", "lang": lang, "mode": mode,
                             "english": item["text"], "native": t["native"], "back": t["back"],
                             "route": d["route"], "close": is_close})
            n = len(items)
            summary[(lang, mode)] = {"n": n, "answered": answered, "close": close, "wrong": answered - close}
    return summary, rows


def run() -> str:
    client = get_groq_client()
    if client is None:
        raise SystemExit("GROQ_API_KEY is required for this experiment")
    engine = TriageEngine.load()
    close_t = load_config()["gate"]["answer_close_threshold"]
    closeness = Closeness(engine.retriever.records["ans_clean"].tolist())
    answerable, dose = _sample(engine)
    cache = _translations(client, [q["text"] for q in answerable + dose])
    ans_summary, ans_rows = _score(engine, answerable, cache, closeness, close_t, answerable=True)
    dose_summary, dose_rows = _score(engine, dose, cache, closeness, close_t, answerable=False)

    def pct(a, n):
        return f"{a}/{n} ({a / n:.0%})" if n else "n/a"

    lines = [
        "# Cross-lingual answer parity (Stage 4)", "",
        f"Source: {len(answerable)} unseen English test-month questions the production engine answers, and "
        f"{len(dose)} it sends to an expert as dose questions, each rephrased as a Marathi and a Hindi farmer "
        f"question by `{REPHRASE_MODEL}` and translated back by the production translator. See the module "
        "docstring in `src/triage/crosslingual_parity.py` for the method. Machine-written questions are "
        "cleaner than real speech, so these are upper bounds.", "",
        "## Answerable questions", "",
        "| Language | Mode | Answered | Same answer as English | Different answer |", "|---|---|---:|---:|---:|",
    ]
    for (lang, mode), s in ans_summary.items():
        lines.append(f"| {lang} | {mode} | {pct(s['answered'], s['n'])} | {pct(s['close'], s['n'])} | "
                     f"{pct(s['wrong'], s['n'])} |")
    lines += ["", "## Safety: dose questions (must never be answered)", "",
              "| Language | Mode | Answered |", "|---|---|---:|"]
    for (lang, mode), s in dose_summary.items():
        lines.append(f"| {lang} | {mode} | {pct(s['answered'], s['n'])} |")

    tr_close = sum(ans_summary[(l, "translate")]["close"] for l in LANGS)
    ex_close = sum(ans_summary[(l, "expanded")]["close"] for l in LANGS)
    tr_answered = sum(ans_summary[(l, "translate")]["answered"] for l in LANGS)
    tr_wrong = sum(ans_summary[(l, "translate")]["wrong"] for l in LANGS)
    dose_answered = sum(s["answered"] for s in dose_summary.values())
    wrong_share = tr_wrong / tr_answered if tr_answered else 0.0
    adopt = tr_close > ex_close and dose_answered == 0 and wrong_share <= 0.2
    lines += ["", "## Decision", "",
              "Rule (fixed before running): adopt translate-first for Devanagari questions in the chat if it "
              "gives more same-as-English answers than glossary expansion, answers no dose question in any "
              "mode, and at most 20% of its answers differ from the English answer.", "",
              f"Same-as-English answers: translate {tr_close} vs expanded {ex_close}; translate answers that "
              f"differ: {wrong_share:.0%}; dose questions answered: {dose_answered}.", "",
              f"**{'Adopt translate-first in the chat (expanded stays the fallback)' if adopt else 'Keep glossary expansion'}.**",
              "", "## Examples", "", "| Set | Lang | Mode | English | Farmer question | Back-translation | Route | Same |",
              "|---|---|---|---|---|---|---|:-:|"]
    rng = np.random.default_rng(SEED)
    picks = [ans_rows[i] for i in sorted(rng.choice(len(ans_rows), size=min(16, len(ans_rows)), replace=False))]
    picks += [r for r in dose_rows if r["route"] == "ANSWER"][:10]
    for r in picks:
        cells = [r["set"], r["lang"], r["mode"], r["english"], r["native"], r["back"], r["route"],
                 "yes" if r["close"] else ""]
        lines.append("| " + " | ".join(str(c).replace("|", "/").replace("\n", " ") for c in cells) + " |")
    lines.append("")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    return "\n".join(lines)


if __name__ == "__main__":
    report = run()
    print(report.split("## Examples")[0])
