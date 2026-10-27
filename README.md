# KCC Farmer Helpline Assistant - Data Cleaning (Stage 1)

This repository contains the end-to-end data cleaning pipeline for the **Kisan Call Centre (KCC)** Maharashtra dataset (`2023-11` to `2025-07`), standardising 361,181 caller records in accordance with the project Source of Truth and Stage 1 specification.

---

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
│   └── district_display.csv     # Mapping from dataset district spellings to display names
├── data/
│   ├── raw/                     # Ingested unzipped raw CSVs (read-only, gitignored)
│   └── clean/                   # Cleaned output files (gitignored)
│       ├── kcc_mh_clean.parquet # MASTER Parquet (361,181 rows, 61 columns)
│       ├── kcc_mh_clean.csv     # MASTER UTF-8 CSV (361,181 rows)
│       └── monthly/             # 20 monthly partitions (kcc_mh_2023_11.csv to kcc_mh_2025_07.csv)
├── docs/
│   ├── kcc_source_of_truth.md   # Project source of truth
│   └── kcc_data_cleaning_stage1.md # Stage 1 detailed specification
├── reports/
│   ├── cleaning_report.md       # Full executive cleaning summary & metrics
│   ├── file_manifest.csv        # Input file manifest with MD5 hashes and status
│   ├── value_counts/            # Distributions for QueryType, Category, Crop, District, Language
│   └── samples/                 # 50-row audit samples per flag and language for human review
├── src/
│   ├── __init__.py
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
    └── test_clean.py            # Comprehensive 11-test acceptance suite
```

---

## 3. Key Findings & Invariants

1. **Raw Ingestion:** 21 CSV files ingested (370,702 raw rows).
2. **Duplicate File Resolution:** `mh-2024-2.csv` (MD5 `9b2d54ddedee588ffa3df4b34c6786da`) is a byte-identical copy of `mh-2024-1.csv` containing January 2024 records. February 2024 is missing from data.gov.in and marked `missing`.
3. **Master Size:** 361,181 rows with **100% unique `KCCCallID`s** across all files.
4. **Phone Redaction:** 2,364 rows with 10-digit mobile numbers redacted to `[PHONE]`; toll-free and scheme numbers (`1800...`, `1947`, `14447`, `155261`) strictly preserved.
5. **Weather & Template Tracking:** 150,698 weather templates (41.72%) and 5,813 mandi templates (1.61%) preserved in the master and flagged with `flag_dated_answer` for downstream routing.
