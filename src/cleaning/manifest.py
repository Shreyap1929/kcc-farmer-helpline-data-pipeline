"""
Raw data ingestion and file manifest generation (Steps 1 & 2).
"""
import glob
import hashlib
import os
import zipfile
import pandas as pd


def compute_file_md5(file_path: str) -> str:
    hasher = hashlib.md5()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def extract_zips_if_needed(zip_paths: list[str], raw_dir: str) -> None:
    """
    Extracts CSV files from ZIP archives into raw_dir if raw_dir does not already contain CSVs.
    Flattens any internal subdirectories so raw_dir contains all CSVs directly.
    """
    os.makedirs(raw_dir, exist_ok=True)
    existing_csvs = glob.glob(os.path.join(raw_dir, "*.csv"))
    if len(existing_csvs) >= 21:
        return

    for zpath in zip_paths:
        if not os.path.exists(zpath):
            continue
        with zipfile.ZipFile(zpath, "r") as z:
            for member in z.infolist():
                if member.filename.endswith(".csv"):
                    fname = os.path.basename(member.filename)
                    target = os.path.join(raw_dir, fname)
                    with z.open(member) as src, open(target, "wb") as dst:
                        dst.write(src.read())


def generate_manifest(raw_dir: str) -> tuple[pd.DataFrame, list[str]]:
    """
    Step 1 & 2:
    Inspect raw CSV files, detect duplicate files by MD5, generate manifest dataframe,
    and return list of used file paths.
    """
    csv_files = sorted(glob.glob(os.path.join(raw_dir, "*.csv")))
    records = []
    seen_md5: dict[str, str] = {}
    used_files: list[str] = []

    for fpath in csv_files:
        fname = os.path.basename(fpath)
        md5_val = compute_file_md5(fpath)

        df_sample = pd.read_csv(fpath, dtype=str, keep_default_na=False, encoding="utf-8")
        row_cnt = len(df_sample)
        min_created = df_sample["CreatedOn"].min() if row_cnt > 0 else ""
        max_created = df_sample["CreatedOn"].max() if row_cnt > 0 else ""
        cols_str = ";".join(df_sample.columns)

        if md5_val in seen_md5:
            status = f"duplicate_of:{seen_md5[md5_val]}"
        elif fname == "mh-2025-7.csv":
            status = "partial_month"
            seen_md5[md5_val] = fname
            used_files.append(fpath)
        else:
            status = "used"
            seen_md5[md5_val] = fname
            used_files.append(fpath)

        records.append(
            {
                "file_name": fname,
                "md5": md5_val,
                "row_count": row_cnt,
                "min_created_on": min_created,
                "max_created_on": max_created,
                "columns": cols_str,
                "status": status,
            }
        )

    # Record 2024-02 as explicitly missing
    records.append(
        {
            "file_name": "mh-2024-02 (missing)",
            "md5": "",
            "row_count": 0,
            "min_created_on": "",
            "max_created_on": "",
            "columns": "",
            "status": "missing",
        }
    )

    manifest_df = pd.DataFrame(records)
    return manifest_df, used_files
