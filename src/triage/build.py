"""
Build every Stage 2 artifact in order:

    views -> question embeddings -> classifiers -> gate calibration + evaluation
    -> cross-lingual check

    python -m src.triage.build                 # everything (~25 min on CPU, first run)
    python -m src.triage.build --from classifier

The embedding step reuses its cache when the questions have not changed.
"""
from __future__ import annotations

import argparse
import time

STEPS = ["views", "embeddings", "classifier", "evaluate", "crosslingual"]


def run_step(name: str) -> None:
    if name == "views":
        from src.triage.config import path
        from src.triage.views import build_views, views_report

        result = build_views()
        rep = path("reports")
        rep.mkdir(parents=True, exist_ok=True)
        (rep / "views_report.md").write_text(views_report(result["master"], result["kb"]), encoding="utf-8")
    elif name == "embeddings":
        from src.triage.embeddings import build_question_embeddings

        build_question_embeddings()
    elif name == "classifier":
        from src.triage.classifier import main

        main()
    elif name == "evaluate":
        from src.triage.evaluate import main

        main()
    elif name == "crosslingual":
        from src.triage.crosslingual import main

        main()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the KCC Stage 2 triage artifacts")
    parser.add_argument("--from", dest="start", choices=STEPS, default=STEPS[0], help="first step to run")
    args = parser.parse_args()
    for name in STEPS[STEPS.index(args.start):]:
        t = time.time()
        print(f"\n=== {name} ===", flush=True)
        run_step(name)
        print(f"=== {name} done in {time.time() - t:.0f}s ===", flush=True)


if __name__ == "__main__":
    main()
