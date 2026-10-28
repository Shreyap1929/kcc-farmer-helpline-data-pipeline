"""
Choose the similarity threshold for reusing expert answers (same-language matching).

Pairs come from the cross-lingual parity set (`data/runtime/parity_translations.json`,
built by `python -m src.triage.crosslingual_parity`):

- same question: the parity Marathi/Hindi rephrasing vs a second, independently worded
  rephrasing of the same English question;
- different question: two rephrasings in the same language whose English questions got
  answers that are not close (Stage 2 closeness < answer_close_threshold), i.e. a reused
  answer would be wrong.

Rule: the lowest threshold at which no different-question pair (that also passes the
production crop check) matches, plus a 0.01 margin. Recall on same-question pairs at that
threshold is reported, not optimised.

    python -m src.review.calibrate_reuse
"""
from __future__ import annotations

import json
import time

import numpy as np

from src.assistant.config import get_groq_client
from src.triage.config import REPO_ROOT, load_config
from src.triage.crops import detect_crops
from src.triage.crosslingual_parity import CACHE, LANGS, _patient, _sample
from src.triage.embeddings import embed_texts
from src.triage.engine import TriageEngine
from src.triage.evaluate import Closeness

OUT = REPO_ROOT / "reports" / "stage4" / "reviewed_reuse_report.md"
SECOND = REPO_ROOT / "data" / "runtime" / "reuse_paraphrases.json"
N_SAME = 40
MARGIN = 0.01


def _second_paraphrase(client, text: str, lang: str) -> str:
    result = client.chat.completions.create(
        model="openai/gpt-oss-20b", temperature=0, reasoning_effort="low", max_completion_tokens=400,
        messages=[
            {"role": "system", "content": (
                f"A farmer asked this question in {LANGS[lang]}. Write how a different farmer would ask the "
                f"same thing in {LANGS[lang]}, with different words, in Devanagari, in one sentence. "
                "Keep the crop. Return only the question.")},
            {"role": "user", "content": text},
        ],
    )
    return (result.choices[0].message.content or "").strip()


def run() -> str:
    client = get_groq_client()
    engine = TriageEngine.load()
    close_t = load_config()["gate"]["answer_close_threshold"]
    closeness = Closeness(engine.retriever.records["ans_clean"].tolist())
    answerable, _ = _sample(engine)
    cache = json.loads(CACHE.read_text(encoding="utf-8"))
    second = json.loads(SECOND.read_text(encoding="utf-8")) if SECOND.exists() else {}

    lines_same, lines_diff, examples = [], [], []
    for lang in LANGS:
        items = [q for q in answerable if f"{lang}|{q['text']}" in cache]
        native = [cache[f"{lang}|{q['text']}"]["native"] for q in items]
        for q, a in zip(items[:N_SAME], native[:N_SAME]):
            key = f"{lang}|{q['text']}"
            if key not in second:
                second[key] = _patient(_second_paraphrase, client, a, lang)
                SECOND.write_text(json.dumps(second, ensure_ascii=False, indent=1), encoding="utf-8")
                time.sleep(2.1)
        va = embed_texts(native)
        vb = embed_texts([second[f"{lang}|{q['text']}"] for q in items[:N_SAME]])
        for i in range(min(N_SAME, len(items))):
            b = second[f"{lang}|{items[i]['text']}"]
            crop_ok = set(detect_crops(native[i])) == set(detect_crops(b))
            lines_same.append((lang, float(va[i] @ vb[i]), crop_ok, native[i], b))
        sims = va @ va.T
        answers = [q["answer"] for q in items]
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                if closeness([answers[i]], [answers[j]])[0] >= close_t:
                    continue  # effectively the same question: reuse would be right
                crop_ok = set(detect_crops(native[i])) == set(detect_crops(native[j]))
                lines_diff.append((lang, float(sims[i, j]), crop_ok, native[i], native[j]))

    diff_passing = sorted((s for _, s, ok, _, _ in lines_diff if ok), reverse=True)
    threshold = round(min(0.99, (diff_passing[0] if diff_passing else 0.9) + MARGIN), 3)
    same_hits = [s >= threshold and ok for _, s, ok, _, _ in lines_same]

    lines = [
        "# Reusing expert answers: threshold calibration (Stage 4)", "",
        "Method in `src/review/calibrate_reuse.py`. Questions are machine-written Marathi/Hindi "
        "rephrasings of unseen English test-month questions; real repeat questions will be noisier.", "",
        "| Measure | Value |", "|---|---:|",
        f"| Different-question pairs (answers not close), same language | {len(lines_diff)} |",
        f"| ...that also pass the crop check | {len(diff_passing)} |",
        f"| Highest similarity among those | {diff_passing[0]:.3f} |" if diff_passing else "| Highest similarity | n/a |",
        f"| **Chosen threshold** (highest + {MARGIN}) | **{threshold}** |",
        f"| Same-question pairs | {len(lines_same)} |",
        f"| Same-question similarity, median | {np.median([s for _, s, _, _, _ in lines_same]):.3f} |",
        f"| Same-question pairs reused at the threshold (recall) | {sum(same_hits)}/{len(same_hits)} ({sum(same_hits)/len(same_hits):.0%}) |",
        f"| Different-question pairs reused at the threshold | 0/{len(diff_passing)} (by construction) |",
        "",
        "Recall is deliberately not optimised: a missed reuse sends the farmer to an expert, a",
        "wrong reuse gives them someone else's answer.", "",
        "## Closest different-question pairs (what the threshold has to stay above)", "",
        "| Lang | Similarity | Question A | Question B |", "|---|---:|---|---|",
    ]
    for lang, s, ok, a, b in sorted((x for x in lines_diff if x[2]), key=lambda x: -x[1])[:8]:
        lines.append(f"| {lang} | {s:.3f} | {a} | {b} |")
    lines += ["", "## Same-question pairs (sample)", "", "| Lang | Similarity | Reused | Question A | Question B |",
              "|---|---:|:-:|---|---|"]
    for (lang, s, ok, a, b), hit in list(zip(lines_same, same_hits))[::5]:
        lines.append(f"| {lang} | {s:.3f} | {'yes' if hit else ''} | {a} | {b} |")
    lines.append("")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    return "\n".join(lines)


if __name__ == "__main__":
    print(run().split("## Closest")[0])
