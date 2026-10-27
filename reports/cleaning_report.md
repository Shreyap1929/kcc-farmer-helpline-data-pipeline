# KCC Data Cleaning – Stage 1 Cleaning Report

**Run Date:** 2026-10-26  
**Pipeline:** Stage 1: Standardise the Data  
**Scope:** Maharashtra KCC Queries & Answers (data.gov.in)

---

## 1. Executive Summary & Row Counts

- **Total raw rows ingested across 21 CSVs:** 370,702
- **Excluded duplicate file (`mh-2024-2.csv`):** 9,521 rows (byte-identical duplicate of `mh-2024-1.csv`)
- **Missing Month:** February 2024 (`2024-02`) is absent from the official source datasets and flagged as missing.
- **Master Clean Dataset Rows:** **361,181** (100% unique `KCCCallID`s).
- **Core Principle Applied:** **Add, don't destroy**. All original raw columns are preserved. Cleaned values and quality flags are stored in new typed columns. No rows deleted after file deduplication.

---

## 2. Ingestion & File Manifest

| File Name | Row Count | MD5 | Status |
|:---|---:|:---|:---|
| `mh-2023-11.csv` | 13,178 | `c7615a90d65755019f2723773f492cf7` | `used` |
| `mh-2023-12.csv` | 13,633 | `169029fff448540f8878f7ed92f0f5aa` | `used` |
| `mh-2024-1.csv` | 9,521 | `9b2d54ddedee588ffa3df4b34c6786da` | `used` |
| `mh-2024-10.csv` | 26,379 | `efaa212abb974c0678a896431e0e11d1` | `used` |
| `mh-2024-11.csv` | 12,725 | `a687734e1c28b531247378d9c6e1edbf` | `used` |
| `mh-2024-12.csv` | 17,093 | `ee06a1c373f0bae28bb812ceb685ec06` | `used` |
| `mh-2024-2.csv` | 9,521 | `9b2d54ddedee588ffa3df4b34c6786da` | `duplicate_of:mh-2024-1.csv` |
| `mh-2024-3.csv` | 9,161 | `719640cef8c5097a0ac17ab231d89151` | `used` |
| `mh-2024-4.csv` | 10,219 | `ceae7b96e0736fde235f3f29590d4402` | `used` |
| `mh-2024-5.csv` | 10,447 | `418762534b99927b21d3d280165931be` | `used` |
| `mh-2024-6.csv` | 27,694 | `b3c25b8a7962266a651e14c239fdab47` | `used` |
| `mh-2024-7.csv` | 27,864 | `8490308a95b3d391ce22ce4f18886474` | `used` |
| `mh-2024-8.csv` | 32,163 | `497072bbb9385eceae515a77f1a81d91` | `used` |
| `mh-2024-9.csv` | 24,210 | `f4036a61b00fc2bcbbd721f3f16d909f` | `used` |
| `mh-2025-1.csv` | 12,065 | `ebe8014cd1bf1f1642ac6810d3aad840` | `used` |
| `mh-2025-2.csv` | 14,685 | `32c6416f561817e5c0b414060b9f44a2` | `used` |
| `mh-2025-3.csv` | 15,146 | `96f34c4aa80f55f3eb64cae9e69d8ebf` | `used` |
| `mh-2025-4.csv` | 12,370 | `3f821508430c295a68a1e822760655b1` | `used` |
| `mh-2025-5.csv` | 14,804 | `1d5308c3a00e4ab191f6219d384d6fa8` | `used` |
| `mh-2025-6.csv` | 30,413 | `f909e558dee575e75fb48349fd7cde80` | `used` |
| `mh-2025-7.csv` | 27,411 | `d26469448850964f719e107cb9197d62` | `partial_month` |
| `mh-2024-02 (missing)` | 0 | `` | `missing` |

---

## 3. Monthly Breakdown & Weather Template Share

| Year-Month | Rows | Weather Template Count (%) |
|:---|---:|:---|
| 2023-11 | 13,178 | 6,595 (50.0%) |
| 2023-12 | 13,633 | 5,734 (42.1%) |
| 2024-01 | 9,521 | 3,484 (36.6%) |
| 2024-03 | 9,161 | 4,661 (50.9%) |
| 2024-04 | 10,219 | 6,396 (62.6%) |
| 2024-05 | 10,447 | 6,523 (62.4%) |
| 2024-06 | 27,694 | 19,804 (71.5%) |
| 2024-07 | 27,864 | 11,164 (40.1%) |
| 2024-08 | 32,163 | 8,648 (26.9%) |
| 2024-09 | 24,210 | 9,490 (39.2%) |
| 2024-10 | 26,379 | 11,324 (42.9%) |
| 2024-11 | 12,725 | 2,675 (21.0%) |
| 2024-12 | 17,093 | 5,270 (30.8%) |
| 2025-01 | 12,065 | 1,714 (14.2%) |
| 2025-02 | 14,685 | 1,119 (7.6%) |
| 2025-03 | 15,146 | 3,473 (22.9%) |
| 2025-04 | 12,370 | 4,410 (35.7%) |
| 2025-05 | 14,804 | 7,824 (52.9%) |
| 2025-06 | 30,413 | 18,580 (61.1%) |
| 2025-07 | 27,411 | 11,810 (43.1%) |

---

## 4. Quality & Processing Flags

| Flag Name | Count | Share (%) |
|:---|---:|:---|
| `flag_q_empty` | 24 | 0.01% |
| `flag_ans_empty` | 88 | 0.02% |
| `flag_incomplete_call` | 470 | 0.13% |
| `flag_weather_template` | 150,698 | 41.72% |
| `flag_mandi_template` | 5,813 | 1.61% |
| `flag_dated_answer` | 156,511 | 43.33% |
| `flag_q_too_long` | 257 | 0.07% |
| `flag_ans_too_long` | 145 | 0.04% |
| `flag_sector_numeric` | 756 | 0.21% |
| `flag_district_invalid` | 5 | 0.00% |
| `flag_date_mismatch` | 0 | 0.00% |
| `flag_pii_phone_redacted` | 2,364 | 0.65% |
| `is_valid_qa` | 360,619 | 99.84% |

---

## 5. Script & Language Classification (Step 11)

### Answer Script Distribution (`ans_script`)
| Script | Count | Share (%) |
|:---|---:|:---|
| `devanagari` | 351,314 | 97.27% |
| `mixed` | 7,883 | 2.18% |
| `latin` | 1,819 | 0.50% |
| `none` | 165 | 0.05% |

### Answer Language Distribution (`answer_lang`)
| Language | Count | Share (%) |
|:---|---:|:---|
| `unclear` | 243,584 | 67.44% |
| `marathi` | 115,060 | 31.86% |
| `english` | 1,819 | 0.50% |
| `hindi` | 718 | 0.20% |

*Note:* `answer_lang` is a rule-based function word heuristic. Weather and mandi templates have short answers lacking multiple function words and are classified as `unclear`. Hand-checked 50-row samples per language are provided in `reports/samples/` for calibration.

---

## 6. PII & Helpline Redaction (Step 12)

- **Total rows with redacted phone numbers:** 2,364
- **Regex pattern used:** `(?<!\d)(?:\+?91[\s-]?)?[6-9](?:[\s-]?\d){9}(?!\d)` (with Devanagari digits normalized to ASCII prior to detection).
- **Toll-free / Scheme numbers preserved:** Toll-free numbers starting with `1800` or `1947`, and shortcodes such as `14447` and `155261` are strictly kept unredacted.

### Top 20 Redacted Mobile Numbers
| Number | Frequency |
|:---|---:|
| `7065514447` | 294 |
| `9822446655` | 213 |
| `8446117500` | 161 |
| `8446221750` | 104 |
| `8446331750` | 104 |
| `9834225799` | 68 |
| `9921597924` | 64 |
| `7065791115` | 63 |
| `7738299899` | 50 |
| `9420951840` | 41 |
| `8275013396` | 40 |
| `9421568674` | 38 |
| `7588612632` | 38 |
| `7242258266` | 34 |
| `8698579689` | 30 |
| `7096093805` | 30 |
| `9503095030` | 28 |
| `9370975818` | 26 |
| `9595044044` | 25 |
| `8275311854` | 23 |

### Top 20 Preserved Helpline Numbers
| Number | Frequency |
|:---|---:|
| `155261` | 9,795 |
| `14447` | 3,829 |
| `18002334000` | 991 |
| `1800115526` | 973 |
| `18001155266` | 553 |
| `18001208040` | 178 |
| `18002330418` | 151 |
| `18002669725` | 94 |
| `18002660700` | 88 |
| `18002333435` | 74 |
| `18001023435` | 68 |
| `1800118485` | 66 |
| `1800116515` | 64 |
| `18002005142` | 35 |
| `18001801551` | 26 |
| `18002091111` | 22 |
| `18002123435` | 17 |
| `1800155261` | 14 |
| `18001803333` | 8 |
| `18002001310` | 7 |

---

## 7. Categorical Label Summary

- **`query_type_clean`:** 72 distinct non-null values (1,917 null/missing).
- **`category_clean`:** 34 distinct non-null values (1,591 null/missing).
- **`crop_clean`:** 283 distinct non-null values (2,306 null/missing).
- **`sector_clean`:** 4 distinct non-null values (756 numeric values flagged and set to null).
- **`district_clean`:** 36 valid districts (5 invalid rows with `'0'` or `'9999'` flagged).

### Top 10 Districts
| District | Rows |
|:---|---:|
| `NANDED` | 27,508 |
| `YEVATMAL` | 26,962 |
| `BULDANA` | 24,337 |
| `AHMADNAGAR` | 20,253 |
| `WASHIM` | 19,658 |
| `SOLAPUR` | 19,491 |
| `AURANGABAD` | 17,673 |
| `BEED` | 15,949 |
| `NASIK` | 15,159 |
| `JALNA` | 14,839 |

---

## 8. Duplicates & Template Leakage (Step 13)

- **Unique QA Keys (`qa_key`):** 299,695
- **Rows repeating an identical (Q, A) pair:** 75,033 rows (61,486 subsequent occurrences).
- **Unique Query Keys (`q_key`):** 85,161
- **Rows repeating a question (`q_dup_count > 1`):** 290,650 rows.
- Chronological splitting and hard evaluation modes should use `is_first_occurrence` and duplicate keys to avoid test set contamination.

---

## 9. Output Deliverables

1. Master Parquet: `data/clean/kcc_mh_clean.parquet` (361,181 rows, 61 columns)
2. Master CSV: `data/clean/kcc_mh_clean.csv` (361,181 rows, UTF-8 encoded)
3. Monthly CSVs: `data/clean/monthly/kcc_mh_YYYY_MM.csv` (20 monthly files)
4. Manifest: `reports/file_manifest.csv`
5. Value counts: `reports/value_counts/*.csv`
6. Audit samples: `reports/samples/*.csv`
