"""
Quality, template, and exclusion flag computation module (Step 10).
"""
import pandas as pd


def process_flags(df: pd.DataFrame) -> pd.DataFrame:
    """
    Step 10:
    Compute all boolean flag columns and generate the composite exclude_reason string.
    Note: no rows are deleted. Everything is flagged.
    """
    q_len = df["q_len"]
    ans_len = df["ans_len"]
    q_norm = df["q_norm"]

    df["flag_q_empty"] = q_len < 3
    df["flag_ans_empty"] = ans_len < 10
    df["flag_incomplete_call"] = q_norm.str.contains("incomplete call", na=False, regex=False)
    df["flag_weather_template"] = q_norm == "farmer asked query on weather"
    df["flag_mandi_template"] = q_norm == "farmer asked query on mandi details"
    df["flag_dated_answer"] = df["flag_weather_template"] | df["flag_mandi_template"]

    # In raw data, long text includes cases with large trailing whitespace/padding (seen in spec)
    raw_q_len = df["QueryText"].str.len() if "QueryText" in df.columns else q_len
    raw_ans_len = df["KccAns"].str.len() if "KccAns" in df.columns else ans_len
    df["flag_q_too_long"] = (q_len > 1000) | (raw_q_len > 1000)
    df["flag_ans_too_long"] = (ans_len > 3000) | (raw_ans_len > 3000)

    # Ensure boolean flags from prior steps are boolean dtype
    for col in [
        "flag_sector_numeric",
        "flag_district_invalid",
        "flag_date_mismatch",
        "flag_pii_phone_redacted",
    ]:
        if col in df.columns:
            df[col] = df[col].astype(bool)
        else:
            df[col] = False

    # is_valid_qa: not flag_q_empty, not flag_ans_empty, not flag_incomplete_call
    df["is_valid_qa"] = (
        (~df["flag_q_empty"])
        & (~df["flag_ans_empty"])
        & (~df["flag_incomplete_call"])
    )

    # Fast composite exclude_reason string construction
    tracked_flags = [
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

    n_rows = len(df)
    reasons_list: list[list[str]] = [[] for _ in range(n_rows)]
    for flag_col in tracked_flags:
        mask = df[flag_col].to_numpy()
        for idx in mask.nonzero()[0]:
            reasons_list[idx].append(flag_col)

    df["exclude_reason"] = [",".join(r) for r in reasons_list]

    return df
