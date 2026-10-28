"""CER and route-agreement evaluation for the opt-in voice set."""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
import re
import unicodedata

from src.assistant.config import REPO_ROOT
from src.assistant.stt import transcribe_audio
from src.assistant.translate import AssistantUnavailable

EVAL_CSV = REPO_ROOT / "config" / "voice_eval.csv"
AUDIO_ROOT = REPO_ROOT / "data" / "voice_eval"


def _normalise(text: str) -> str:
    text = unicodedata.normalize("NFC", text or "").casefold()
    return re.sub(r"\s+", " ", text).strip()


def character_error_rate(reference: str, hypothesis: str) -> float | None:
    """Return codepoint CER; None means the reference is empty."""
    ref, hyp = _normalise(reference), _normalise(hypothesis)
    if not ref:
        return None
    previous = list(range(len(hyp) + 1))
    for i, rchar in enumerate(ref, 1):
        current = [i]
        for j, hchar in enumerate(hyp, 1):
            current.append(min(current[-1] + 1, previous[j] + 1,
                               previous[j - 1] + (rchar != hchar)))
        previous = current
    return previous[-1] / len(ref)


def _read_rows() -> list[dict]:
    with EVAL_CSV.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def evaluate(engine, *, rows: list[dict] | None = None, transcriber=None) -> tuple[str, list[dict]]:
    """Run STT and compare its route to typed reference routing. External STT is injectable."""
    rows = _read_rows() if rows is None else rows
    transcriber = transcriber or transcribe_audio
    results, missing = [], []
    root = AUDIO_ROOT.resolve()
    for row in rows:
        candidate = (root / row["file"]).resolve()
        if not candidate.is_relative_to(root):
            results.append({**row, "status": "invalid audio path"})
            continue
        if not candidate.is_file():
            missing.append(row["file"])
            results.append({**row, "status": "audio missing"})
            continue
        try:
            audio = candidate.read_bytes()
            content_type = "audio/wav" if candidate.suffix.lower() == ".wav" else "audio/mpeg"
            transcript = transcriber(audio, candidate.name, content_type)
        except AssistantUnavailable:
            results.append({**row, "status": "STT unavailable"})
            continue
        except Exception:
            results.append({**row, "status": "STT error"})
            continue
        if engine is None:
            results.append({**row, "status": "triage unavailable", "transcript": transcript["text"],
                            "cer": character_error_rate(row["reference_text"], transcript["text"]),
                            "typed_route": None, "voice_route": None, "route_agreement": None,
                            "expected_route_match": None})
            continue
        typed_route = engine.triage(row["reference_text"])["route"]
        voice_route = engine.triage(transcript["text"])["route"]
        results.append({
            **row, "status": "ok", "transcript": transcript["text"],
            "cer": character_error_rate(row["reference_text"], transcript["text"]),
            "typed_route": typed_route, "voice_route": voice_route,
            "route_agreement": typed_route == voice_route,
            "expected_route_match": (voice_route == row["expected_route"] if row.get("expected_route") else None),
        })

    per_lang: dict[str, list[dict]] = defaultdict(list)
    for result in results:
        if result.get("cer") is not None:
            per_lang[result["lang"]].append(result)
    lines = ["# Stage 3 - Voice evaluation", "", "CER is Unicode codepoint edit distance divided by reference length after NFC normalization and whitespace collapse. Route agreement compares triage of the typed reference with triage of the STT transcript.", ""]
    kinds = sorted({"synthetic" if r.get("speaker", "").startswith("synthetic") else "recorded" for r in rows})
    lines.append(f"Audio types in this run: {', '.join(kinds) if kinds else 'none'}.")
    lines.append("")
    lines += ["| Language | Audio evaluated | Mean CER | Route agreement |", "|---|---:|---:|---:|"]
    for lang in sorted({r.get("lang", "") for r in rows}):
        vals = per_lang.get(lang, [])
        cer = [r["cer"] for r in vals if r.get("cer") is not None]
        agrees = [r["route_agreement"] for r in vals if r.get("route_agreement") is not None]
        cer_summary = f"{sum(cer)/len(cer):.3f} ({len(cer)} samples)" if cer else "unavailable"
        route_summary = f"{sum(agrees)}/{len(agrees)}" if agrees else "unavailable"
        lines.append(f"| {lang} | {len(vals)} | {cer_summary} | {route_summary} |")
    lines += ["", "## Per-file outcomes", "", "| File | Speaker | Lang | Noisy | Status | CER | Typed route | Voice route | Agreement | Expected route match |", "|---|---|---|---|---|---:|---|---|:-:|:-:|"]
    for result in results:
        if result.get("cer") is not None:
            cer = "" if result["cer"] is None else f"{result['cer']:.3f}"
            expected = "" if result["expected_route_match"] is None else str(result["expected_route_match"])
            lines.append(f"| {result['file']} | {result['speaker']} | {result['lang']} | {result['noisy']} | {result['status']} | {cer} | {result['typed_route'] or ''} | {result['voice_route'] or ''} | {result['route_agreement'] if result['route_agreement'] is not None else ''} | {expected} |")
        else:
            lines.append(f"| {result['file']} | {result.get('speaker','')} | {result.get('lang','')} | {result.get('noisy','')} | {result['status']} | | | | | |")
    if missing:
        lines += ["", f"Audio files not present under the ignored `data/voice_eval/` directory: {', '.join(missing)}."]
    if not any(result.get("cer") is not None for result in results):
        lines += ["", "No CER or route-agreement score is reported because no audio was successfully evaluated."]
    if any(result.get("status") == "triage unavailable" for result in results):
        lines += ["", "Route agreement could not be calculated because the Stage 2 triage runtime is unavailable."]
    lines.append("")
    return "\n".join(lines), results


def main() -> None:
    from src.triage.engine import TriageEngine

    out = REPO_ROOT / "reports" / "stage3" / "voice_eval_report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = _read_rows()
    if not any((AUDIO_ROOT / row["file"]).is_file() for row in rows):
        report, _ = evaluate(None, rows=rows)
    else:
        try:
            engine = TriageEngine.load()
            report, _ = evaluate(engine, rows=rows)
        except FileNotFoundError as exc:
            report, _ = evaluate(None, rows=rows)
            report += (f"\nStage 2 triage unavailable: {exc}. CER is available if transcription succeeded; no route result is imputed.\n")
    out.write_text(report, encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
