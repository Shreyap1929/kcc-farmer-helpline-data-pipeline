"""Measure raw, glossary-expanded and translate-first triage variants."""
from __future__ import annotations

import pandas as pd

from src.assistant.config import get_groq_client
from src.assistant.language import detect_language
from src.assistant.translate import AssistantUnavailable, translate_to_english
from src.triage.config import CONFIG_DIR, REPO_ROOT
from src.triage.embeddings import embed_texts
from src.triage.engine import TriageEngine
from src.triage.expansion import expand_query
from src.triage.retrieval import Retriever


def _on_topic(question: str, keywords: str) -> bool:
    return any(term.lower() in question.lower() for term in keywords.split("|"))


def build_report(retrieval_rows: list[dict], route_rows: list[dict], *, translation_available: bool,
                 blocker: str | None = None) -> str:
    variants = ["plain", "expanded", "translate"]
    retrieval_scores = {name: sum(r["on_topic"] for r in retrieval_rows if r["variant"] == name)
                        for name in variants}
    route_scores = {name: sum(r["correct"] for r in route_rows if r["variant"] == name)
                    for name in variants}
    n_retrieval = len({r["index"] for r in retrieval_rows})
    n_routes = len({r["index"] for r in route_rows})
    exp_ret = retrieval_scores["expanded"]
    trans_ret = retrieval_scores["translate"]
    exp_route = route_scores["expanded"]
    trans_route = route_scores["translate"]
    adopt = translation_available and n_retrieval > 0 and n_routes > 0 and trans_ret > exp_ret and trans_route >= exp_route
    lines = [
        "# Stage 3 - Translate-first experiment", "",
        "Evaluation uses the frozen held-out retrieval keywords and Marathi/Hindi gate probes.",
        "The safety gate thresholds are unchanged. For adoption, translate-first must strictly",
        "improve held-out top-1 on-topic retrieval and must not reduce expected-route accuracy",
        "compared with current glossary expansion. English inputs are excluded from transformation",
        "and retain the existing query path.", "",
        "## Results", "",
        "| Variant | Held-out retrieval on topic | Gate routes correct |", "|---|---:|---:|",
    ]
    for variant in variants:
        ret = "unavailable" if variant == "translate" and not translation_available else f"{retrieval_scores[variant]}/{n_retrieval}"
        routes = "unavailable" if variant == "translate" and not translation_available else f"{route_scores[variant]}/{n_routes}"
        if not n_retrieval:
            ret = "unavailable"
        if not n_routes:
            routes = "unavailable"
        lines.append(f"| {variant} | {ret} | {routes} |")
    decision = "Adopt translate-first" if adopt else (
        "Do not adopt translate-first; comparison incomplete" if not translation_available or not n_retrieval or not n_routes
        else "Keep glossary expansion"
    )
    lines += ["", f"**Decision:** {decision}.", ""]
    if blocker:
        lines += [f"**Evaluation limitation:** {blocker}", ""]
    if not translation_available:
        lines += ["Translate-first scores are unavailable; no score or result is imputed.", ""]
    lines += ["## Retrieval examples and failures", "", "| Variant | Input | Top-1 KB question | Topic match |", "|---|---|---|:-:|"]
    for row in retrieval_rows:
        lines.append(f"| {row['variant']} | {row['text']} | {row['top1']} | {'yes' if row['on_topic'] else 'no'} |")
    lines += ["", "## Gate-probe route results", "", "| Variant | Input | Expected | Actual | Correct |", "|---|---|---|---|:-:|"]
    for row in route_rows:
        lines.append(f"| {row['variant']} | {row['text']} | {row['expected']} | {row['actual']} | {'yes' if row['correct'] else 'no'} |")
    lines.append("")
    return "\n".join(lines)


def evaluate(engine: TriageEngine, retriever: Retriever, *, client=None) -> str:
    held = pd.read_csv(CONFIG_DIR / "crosslingual_heldout.csv", dtype=str, keep_default_na=False)
    probes = pd.read_csv(CONFIG_DIR / "gate_probes.csv", dtype=str, keep_default_na=False)
    probes = probes[probes["lang"].isin(["mr", "hi"])].reset_index(drop=True)
    client = client if client is not None else get_groq_client()
    translation_available = client is not None
    translations: dict[str, str] = {}
    retrieval_rows = []
    route_rows = []

    if translation_available:
        try:
            unique = list(dict.fromkeys([*held["text"], *probes["text"]]))
            for text in unique:
                translations[text] = translate_to_english(text, detect_language(text), client=client)
        except AssistantUnavailable as exc:
            translations.clear()
            translation_available = False
            blocker = str(exc)
        else:
            blocker = None
    else:
        blocker = "GROQ_API_KEY/provider unavailable; translations were not attempted."

    fns = {
        "plain": lambda text: text,
        "expanded": expand_query,
        "translate": lambda text: translations.get(text, text),
    }
    for name, transform in fns.items():
        if name == "translate" and not translation_available:
            continue
        vectors = embed_texts([transform(text) for text in held["text"]])
        top_hits = retriever.search_batch(vectors, k=1)
        for index, (row, hits) in enumerate(zip(held.itertuples(), top_hits)):
            top = hits[0].question if hits else ""
            retrieval_rows.append({"index": index, "variant": name, "text": row.text, "top1": top,
                                   "on_topic": _on_topic(top, row.topic_keywords)})
        for index, row in enumerate(probes.itertuples()):
            text = row.text
            translation = translations.get(text) if translation_available else None
            decision = engine.triage(text, crop=row.profile_crop or None, translated_text=translation,
                                     retrieval_mode=name)
            route_rows.append({"index": index, "variant": name, "text": text,
                               "expected": row.expected_route, "actual": decision["route"],
                               "correct": decision["route"] == row.expected_route})

    return build_report(retrieval_rows, route_rows, translation_available=translation_available, blocker=blocker)


def main() -> None:
    out = REPO_ROOT / "reports" / "stage3" / "translate_first_report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        engine = TriageEngine.load()
        report = evaluate(engine, engine.retriever)
    except FileNotFoundError as exc:
        report = build_report([], [], translation_available=False,
                              blocker=f"Stage 2 runtime artifacts are missing: {exc}. Build required to measure.")
    out.write_text(report, encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
