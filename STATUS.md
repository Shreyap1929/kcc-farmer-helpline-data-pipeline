# Project Status - KCC Farmer Helpline Assistant

Running log of what has been built, by whom and when. Newest entries at the top.
Times are IST. Numbers come from the generated reports in `reports/`; re-run the
pipelines to refresh them, do not edit them by hand.

| Stage | Owner | Status | Finished |
|---|---|---|---|
| 1. Data cleaning | Shreya | Done | 2026-10-27 20:03 |
| 2. Triage core (text) | Amir | Done | 2026-10-27 22:50 |
| 3. Speech, LLM replies, expert queue, golden set | - | Not started | - |

---

## Stage 2 - Triage core (text)

**Done by Amir** - 2026-10-27, 20:30 to 22:50 IST
Design: [docs/stage2_triage_core.md](docs/stage2_triage_core.md)

### What was built

| Piece | Where | What it does |
|---|---|---|
| Content policy | `src/triage/policy.py` | Finds live-market/weather, scheme, dose and farm intent in English, Marathi and Hindi questions; finds chemical doses, forecasts, mandi prices and scheme dates in Marathi answers |
| Crop detection | `src/triage/crops.py`, `config/crop_lexicon.yaml` | 40 crops in four scripts/spellings, inflection-aware |
| Dataset views + split | `src/triage/views.py` | Policy-tagged corpus, knowledge base, chronological train/valid/test split |
| Embeddings | `src/triage/embeddings.py` | multilingual-e5-base, chosen by a measured 4-model probe; 95,804 questions cached |
| Classifiers | `src/triage/classifier.py` | Query type (13 classes) and crop (30): TF-IDF, embedding and ensemble variants |
| Query expansion | `src/triage/expansion.py`, `config/query_glossary.yaml` | Appends English farm terms to Marathi/Hindi questions before search |
| Retrieval | `src/triage/retrieval.py` | FAISS over distinct KB questions, crop/district/season boosts, answer-agreement stats |
| Gate | `src/triage/gate.py` | Six routes with reason codes; never auto-serves chemical or time-sensitive advice |
| Calibration + evaluation | `src/triage/evaluate.py`, `src/triage/crosslingual.py` | Thresholds from validation months; realistic/hard test; probes; cross-lingual check |
| API + console | `src/api/` | FastAPI (`/api/triage`, `/api/meta`, `/api/health`) and an offline-safe operator console |
| One-command build | `src/triage/build.py` | `python -m src.triage.build` rebuilds every artifact and report |
| Tests | `tests/test_policy.py`, `test_gate.py`, `test_evaluate.py`, `test_api.py`, `test_triage_artifacts.py` | 121 new tests; full suite 132/132 passing, including the 11 Stage 1 tests |

### Results (test months 2025-01..07, knowledge base frozen at 2024-12)

| Measure | Result |
|---|---|
| Chemical answers served automatically | **0** |
| Time-sensitive questions answered from history | **0.0%** (99.8% sent to a live/scheme pointer) |
| Questions whose real answer was chemical, answered automatically | 0.8% (served answer itself non-chemical) |
| Real farm questions wrongly called out of scope | 0.0% |
| Auto-answer coverage | 2.8% (deliberately conservative) |
| Answered cases close to the real advisor answer | 27.2%, vs 31.2% for a second real advisor on the same questions, vs 14.5% answering the same pool with no threshold |
| Query-type classifier, unseen questions | macro-F1 0.676 (majority baseline 0.024) |
| Crop classifier, unseen questions | macro-F1 0.915 |
| Marathi/Hindi held-out retrieval on topic | 3/12 plain -> **10/12** with glossary expansion |
| Probe questions routed as expected | 31/37 (the 6 misses fail safe to an expert and are documented) |
| API latency (warm, CPU) | ~60-170 ms per call |

### Findings worth knowing

- **Stage 1 date flags miss most dated content.** They match two exact template
  questions. The policy layer found 46,450 more time-sensitive rows (free-text market
  questions, per-piece prices, instalment dates and status, insurance deadlines), leaving
  a 157,705-row knowledge base.
- **Label noise caps classifier scores.** 62.7% of test rows belong to a question text
  that was labelled differently on different calls, so even a perfect lookup could
  agree with the labels at most 76.5% of the time.
- **Advisors disagree with each other.** Two real answers to the identical question are
  "close" only ~38% of the time, so the answer threshold is calibrated relative to
  that, and calibration disables auto-answering rather than silently falling back.
- **Plain multilingual embeddings are not enough for Marathi.** Against the real KB,
  Marathi questions mostly retrieved PM-Kisan questions until glossary expansion.
- **Leaks found by reading output, then fixed.** Console screenshots showed a per-piece
  mandi price and instalment-date answers in the KB. Each fix is covered by a test, and
  scheme questions about a date/status/instalment are now excluded structurally.

### Open items handed to Stage 3

- Golden set (hand-checked labels and answers) - all quality numbers are still proxies.
- Translate-to-English (or Whisper translate) for Marathi/Hindi; compare with expansion.
- Speech in/out, LLM reply rewriting with the existing number-grounding check, LangGraph
  expert queue (the gate's `draft_for_expert` / `answer_source` / `reasons` are its payload).
- Smoother threshold choice (it moved between 0.980 and 0.9825 with small KB changes).
- Licence/terms review of the data.gov.in resource (still open from Stage 1).

---

## Stage 1 - Data cleaning

**Done by Shreya** - committed 2026-10-27 20:03 IST
Spec: [docs/kcc_data_cleaning_stage1.md](docs/kcc_data_cleaning_stage1.md) - Report: [reports/cleaning_report.md](reports/cleaning_report.md)

- Ingested 21 raw monthly CSVs (370,702 rows); found and excluded `mh-2024-2.csv`, a
  byte-identical copy of January 2024 (February 2024 is missing upstream).
- Clean master of 361,181 rows, 61 columns (Parquet + CSV + 20 monthly files), with
  100% unique `KCCCallID`.
- Unicode/whitespace cleaning, label standardisation, district display mapping, season
  derived from month, `q_core` boilerplate stripping.
- Phone-number redaction (2,364 rows) with official helplines preserved.
- Quality flags (empty, incomplete, weather/mandi templates, too long, invalid district),
  duplicate keys (`qa_key`, `q_key`), heuristic answer language.
- Value counts, audit samples, file manifest, and an 11-test acceptance suite (passing).
