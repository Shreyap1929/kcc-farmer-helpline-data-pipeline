# KCC Farmer Helpline Assistant

A triage assistant for a Kisan Call Centre (KCC) style helpline, built on 361,181 real
Maharashtra KCC records (`2023-11` to `2025-07`). A farmer's question goes in; the system
decides whether to answer from a past expert answer (with its source), ask a follow-up,
point to a live or official source, or hand the case to a human expert.

| Stage | What | Status |
|---|---|---|
| 1 | Data cleaning pipeline ([spec](docs/kcc_data_cleaning_stage1.md)) | Done |
| 2 | Triage core: content policy, classifiers, multilingual retrieval, routing gate, API + console ([design](docs/stage2_triage_core.md)) | Done |
| 3 | Farmer chat and voice: Whisper STT, grounded LLM rewriting, TTS, SQLite sessions ([design](docs/stage3_chat_voice.md), [fixes](docs/stage3_fixes_stage4_review.md)) | Done (fixed and measured end to end 2026-10-28) |
| 4 | Expert review: case queue, LangGraph resolution workflow, expert desk, answers delivered back to the farmer ([design](docs/stage3_fixes_stage4_review.md)) | Done (first cut) |
| 5 | Answerability model: learned "will this past answer fit?" in place of the similarity cut-off ([design](docs/stage5_answerability.md), [report](reports/stage5/answerability_report.md)) | Evaluated; not adopted by its pre-registered rule (team decision pending) |

Progress log: [STATUS.md](STATUS.md).

---

## Stage 2 - Triage core

```bash
pip install -r requirements.txt

# Build views, embeddings, classifiers, calibration and evaluation (~25 min on CPU, first run).
# Needs the Stage 1 master at data/clean/kcc_mh_clean.parquet.
python -m src.triage.build

# Serve the API and the operator console at http://localhost:8000
uvicorn src.api.app:app --port 8000

# Tests (unit tests need no data; artifact tests skip if nothing is built)
pytest -v
```

How it routes a call:

```text
question + caller profile ─► policy signals (en/mr/hi) ─┐
                         ─► crop named in question  ────┤
                         ─► e5 embedding ─► classifier ─┼─► gate ─► ANSWER | CLARIFY | SCHEME_POINTER
                                        └─► retrieval ──┘          LIVE_DATA_POINTER | EXPERT_REVIEW | OUT_OF_SCOPE
```

Results (generated, never hand-edited): [dataset views](reports/stage2/views_report.md) ·
[embedding model choice](reports/stage2/embedding_model_probe.md) ·
[classifiers](reports/stage2/classifier_report.md) · [gate evaluation](reports/stage2/gate_report.md)

Safety rules enforced in code and tests: chemical/dose questions and answers are never
answered automatically; weather, mandi prices and scheme status are never answered from
history; every automatic answer shows its KCC call id and date.

---

## Stage 3 - Farmer chat and voice

Stage 3 adds a farmer interface at `http://localhost:8000/chat`; the operator console
remains at `/`. It supports English, Marathi and Hindi typed chat, browser-recorded
voice notes, Groq Whisper transcription, grounded historical-answer rewriting, fixed
non-answer replies and text-only fallbacks. Expert cases are stored in local SQLite for
the Stage 4 expert desk at `/expert`.

> **Open the pages through the server** (`http://localhost:8000/chat`), not by
> double-clicking `chat.html`. Opened from disk the page has no API behind it, which is
> what produced "The service is unavailable right now" during Stage 3 testing; the page
> now says so explicitly.

The app needs the Stage 2 `data/views/` and `data/artifacts/` runtime outputs. With the
project virtual environment active, install the requirements and build those artifacts
once when absent:

```powershell
python -m pip install -r requirements.txt
python -m src.triage.build
```

Configure `GROQ_API_KEY` privately in a local `.env` (copy `.env.example` as a template),
then run:

```powershell
uvicorn src.api.app:app --port 8000
```

Open `/chat` for farmer chat, `/expert` for the expert desk or `/` for the operator console.
Set `EXPERT_TOKEN` in `.env` to require a token on the expert API (otherwise it is open,
fine only on a local machine). Without a Groq key, typed
chat uses the existing gate reply and voice reports unavailable. Generated audio and
SQLite runtime data are local and ignored by Git. Run the voice evaluation harness with
`python -m src.assistant.voice_eval`; synthetic outputs must not be interpreted as
real-speech quality measurements. Current implementation and validation status are in
[docs/stage3_progress.md](docs/stage3_progress.md) and [STATUS.md](STATUS.md).

---

## Stage 1 - Data cleaning

## 1. Quick Start

### Run the Pipeline
To extract raw data and execute all cleaning steps in one reproducible command:
```bash
python -m src.cleaning.run --raw data/raw --out data/clean --reports reports --config config
```

### Run Acceptance Tests
To verify all 11 acceptance tests:
```bash
pytest -v tests/test_clean.py
```

---

## 2. Directory Structure

```
clean_data/
├── config/
│   ├── season_map.yaml          # Mapping of month numbers to agricultural seasons (kharif, rabi, summer)
│   ├── district_display.csv     # Mapping from dataset district spellings to display names
│   ├── triage.yaml              # Stage 2: split months, model, retrieval boosts, gate settings
│   ├── crop_lexicon.yaml        # Stage 2: crop names in English / Marathi / Hindi / romanised
│   └── gate_probes.csv          # Stage 2: hand-written probe questions with expected routes
├── data/
│   ├── raw/                     # Ingested unzipped raw CSVs (read-only, gitignored)
│   ├── clean/                   # Cleaned output files (gitignored)
│   │   ├── kcc_mh_clean.parquet # MASTER Parquet (361,181 rows, 61 columns)
│   │   ├── kcc_mh_clean.csv     # MASTER UTF-8 CSV (361,181 rows)
│   │   └── monthly/             # 20 monthly partitions (kcc_mh_2023_11.csv to kcc_mh_2025_07.csv)
│   ├── views/                   # Stage 2: policy-tagged corpus + knowledge base (gitignored)
│   └── artifacts/               # Stage 2: embeddings, classifiers, thresholds (gitignored)
├── docs/
│   ├── kcc_source_of_truth.md   # Project source of truth
│   ├── kcc_data_cleaning_stage1.md # Stage 1 detailed specification
│   └── stage2_triage_core.md    # Stage 2 design
├── reports/
│   ├── cleaning_report.md       # Full executive cleaning summary & metrics
│   ├── file_manifest.csv        # Input file manifest with MD5 hashes and status
│   ├── value_counts/            # Distributions for QueryType, Category, Crop, District, Language
│   ├── samples/                 # 50-row audit samples per flag and language for human review
│   └── stage2/                  # Stage 2 generated reports and figures
├── src/
│   ├── __init__.py
│   ├── api/                     # Stage 2: FastAPI app + static operator console
│   ├── triage/                  # Stage 2: policy, crops, views, embeddings, classifier,
│   │                            #          retrieval, gate, engine, evaluate, build
│   └── cleaning/
│       ├── __init__.py
│       ├── constants.py         # Schema definitions, regexes, stopword sets
│       ├── dates.py             # ISO8601 tolerant date parsing & season mapping
│       ├── duplicates.py        # Exact and near-duplicate key computation
│       ├── flags.py             # Quality, template, and exclusion flag evaluation
│       ├── labels.py            # Categorical label standardisation & missing token handling
│       ├── language.py          # Devanagari script ratio & Marathi/Hindi function word heuristics
│       ├── manifest.py          # ZIP extraction, file hashing & duplicate file detection
│       ├── pii.py               # Indian mobile number redaction with helpline preservation
│       ├── pipeline.py          # End-to-end pipeline orchestration
│       ├── reports.py           # Markdown report, value counts, and sampling generator
│       ├── run.py               # CLI runner
│       └── text_utils.py        # NFC normalization, whitespace collapsing & core query extraction
└── tests/
    ├── test_clean.py            # Comprehensive 11-test acceptance suite
    ├── test_policy.py           # Stage 2: policy detectors and crop detection
    ├── test_gate.py             # Stage 2: every gate route + safety invariant
    ├── test_api.py              # Stage 2: API contract with a fake engine
    └── test_triage_artifacts.py # Stage 2: split, KB and leakage invariants on built data
```

---

## 3. Key Findings & Invariants

1. **Raw Ingestion:** 21 CSV files ingested (370,702 raw rows).
2. **Duplicate File Resolution:** `mh-2024-2.csv` (MD5 `9b2d54ddedee588ffa3df4b34c6786da`) is a byte-identical copy of `mh-2024-1.csv` containing January 2024 records. February 2024 is missing from data.gov.in and marked `missing`.
3. **Master Size:** 361,181 rows with **100% unique `KCCCallID`s** across all files.
4. **Phone Redaction:** 2,364 rows with 10-digit mobile numbers redacted to `[PHONE]`; toll-free and scheme numbers (`1800...`, `1947`, `14447`, `155261`) strictly preserved.
5. **Weather & Template Tracking:** 150,698 weather templates (41.72%) and 5,813 mandi templates (1.61%) preserved in the master and flagged with `flag_dated_answer` for downstream routing.
