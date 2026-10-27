"""
Duplicate detection and key calculation module (Step 13).
"""
import hashlib
import pandas as pd


def compute_md5(val: str) -> str:
    return hashlib.md5(val.encode("utf-8")).hexdigest()


def process_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    """
    Step 13:
    - qa_key: MD5(q_norm + "||" + ans_norm)
    - qa_dup_count: total occurrences of qa_key
    - q_key: MD5(q_norm)
    - q_dup_count: total occurrences of q_key
    - is_first_occurrence: True for earliest created_on within each qa_key group
    """
    qa_strings = df["q_norm"].fillna("") + "||" + df["ans_norm"].fillna("")
    df["qa_key"] = qa_strings.apply(compute_md5)
    df["q_key"] = df["q_norm"].fillna("").apply(compute_md5)

    # Count occurrences
    qa_counts = df["qa_key"].value_counts()
    df["qa_dup_count"] = df["qa_key"].map(qa_counts).astype(int)

    q_counts = df["q_key"].value_counts()
    df["q_dup_count"] = df["q_key"].map(q_counts).astype(int)

    # Determine earliest occurrence per qa_key deterministically
    # Sort temporary index by created_on, source_file, source_row
    # We maintain original df order while setting is_first_occurrence
    temp = df[["qa_key", "created_on", "source_file", "source_row"]].copy()
    temp["orig_idx"] = temp.index
    temp = temp.sort_values(by=["created_on", "source_file", "source_row", "orig_idx"])

    # First occurrence per qa_key in this sorted view
    first_mask = ~temp.duplicated(subset=["qa_key"], keep="first")
    first_indices = set(temp.loc[first_mask, "orig_idx"])

    df["is_first_occurrence"] = df.index.isin(first_indices)

    return df
