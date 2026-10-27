# KCC Data Cleaning – Stage 1: Standardise the Data

Spec for the teammate's coding AI. Inputs: `2025-dataset.zip`, `DATASETS.zip`, `kcc_source_of_truth.md`. Numbers below come from inspecting the real files, not from the ChatGPT report.

## 0. How to use this document

- Read `kcc_source_of_truth.md` first (sections 4, 8, 9, 10). This document is the detailed instruction for **Stage 1 only**. If the two disagree, the source of truth wins, except for the file facts in section 1, which were measured on the actual files (update the source of truth to match).
- **Goal:** produce one clean, typed, documented master dataset, plus one file per month and an audit report, that every later stage (language audit, classifier, retrieval index, golden corpus, evaluation) can read directly without further cleaning.
- **Stage 1 does not:** train models, translate text, build the golden corpus, create train/test splits, or decide which rows are used for which task.
- **Core principle: add, don't destroy.** Keep every raw column untouched. Put cleaned values in new columns. Remove rows only for exact duplicates and the duplicated file. Everything else is **flagged, not deleted**. Later stages choose what to filter.

## 1. What is really in the ZIPs (verified)

- `2025-dataset.zip` → `2025-dataset/mh-2025-1.csv` … `mh-2025-7.csv` (Jan–Jul 2025).
- `DATASETS.zip` → `DATASETS/mh-2023-11.csv`, `mh-2023-12.csv`, `mh-2024-1.csv` … `mh-2024-12.csv`.
- 21 CSV files, 370,702 raw rows, identical 15 columns in every file: `BlockName, Category, CreatedOn, Crop, DistrictName, KCCCallID, KccAns, QueryText, QueryType, Season, Sector, StateName, day, month, year` (order may differ between files; match by name).
- Encoding is UTF-8. Always read with pandas `dtype=str, keep_default_na=False, encoding="utf-8"`. **Never open and re-save in Excel** (corrupts Marathi).
- **`mh-2024-2.csv` is a byte-identical copy of `mh-2024-1.csv`.** Same MD5, 9,521 rows, all dated 1–31 January 2024. It is not February. **February 2024 is missing from the data.**
- File names are not zero-padded and cannot be trusted for the month. Derive the month from `CreatedOn`.
- `mh-2025-7.csv` ends on 29 July 2025, so July 2025 is a partial month.
- After dropping the duplicate file: **361,181 rows, and `KCCCallID` is unique across all of them** (no ID repeats across files). So there are no exact-duplicate rows left to remove.
- `StateName` is always `MAHARASHTRA`. `Season` is always the string `NA`. `day/month/year` agree with `CreatedOn` in 100% of rows.
- `QueryText` is always English and never contains Devanagari. It is the call-taker's English summary, not the farmer's words (about 37% of rows are fully uppercase). `KccAns` is about 97% Devanagari script.

Rows per month (use these to reconcile):

| Month | Rows | Month | Rows |
| --- | --- | --- | --- |
| 2023-11 | 13,178 | 2024-09 | 24,210 |
| 2023-12 | 13,633 | 2024-10 | 26,379 |
| 2024-01 | 9,521 | 2024-11 | 12,725 |
| 2024-02 | **missing** | 2024-12 | 17,093 |
| 2024-03 | 9,161 | 2025-01 | 12,065 |
| 2024-04 | 10,219 | 2025-02 | 14,685 |
| 2024-05 | 10,447 | 2025-03 | 15,146 |
| 2024-06 | 27,694 | 2025-04 | 12,370 |
| 2024-07 | 27,864 | 2025-05 | 14,804 |
| 2024-08 | 32,163 | 2025-06 | 30,413 |
|  |  | 2025-07 | 27,411 (to 29 Jul) |

These sum to 361,181. Note the source of truth currently says Jan and Feb 2025 are "about 12k" each; the real numbers are 12,065 and 14,685.

## 2. Folder layout and outputs

```
kcc-project/
  data/raw/                 # unzipped originals, read-only, never edited, not in Git
  data/clean/
    kcc_mh_clean.parquet    # MASTER (all 361,181 rows, raw + cleaned + flag columns)
    kcc_mh_clean.csv        # same, UTF-8, for people who need CSV
    monthly/kcc_mh_2024_03.csv ... kcc_mh_2025_07.csv   # one per real month, from CreatedOn
  reports/
    file_manifest.csv       # one row per input file (see step 1)
    cleaning_report.md      # counts for every step and flag
    value_counts/           # QueryType, Category, Crop, Sector, District, answer_lang
    samples/                # 50-row samples per flag for human review
  src/cleaning/             # pipeline code, one function per step, runnable end to end
  tests/test_clean.py       # assertions from section 6
```

The pipeline must be **one reproducible command** (for example `python -m src.cleaning.run --raw data/raw --out data/clean`). Re-running it gives the same output. No manual edits to outputs.

## 3. Pipeline steps (do them in this order)

### Step 1. Ingest and manifest

- Unzip both archives into `data/raw/`. Treat raw as read-only.
- For each CSV record in `reports/file_manifest.csv`: file name, MD5, row count, min and max `CreatedOn`, column list, and `status` (`used`, `duplicate_of:<file>`, `partial_month`).
- Add to every row: `source_file` (file name) and `source_row` (0-based row number in that file) for provenance.

### Step 2. Remove the duplicated file

- Detect duplicate files by MD5 (do not hard-code the name). Keep `mh-2024-1.csv`, mark `mh-2024-2.csv` as `duplicate_of:mh-2024-1.csv`, exclude it.
- Write `2024-02` as **missing** in the manifest. Never relabel January as February.
- Then assert: no `KCCCallID` repeats. If any do, drop exact full-row repeats, and write rows that share an ID but differ to `reports/id_conflicts.csv` for review.

### Step 3. Combine

Concatenate all used files into one dataframe with all columns as strings. Keep the original raw columns as they are, and create cleaned versions as new columns (section 4).

### Step 4. Types and dates

- `KCCCallID`: keep as **string** (3 to 7 digits).
- `CreatedOn`: parse to a timestamp with a tolerant parser (fractional seconds vary, such as `.4`, `.78`, `.613`). Store as `created_on`. Treat as local time, no timezone.
- Derive `date`, `year`, `month`, `year_month` (e.g. `2025-03`), `day_of_week`. Assert they match the raw `year`, `month`, `day`. If any row disagrees, flag it in `flag_date_mismatch` and trust `CreatedOn`.
- Raw `day/month/year` stay as raw columns; use the derived ones downstream.

### Step 5. Unicode and whitespace

For every text and label column when creating the cleaned version:

1. Normalise Unicode to NFC.
2. Replace tabs, newlines, carriage returns and repeated spaces with a single space.
3. Strip leading and trailing whitespace (and zero-width characters such as U+200B, U+200C, U+200D, U+FEFF).

Do not change case in this step. Do not strip bullets, asterisks, greetings (`नमस्कार सर,`) or sign-offs from answers. That is Stage 2 work.

### Step 6. Missing-value tokens

Treat these as missing (null) in the cleaned columns: empty string, `NA`, `N/A`, `NULL`, `NONE`, `-` (case-insensitive after stripping). Keep the raw value in the raw column. `Others` is a **real value**, not missing (it is about 45% of `Category` and `Crop`).

### Step 7. Label standardisation (`QueryType`, `Category`, `Crop`, `Sector`)

- `QueryType`: raw values such as `\tPlant Protection\t` and `\tWater Management\t` carry tab characters. After step 5 there are **72 distinct non-empty values** (73 before stripping, 1,917 missing). Store as `query_type_clean`.
- `Category` (about 35 distinct) → `category_clean`. `Crop` (about 284 distinct) → `crop_clean`. Only whitespace and missing-token fixes. **Do not merge, rename or regroup labels.** Some are ambiguous (for example the rare fisheries labels with 1 to 2 rows). Report their counts, do not guess.
- `Sector`: valid values are `AGRICULTURE`, `HORTICULTURE`, `ANIMAL HUSBANDRY` and similar words. About 756 rows have numeric values such as `10749`, `10717`. Set `sector_clean` to null for those, set `flag_sector_numeric = True`, keep the raw value. Do not map to "Others".
- Never infer a missing `Crop` or `QueryType` from other text in Stage 1.

### Step 8. District and block

- `DistrictName` has 38 raw values, including junk: `'0   '` and `'9999'`, and `Mumbai Suburban` (different casing from the rest). Create `district_clean`: strip, uppercase, junk values → null with `flag_district_invalid = True`. Count the affected rows in the report.
- **Keep the dataset's own spelling as the key** (`YEVATMAL`, `AHMADNAGAR`, `NASIK`, `AURANGABAD`, `OSMANABAD`, `GONDIYA`, `RAIGARH`, `MUMBAI`). Do not silently rename. Optionally add a separate `district_display` column from a small, visible mapping file `config/district_display.csv` (for example AURANGABAD → Chhatrapati Sambhajinagar, OSMANABAD → Dharashiv, NASIK → Nashik). The key column never changes.
- `BlockName` (about 255 missing) → `block_clean`: strip, uppercase, missing tokens → null.

### Step 9. Text columns

Create for each of `QueryText` and `KccAns`:

- `q_clean` / `ans_clean`: step 5 output, original case and script kept. **These are the columns every later stage reads.**
- `q_norm` / `ans_norm`: lowercase (Latin only), punctuation and symbols removed, spaces collapsed. Used only for template detection and de-duplication keys, not for embeddings.
- `q_core`: `q_clean` with the template prefix removed, so embeddings focus on content. Before writing the rule, list the 30 most common first-four-word prefixes and strip only those that are clearly boilerplate (expected: `FARMER ASKED ABOUT`, `FARMER ASKED QUERY ON`, `FARMER ASKED QUERY ABOUT`, `FARMER ASKED`). If stripping leaves fewer than 3 characters, keep `q_clean`.
- `ans_digits_ascii`: `ans_clean` with Devanagari digits (०–९) converted to 0–9. Answers contain doses like `०.००१%` and `००:५२:३४`; the later "every number in the reply must appear in the source" check needs one digit system. Keep `ans_clean` itself unchanged.
- `q_len`, `ans_len`: character lengths of the cleaned text.
- **Never truncate** long text. Max lengths seen: `QueryText` 34,118 characters, `KccAns` over 10,000. Flag instead (step 10).

### Step 10. Flags (all boolean columns; none of them deletes a row)

| Flag | Rule | Expected count |
| --- | --- | --- |
| `flag_q_empty` | `q_clean` null or under 3 characters | 22 empty, 25 under 5 chars |
| `flag_ans_empty` | `ans_clean` null or under 10 characters | 27 empty, 86 under 10 chars |
| `flag_incomplete_call` | `q_norm` contains `incomplete call` | about 470 |
| `flag_weather_template` | `q_norm == "farmer asked query on weather"` | **150,691 (41.7%)** |
| `flag_mandi_template` | `q_norm == "farmer asked query on mandi details"` | about 6,000 |
| `flag_dated_answer` | weather or mandi template (answer is a forecast or price valid only on that day) | derived |
| `flag_q_too_long` | `q_len > 1000` | about 257 |
| `flag_ans_too_long` | `ans_len > 3000` | about 145 |
| `flag_sector_numeric`, `flag_district_invalid`, `flag_date_mismatch` | steps 4, 7, 8 | as found |
| `flag_pii_phone_redacted` | step 12 | as found |
| `is_valid_qa` | not `flag_q_empty`, not `flag_ans_empty`, not `flag_incomplete_call` | derived |

Also write `exclude_reason` (text, comma-separated list of the flags that apply, or empty). **The weather template rows stay in the master.** Their answers are real, dated weather forecasts for a named taluka, which the gate's live-data route (source of truth section 7, route 4) needs to learn from, but they are useless as ordinary knowledge-base answers. Stage 2 decides per task.

### Step 11. Derived columns

**Season** (the raw column is 100% `NA`): add `season_derived` from `month`. Default mapping, kept in `config/season_map.yaml` so the team can change it: Jun–Oct = `kharif`, Nov–Feb = `rabi`, Mar–May = `summer`. Mark in the report that this is an approximation. Drop the raw `Season` from any feature list but keep the raw column.

**Answer script**: `ans_script` from the share of Devanagari letters among all letters in `ans_clean`: above 0.9 = `devanagari`, below 0.1 = `latin`, else `mixed`, and `none` if no letters. Measured on the data: about 351,691 devanagari, 7,506 mixed, 1,984 latin.

**Answer language (first pass heuristic)**: `answer_lang` ∈ `marathi | hindi | english | unclear`, plus `lang_confidence` (0–1). Rules:

- `english` if `ans_script == latin`.
- For Devanagari text count **unambiguous** function words only. Marathi: `आहे, आहेत, नाही, करावी, करावा, द्यावे, घ्यावे, मध्ये`. Hindi: `है, हैं, नहीं, करें, कृपया, में, आपको`. Do not use words that both languages share (`का`, `की`, `को` and similar); a quick test showed such lists give false Hindi matches.
- `marathi` or `hindi` if one side has at least 2 hits and at least twice the other. Otherwise `unclear`. `lang_confidence` = winning share of hits.
- **This is a heuristic.** Marathi and Hindi share a script, so it cannot be trusted until a human reads about 50 rows per language and the word lists are adjusted. Put those samples in `reports/samples/answer_lang_*.csv`. The report must also contain the table `district_clean × answer_lang` (this is the "answer language varies by district" observation from the source of truth).
- `QueryText` is always English, so add no query-language column; add `q_script = latin` only as a sanity check and report if any row differs.

### Step 12. Phone numbers and personal data

The source of truth requires redaction of names and phone numbers.

- Convert Devanagari digits to ASCII for detection only. Detect Indian mobile numbers with `(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)` (also allow a single space or hyphen inside the number).
- In `q_clean` and `ans_clean` replace each match with `[PHONE]`. Set `flag_pii_phone_redacted`. The raw columns stay as they are (raw data is private and never committed).
- **Do not redact helpline and scheme numbers**: toll-free numbers starting `1800` or `1947`, and short codes of 6 digits or fewer such as `14447`, `155261`. They are useful scheme pointers. Report the 20 most frequent numbers that were redacted and the 20 most frequent that were kept, so a human can check the boundary.
- Measured before redaction: about 1,126 answers and 6 questions contain a 10-digit mobile-like number. Some may be officials' contact numbers rather than farmers'; redact anyway and note the count.
- Names cannot be found reliably with rules. Do not try automatic name removal. Instead, write 100 random `ans_clean` values to `reports/samples/pii_review.csv` for a human check.

### Step 13. Near-duplicate keys (flag only, no removal)

Many answers are template-like and repeated questions are common, which later causes train/test leakage.

- `qa_key` = MD5 of `q_norm + "||" + ans_norm`; `qa_dup_count` = rows sharing that key (measured: about 50,072 rows are repeats of an earlier identical question and answer).
- `q_key` = MD5 of `q_norm`; `q_dup_count`.
- `is_first_occurrence` = earliest `created_on` within the same `qa_key`.
- **Do not drop these rows.** Chronological splitting and the "hard mode" evaluation in the source of truth (section 10) need them to be present and labelled.

### Step 14. Write outputs

- Master: Parquet (primary) and CSV (UTF-8). Column order as in section 4. Nulls written as real nulls in Parquet and empty cells in CSV.
- Monthly files `kcc_mh_YYYY_MM.csv` from `year_month` (source of truth naming). Only months that exist; do not create an empty `2024_02`.
- Run the tests in section 6 and fail loudly if any assertion breaks.

### Step 15. Cleaning report (`reports/cleaning_report.md`)

Must contain: the manifest; row counts before and after each step (370,702 → 361,181); every flag count; label counts (`query_type_clean`, `category_clean`, `crop_clean`, `sector_clean`, `district_clean`); rows per month and per month the weather-template share; `answer_script` and `answer_lang` counts; district × answer language table; the 50 most repeated questions; list of anything unexpected, with row counts.

## 4. Master schema (final columns)

| Group | Columns |
| --- | --- |
| Identity and provenance | `KCCCallID` (str), `source_file`, `source_row` |
| Raw (unchanged) | `BlockName, Category, CreatedOn, Crop, DistrictName, KccAns, QueryText, QueryType, Season, Sector, StateName, day, month, year` |
| Time | `created_on, date, year_month, day_of_week, season_derived` (plus derived `year`, `month` as ints named `year_i`, `month_i`) |
| Cleaned labels and places | `query_type_clean, category_clean, crop_clean, sector_clean, district_clean, district_display (optional), block_clean` |
| Cleaned text | `q_clean, q_core, q_norm, ans_clean, ans_norm, ans_digits_ascii, q_len, ans_len` |
| Language | `ans_script, answer_lang, lang_confidence` |
| Flags | `flag_q_empty, flag_ans_empty, flag_incomplete_call, flag_weather_template, flag_mandi_template, flag_dated_answer, flag_q_too_long, flag_ans_too_long, flag_sector_numeric, flag_district_invalid, flag_date_mismatch, flag_pii_phone_redacted, is_valid_qa, exclude_reason` |
| Duplicates | `qa_key, qa_dup_count, q_key, q_dup_count, is_first_occurrence` |

Column names are fixed so later code can rely on them. If the teammate's AI wants to rename anything, change this table and the tests together.

## 5. Do NOT do these

- Do not edit, overwrite or re-save raw files; do not open them in Excel.
- Do not delete weather-template, mandi-template, incomplete, short or long rows. Flag them.
- Do not translate answers to English or alter Marathi text beyond whitespace, Unicode and phone redaction.
- Do not fill missing `Crop`, `QueryType`, `Category` or `Sector` by guessing, and do not merge or rename labels.
- Do not use an LLM to "fix" or rewrite text, or to label language. Rules and lists only, so the result is reproducible.
- Do not truncate long texts.
- Do not build train/test splits, the golden set or the classifier dataset here.
- Do not call the data.gov.in API (decision in the source of truth).
- Do not commit raw data, cleaned data or any API key to Git.

## 6. Acceptance tests (put in `tests/test_clean.py`)

1. Raw rows read = 370,702; rows after removing the duplicate file = 361,181 (±0 unless the team adds files).
2. `KCCCallID` is unique in the master; `source_file` never equals `mh-2024-2.csv`.
3. Monthly files cover 2023-11 … 2025-07 **without 2024-02**; per-month row counts equal the table in section 1.
4. No tab, newline or double space inside any `*_clean` column; no leading or trailing whitespace.
5. `query_type_clean` has 72 distinct non-null values; `district_clean` has no `0`, `9999` or digits.
6. `season_derived` has no nulls; `sector_clean` has no numeric values.
7. `created_on` has no nulls, min is 2023-11-01, max is 2025-07-29; derived `year_i`, `month_i` match raw `year`, `month`.
8. Flag counts are within about 1% of the expected counts in step 10 (explain any larger gap in the report).
9. No 10-digit mobile-like number remains in `q_clean` or `ans_clean`; helpline numbers listed in step 12 are still present.
10. Re-running the pipeline produces a byte-identical master Parquet (or identical hash of the content).
11. A raw-versus-clean spot check: 20 random rows where `Marathi` text in `ans_clean` equals the raw answer after whitespace normalisation.

## 7. Decisions the team should confirm (small, all reversible)

- **Season boundaries** (step 11). Default Jun–Oct kharif, Nov–Feb rabi, Mar–May summer.
- **District display names** (step 8). Keep dataset spelling as the key; use modern names only for display.
- **Language list** is not decided here. It is decided after the language audit, as the source of truth says.
- **Licence and terms of use** of the KCC resource are still unread (source of truth open item). Stage 1 can proceed, but the licence line in the manifest stays "unverified" until someone reads it.
- **Missing February 2024:** try the portal CSV download once more; otherwise leave it missing and say so in the report.
- After Stage 1, update `kcc_source_of_truth.md` section 9 ("What we have") with the real file list and row counts.

## 8. Hand-off to Stage 2

What Stage 2 (language audit, golden corpus, classifier, answerability model) receives: one master file with `is_valid_qa`, template flags, duplicate keys, `season_derived`, `answer_lang` and `q_core`. Stage 2 builds task-specific views by filtering on those flags (for example the classifier view drops `flag_weather_template` and invalid rows; the retrieval index drops `flag_dated_answer` and keeps expert-style answers). Stage 1 is finished when all tests in section 6 pass and the cleaning report has been read by both teammates.
