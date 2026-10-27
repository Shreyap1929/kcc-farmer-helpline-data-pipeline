"""
Label standardisation and geographic entity cleaning (Steps 6, 7, 8).
"""
import os
import pandas as pd
from src.cleaning.constants import MISSING_TOKENS
from src.cleaning.text_utils import clean_unicode_and_ws


def load_district_display_map(mapping_path: str | None = None) -> dict[str, str]:
    if mapping_path and os.path.exists(mapping_path):
        try:
            m_df = pd.read_csv(mapping_path, dtype=str)
            if "district_clean" in m_df.columns and "district_display" in m_df.columns:
                return dict(zip(m_df["district_clean"], m_df["district_display"]))
        except Exception:
            pass
    return {}


def process_labels(df: pd.DataFrame, district_map_path: str | None = None) -> pd.DataFrame:
    """
    Standardises QueryType, Category, Crop, Sector, DistrictName, BlockName.
    Sets flags: flag_sector_numeric, flag_district_invalid.
    """
    district_display_map = load_district_display_map(district_map_path)

    # 1. QueryType
    def clean_qt(val: str) -> str | None:
        c = clean_unicode_and_ws(val)
        return None if c.lower() in MISSING_TOKENS else c

    df["query_type_clean"] = df["QueryType"].apply(clean_qt)

    # 2. Category
    def clean_cat(val: str) -> str | None:
        c = clean_unicode_and_ws(val)
        return None if c.lower() in MISSING_TOKENS else c

    df["category_clean"] = df["Category"].apply(clean_cat)

    # 3. Crop
    def clean_crop(val: str) -> str | None:
        c = clean_unicode_and_ws(val)
        return None if c.lower() in MISSING_TOKENS else c

    df["crop_clean"] = df["Crop"].apply(clean_crop)

    # 4. Sector
    sector_cleaned = []
    sector_numeric_flags = []
    for s in df["Sector"]:
        cs = clean_unicode_and_ws(s)
        if cs.isdigit():
            sector_cleaned.append(None)
            sector_numeric_flags.append(True)
        elif cs.lower() in MISSING_TOKENS:
            sector_cleaned.append(None)
            sector_numeric_flags.append(False)
        else:
            sector_cleaned.append(cs)
            sector_numeric_flags.append(False)
    df["sector_clean"] = sector_cleaned
    df["flag_sector_numeric"] = sector_numeric_flags

    # 5. DistrictName
    dist_cleaned = []
    dist_invalid_flags = []
    for d in df["DistrictName"]:
        cd = clean_unicode_and_ws(d).upper()
        if cd in {"0", "9999"} or cd.isdigit() or cd.lower() in MISSING_TOKENS:
            dist_cleaned.append(None)
            dist_invalid_flags.append(True)
        else:
            dist_cleaned.append(cd)
            dist_invalid_flags.append(False)
    df["district_clean"] = dist_cleaned
    df["flag_district_invalid"] = dist_invalid_flags

    # Optional display name mapping
    df["district_display"] = df["district_clean"].map(
        lambda x: district_display_map.get(x, x) if x is not None else None
    )

    # 6. BlockName
    def clean_block(val: str) -> str | None:
        cb = clean_unicode_and_ws(val).upper()
        return None if cb.lower() in MISSING_TOKENS else cb

    df["block_clean"] = df["BlockName"].apply(clean_block)

    return df
