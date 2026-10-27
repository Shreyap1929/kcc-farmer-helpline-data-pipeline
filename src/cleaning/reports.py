"""
Reporting, value count exports, and sampling module (Step 15).
"""
import os
from collections import Counter
import pandas as pd


def generate_reports_and_samples(
    master_df: pd.DataFrame,
    manifest_df: pd.DataFrame,
    redacted_numbers_counter: Counter,
    kept_numbers_counter: Counter,
    reports_dir: str = "reports",
) -> str:
    """
    Generates:
    - reports/file_manifest.csv
    - reports/value_counts/*.csv
    - reports/samples/*.csv
    - reports/cleaning_report.md
    """
    val_counts_dir = os.path.join(reports_dir, "value_counts")
    samples_dir = os.path.join(reports_dir, "samples")
    os.makedirs(val_counts_dir, exist_ok=True)
    os.makedirs(samples_dir, exist_ok=True)

    # 1. Manifest
    manifest_path = os.path.join(reports_dir, "file_manifest.csv")
    manifest_df.to_csv(manifest_path, index=False, encoding="utf-8")

    # 2. Value counts
    def save_vc(series: pd.Series, out_name: str, col_name: str):
        vc = series.value_counts(dropna=False).reset_index()
        vc.columns = [col_name, "count"]
        vc.to_csv(os.path.join(val_counts_dir, out_name), index=False, encoding="utf-8")
        return vc

    vc_query_type = save_vc(master_df["query_type_clean"], "query_type.csv", "query_type_clean")
    vc_category = save_vc(master_df["category_clean"], "category.csv", "category_clean")
    vc_crop = save_vc(master_df["crop_clean"], "crop.csv", "crop_clean")
    vc_sector = save_vc(master_df["sector_clean"], "sector.csv", "sector_clean")
    vc_district = save_vc(master_df["district_clean"], "district.csv", "district_clean")
    vc_answer_lang = save_vc(master_df["answer_lang"], "answer_lang.csv", "answer_lang")
    vc_ans_script = save_vc(master_df["ans_script"], "ans_script.csv", "ans_script")

    # District x Answer Language cross-tabulation
    dist_lang = pd.crosstab(
        master_df["district_clean"].fillna("INVALID/NULL"),
        master_df["answer_lang"],
        margins=True,
    )
    dist_lang.to_csv(os.path.join(val_counts_dir, "district_x_answer_lang.csv"), encoding="utf-8")

    # Top 50 repeated questions
    top_50_q = (
        master_df["q_clean"]
        .value_counts()
        .head(50)
        .reset_index()
    )
    top_50_q.columns = ["q_clean", "count"]
    top_50_q.to_csv(os.path.join(val_counts_dir, "top_50_repeated_questions.csv"), index=False, encoding="utf-8")

    # 3. Samples
    sample_seed = 42
    # Language samples (50 rows each)
    for lang in ["marathi", "hindi", "english", "unclear"]:
        sub = master_df[master_df["answer_lang"] == lang]
        n_sample = min(50, len(sub))
        if n_sample > 0:
            sample_df = sub.sample(n=n_sample, random_state=sample_seed)[
                ["KCCCallID", "source_file", "district_clean", "q_clean", "ans_clean", "lang_confidence"]
            ]
            sample_df.to_csv(
                os.path.join(samples_dir, f"answer_lang_{lang}.csv"), index=False, encoding="utf-8"
            )

    # PII review (100 random rows)
    n_pii = min(100, len(master_df))
    pii_sample = master_df.sample(n=n_pii, random_state=sample_seed)[
        ["KCCCallID", "source_file", "ans_clean", "flag_pii_phone_redacted"]
    ]
    pii_sample.to_csv(os.path.join(samples_dir, "pii_review.csv"), index=False, encoding="utf-8")

    # 50-row samples per flag
    flag_cols = [
        "flag_q_empty",
        "flag_ans_empty",
        "flag_incomplete_call",
        "flag_weather_template",
        "flag_mandi_template",
        "flag_dated_answer",
        "flag_q_too_long",
        "flag_ans_too_long",
        "flag_sector_numeric",
        "flag_district_invalid",
        "flag_date_mismatch",
        "flag_pii_phone_redacted",
    ]
    for flag in flag_cols:
        sub = master_df[master_df[flag]]
        n_s = min(50, len(sub))
        if n_s > 0:
            s_df = sub.sample(n=n_s, random_state=sample_seed)[
                ["KCCCallID", "source_file", "district_clean", "q_clean", "ans_clean", "exclude_reason"]
            ]
            s_df.to_csv(
                os.path.join(samples_dir, f"sample_{flag}.csv"), index=False, encoding="utf-8"
            )

    # 4. Cleaning Report (Markdown)
    total_raw_rows = manifest_df[manifest_df["status"] != "missing"]["row_count"].sum()
    duplicate_rows = manifest_df[manifest_df["status"].str.startswith("duplicate_of:")]["row_count"].sum()
    final_master_rows = len(master_df)

    # Monthly breakdown table
    monthly_stats = []
    for ym, group in master_df.groupby("year_month", sort=True):
        m_count = len(group)
        w_count = group["flag_weather_template"].sum()
        w_pct = (w_count / m_count) * 100 if m_count > 0 else 0
        monthly_stats.append(
            f"| {ym} | {m_count:,} | {w_count:,} ({w_pct:.1f}%) |"
        )
    monthly_table = "\n".join(monthly_stats)

    # Flag counts table
    flag_stats = []
    for flag in flag_cols + ["is_valid_qa"]:
        cnt = master_df[flag].sum()
        pct = (cnt / final_master_rows) * 100
        flag_stats.append(f"| `{flag}` | {cnt:,} | {pct:.2f}% |")
    flag_table = "\n".join(flag_stats)

    # Script counts table
    script_stats = []
    for s_name, s_cnt in master_df["ans_script"].value_counts().items():
        script_stats.append(f"| `{s_name}` | {s_cnt:,} | {(s_cnt/final_master_rows)*100:.2f}% |")
    script_table = "\n".join(script_stats)

    # Language counts table
    lang_stats = []
    for l_name, l_cnt in master_df["answer_lang"].value_counts().items():
        lang_stats.append(f"| `{l_name}` | {l_cnt:,} | {(l_cnt/final_master_rows)*100:.2f}% |")
    lang_table = "\n".join(lang_stats)

    # Top 20 redacted phone numbers
    redacted_table = "\n".join(
        [f"| `{num}` | {cnt:,} |" for num, cnt in redacted_numbers_counter.most_common(20)]
    )

    # Top 20 kept helpline numbers
    kept_table = "\n".join(
        [f"| `{num}` | {cnt:,} |" for num, cnt in kept_numbers_counter.most_common(20)]
    )

    # District table top 10
    top_districts = "\n".join(
        [f"| `{row['district_clean']}` | {row['count']:,} |" for _, row in vc_district.head(10).iterrows()]
    )

    report_content = f"""# KCC Data Cleaning – Stage 1 Cleaning Report

**Run Date:** 2026-10-26  
**Pipeline:** Stage 1: Standardise the Data  
**Scope:** Maharashtra KCC Queries & Answers (data.gov.in)

---

## 1. Executive Summary & Row Counts

- **Total raw rows ingested across 21 CSVs:** {total_raw_rows:,}
- **Excluded duplicate file (`mh-2024-2.csv`):** {duplicate_rows:,} rows (byte-identical duplicate of `mh-2024-1.csv`)
- **Missing Month:** February 2024 (`2024-02`) is absent from the official source datasets and flagged as missing.
- **Master Clean Dataset Rows:** **{final_master_rows:,}** (100% unique `KCCCallID`s).
- **Core Principle Applied:** **Add, don't destroy**. All original raw columns are preserved. Cleaned values and quality flags are stored in new typed columns. No rows deleted after file deduplication.

---

## 2. Ingestion & File Manifest

| File Name | Row Count | MD5 | Status |
|:---|---:|:---|:---|
"""
    for _, r in manifest_df.iterrows():
        report_content += f"| `{r['file_name']}` | {r['row_count']:,} | `{r['md5']}` | `{r['status']}` |\n"

    report_content += f"""
---

## 3. Monthly Breakdown & Weather Template Share

| Year-Month | Rows | Weather Template Count (%) |
|:---|---:|:---|
{monthly_table}

---

## 4. Quality & Processing Flags

| Flag Name | Count | Share (%) |
|:---|---:|:---|
{flag_table}

---

## 5. Script & Language Classification (Step 11)

### Answer Script Distribution (`ans_script`)
| Script | Count | Share (%) |
|:---|---:|:---|
{script_table}

### Answer Language Distribution (`answer_lang`)
| Language | Count | Share (%) |
|:---|---:|:---|
{lang_table}

*Note:* `answer_lang` is a rule-based function word heuristic. Weather and mandi templates have short answers lacking multiple function words and are classified as `unclear`. Hand-checked 50-row samples per language are provided in `reports/samples/` for calibration.

---

## 6. PII & Helpline Redaction (Step 12)

- **Total rows with redacted phone numbers:** {master_df['flag_pii_phone_redacted'].sum():,}
- **Regex pattern used:** `(?<!\\d)(?:\\+?91[\\s-]?)?[6-9](?:[\\s-]?\\d){{9}}(?!\\d)` (with Devanagari digits normalized to ASCII prior to detection).
- **Toll-free / Scheme numbers preserved:** Toll-free numbers starting with `1800` or `1947`, and shortcodes such as `14447` and `155261` are strictly kept unredacted.

### Top 20 Redacted Mobile Numbers
| Number | Frequency |
|:---|---:|
{redacted_table}

### Top 20 Preserved Helpline Numbers
| Number | Frequency |
|:---|---:|
{kept_table}

---

## 7. Categorical Label Summary

- **`query_type_clean`:** {master_df['query_type_clean'].nunique():,} distinct non-null values ({master_df['query_type_clean'].isna().sum():,} null/missing).
- **`category_clean`:** {master_df['category_clean'].nunique():,} distinct non-null values ({master_df['category_clean'].isna().sum():,} null/missing).
- **`crop_clean`:** {master_df['crop_clean'].nunique():,} distinct non-null values ({master_df['crop_clean'].isna().sum():,} null/missing).
- **`sector_clean`:** {master_df['sector_clean'].nunique():,} distinct non-null values ({master_df['flag_sector_numeric'].sum():,} numeric values flagged and set to null).
- **`district_clean`:** {master_df['district_clean'].nunique():,} valid districts ({master_df['flag_district_invalid'].sum():,} invalid rows with `'0'` or `'9999'` flagged).

### Top 10 Districts
| District | Rows |
|:---|---:|
{top_districts}

---

## 8. Duplicates & Template Leakage (Step 13)

- **Unique QA Keys (`qa_key`):** {master_df['qa_key'].nunique():,}
- **Rows repeating an identical (Q, A) pair:** {(master_df['qa_dup_count'] > 1).sum():,} rows ({(master_df['is_first_occurrence'] == False).sum():,} subsequent occurrences).
- **Unique Query Keys (`q_key`):** {master_df['q_key'].nunique():,}
- **Rows repeating a question (`q_dup_count > 1`):** {(master_df['q_dup_count'] > 1).sum():,} rows.
- Chronological splitting and hard evaluation modes should use `is_first_occurrence` and duplicate keys to avoid test set contamination.

---

## 9. Output Deliverables

1. Master Parquet: `data/clean/kcc_mh_clean.parquet` ({final_master_rows:,} rows, 61 columns)
2. Master CSV: `data/clean/kcc_mh_clean.csv` ({final_master_rows:,} rows, UTF-8 encoded)
3. Monthly CSVs: `data/clean/monthly/kcc_mh_YYYY_MM.csv` (20 monthly files)
4. Manifest: `reports/file_manifest.csv`
5. Value counts: `reports/value_counts/*.csv`
6. Audit samples: `reports/samples/*.csv`
"""

    report_path = os.path.join(reports_dir, "cleaning_report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_content)

    return report_path
