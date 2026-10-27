"""
Date parsing and calendar / season derivation module (Steps 4 & 11).
"""
import pandas as pd
import yaml

DEFAULT_SEASON_MAP = {
    1: "rabi",
    2: "rabi",
    3: "summer",
    4: "summer",
    5: "summer",
    6: "kharif",
    7: "kharif",
    8: "kharif",
    9: "kharif",
    10: "kharif",
    11: "rabi",
    12: "rabi",
}


def load_season_map(config_path: str | None = None) -> dict[int, str]:
    if not config_path:
        return DEFAULT_SEASON_MAP
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            if data and "months" in data:
                return {int(k): str(v) for k, v in data["months"].items()}
    except Exception:
        pass
    return DEFAULT_SEASON_MAP


def process_dates(df: pd.DataFrame, season_map_path: str | None = None) -> pd.DataFrame:
    """
    Step 4 & 11:
    - Parse CreatedOn with ISO8601 tolerant parser.
    - Derive date, year_month, day_of_week, year_i, month_i.
    - Check for date mismatch with raw day, month, year.
    - Derive season_derived from month_i.
    """
    season_map = load_season_map(season_map_path)

    created_on = pd.to_datetime(df["CreatedOn"], format="ISO8601")
    df["created_on"] = created_on
    df["date"] = created_on.dt.strftime("%Y-%m-%d")
    df["year_month"] = created_on.dt.strftime("%Y-%m")
    df["day_of_week"] = created_on.dt.day_name()
    df["year_i"] = created_on.dt.year.astype(int)
    df["month_i"] = created_on.dt.month.astype(int)

    # Compare derived day, month, year with raw
    raw_y = df["year"].astype(str).str.strip()
    raw_m = df["month"].astype(str).str.strip()
    raw_d = df["day"].astype(str).str.strip()

    mismatch = (
        (df["year_i"].astype(str) != raw_y)
        | (df["month_i"].astype(str) != raw_m)
        | (created_on.dt.day.astype(str) != raw_d)
    )
    df["flag_date_mismatch"] = mismatch

    # Derive season
    df["season_derived"] = df["month_i"].map(season_map).fillna("unknown")

    return df
