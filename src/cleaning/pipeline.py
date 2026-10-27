"""
End-to-end cleaning pipeline orchestrator (Steps 1 to 15).
"""
import os
import re
from collections import Counter
import pandas as pd

from src.cleaning.constants import (
    DEV_TO_ASCII_DIGITS,
    HELPLINE_PREFIXES,
    MASTER_COLUMNS,
)
from src.cleaning.dates import process_dates
from src.cleaning.duplicates import process_duplicates
from src.cleaning.flags import process_flags
from src.cleaning.labels import process_labels
from src.cleaning.language import classify_answer_lang, detect_script
from src.cleaning.manifest import extract_zips_if_needed, generate_manifest
from src.cleaning.pii import redact_phone_numbers
from src.cleaning.reports import generate_reports_and_samples
from src.cleaning.text_utils import (
    clean_unicode_and_ws,
    extract_q_core,
    make_normalized_text,
    to_ascii_digits,
)

HELPLINE_PATTERN = re.compile(r"(?<!\d)(?:1800\d{6,7}|1947|14447|155261)(?!\d)")


def run_pipeline(
    raw_dir: str = "data/raw",
    out_dir: str = "data/clean",
    reports_dir: str = "reports",
    config_dir: str = "config",
    zip_paths: list[str] | None = None,
) -> pd.DataFrame:
    """
    Executes all cleaning steps in strict order (Steps 1 to 15):
    1. Ingest & manifest
    2. Exclude duplicate file
    3. Concatenate
    4. Dates & calendar
    5. Unicode & whitespace
    6. Missing value tokens
    7. Label standardisation
    8. District & block
    9. Text columns
    10. Quality & template flags
    11. Derived columns (season, script, language)
    12. Phone & PII redaction
    13. Duplicate keys
    14. Output files
    15. Cleaning report & audit samples
    """
    print("=== Step 1 & 2: Ingest and Manifest ===")
    if zip_paths:
        extract_zips_if_needed(zip_paths, raw_dir)

    manifest_df, used_files = generate_manifest(raw_dir)
    print(f"Discovered {len(used_files)} valid files to process.")

    print("=== Step 3: Combine Raw Data ===")
    dfs = []
    for fpath in used_files:
        fname = os.path.basename(fpath)
        df_sub = pd.read_csv(fpath, dtype=str, keep_default_na=False, encoding="utf-8")
        df_sub["source_file"] = fname
        df_sub["source_row"] = range(len(df_sub))
        dfs.append(df_sub)

    master_df = pd.concat(dfs, ignore_index=True)
    print(f"Combined master dataset shape: {master_df.shape}")

    # Assert no duplicate IDs
    id_counts = master_df["KCCCallID"].value_counts()
    dup_ids = id_counts[id_counts > 1]
    if len(dup_ids) > 0:
        print(f"WARNING: {len(dup_ids)} duplicate KCCCallIDs found! Writing conflicts...")
        os.makedirs(reports_dir, exist_ok=True)
        conflicts = master_df[master_df["KCCCallID"].isin(dup_ids.index)]
        conflicts.to_csv(os.path.join(reports_dir, "id_conflicts.csv"), index=False, encoding="utf-8")
        # Drop exact full-row repeats
        master_df = master_df.drop_duplicates(keep="first")

    print("=== Step 4 & 11: Dates and Season ===")
    season_map_path = os.path.join(config_dir, "season_map.yaml")
    master_df = process_dates(master_df, season_map_path)

    print("=== Step 6, 7 & 8: Labels and Places ===")
    district_map_path = os.path.join(config_dir, "district_display.csv")
    master_df = process_labels(master_df, district_map_path)

    print("=== Steps 5, 9, 11 & 12: Text Normalization, Language & PII Redaction ===")
    q_clean_list = []
    q_core_list = []
    q_norm_list = []
    ans_clean_list = []
    ans_norm_list = []
    ans_digits_ascii_list = []
    q_len_list = []
    ans_len_list = []
    ans_script_list = []
    answer_lang_list = []
    lang_conf_list = []
    flag_pii_list = []

    redacted_numbers_counter = Counter()
    kept_numbers_counter = Counter()

    for q_raw, a_raw in zip(master_df["QueryText"], master_df["KccAns"]):
        # Step 5: Unicode and Whitespace cleaning
        cq = clean_unicode_and_ws(q_raw)
        ca = clean_unicode_and_ws(a_raw)

        # Step 12: Phone number redaction
        qc, q_redacted, q_nums = redact_phone_numbers(cq)
        ac, a_redacted, a_nums = redact_phone_numbers(ca)

        for num in q_nums + a_nums:
            redacted_numbers_counter[num] += 1
        flag_pii_list.append(q_redacted or a_redacted)

        # Scan for kept helpline numbers
        ca_ascii = ca.translate(DEV_TO_ASCII_DIGITS)
        for m in HELPLINE_PATTERN.finditer(ca_ascii):
            kept_numbers_counter[re.sub(r"[\s-]", "", m.group(0))] += 1

        # Step 9: Derived text representations
        q_core = extract_q_core(qc)
        q_norm = make_normalized_text(qc)
        ans_norm = make_normalized_text(ac)
        ans_digits_ascii = to_ascii_digits(ac)
        q_l = len(qc)
        ans_l = len(ac)

        # Step 11: Script and language
        script = detect_script(ac)
        lang, conf = classify_answer_lang(ac, script)

        q_clean_list.append(qc)
        q_core_list.append(q_core)
        q_norm_list.append(q_norm)
        ans_clean_list.append(ac)
        ans_norm_list.append(ans_norm)
        ans_digits_ascii_list.append(ans_digits_ascii)
        q_len_list.append(q_l)
        ans_len_list.append(ans_l)
        ans_script_list.append(script)
        answer_lang_list.append(lang)
        lang_conf_list.append(conf)

    master_df["q_clean"] = q_clean_list
    master_df["q_core"] = q_core_list
    master_df["q_norm"] = q_norm_list
    master_df["ans_clean"] = ans_clean_list
    master_df["ans_norm"] = ans_norm_list
    master_df["ans_digits_ascii"] = ans_digits_ascii_list
    master_df["q_len"] = q_len_list
    master_df["ans_len"] = ans_len_list
    master_df["ans_script"] = ans_script_list
    master_df["answer_lang"] = answer_lang_list
    master_df["lang_confidence"] = lang_conf_list
    master_df["flag_pii_phone_redacted"] = flag_pii_list

    print("=== Step 10: Flags ===")
    master_df = process_flags(master_df)

    print("=== Step 13: Duplicate Keys ===")
    master_df = process_duplicates(master_df)

    print("=== Step 14: Writing Output Files ===")
    # Reorder columns to match Master Schema exactly
    master_df = master_df[MASTER_COLUMNS]

    os.makedirs(out_dir, exist_ok=True)
    monthly_dir = os.path.join(out_dir, "monthly")
    os.makedirs(monthly_dir, exist_ok=True)

    parquet_path = os.path.join(out_dir, "kcc_mh_clean.parquet")
    csv_path = os.path.join(out_dir, "kcc_mh_clean.csv")

    print(f"Writing Parquet master to {parquet_path}...")
    master_df.to_parquet(parquet_path, index=False)

    print(f"Writing CSV master to {csv_path}...")
    master_df.to_csv(csv_path, index=False, encoding="utf-8")

    print("Writing monthly CSV files...")
    for ym, group_df in master_df.groupby("year_month", sort=True):
        ym_name = ym.replace("-", "_")
        m_path = os.path.join(monthly_dir, f"kcc_mh_{ym_name}.csv")
        group_df.to_csv(m_path, index=False, encoding="utf-8")

    print("=== Step 15: Generating Reports and Audit Samples ===")
    report_file = generate_reports_and_samples(
        master_df=master_df,
        manifest_df=manifest_df,
        redacted_numbers_counter=redacted_numbers_counter,
        kept_numbers_counter=kept_numbers_counter,
        reports_dir=reports_dir,
    )
    print(f"Cleaning report generated at: {report_file}")
    print("Pipeline completed successfully!")
    return master_df
