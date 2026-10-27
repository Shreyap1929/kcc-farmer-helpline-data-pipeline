"""
Command-line runner for KCC Stage 1 Data Cleaning Pipeline.
Example:
    python -m src.cleaning.run --raw data/raw --out data/clean --reports reports --config config
"""
import argparse
import sys
from src.cleaning.pipeline import run_pipeline


def main():
    parser = argparse.ArgumentParser(description="KCC Farmer Helpline Data Cleaning - Stage 1")
    parser.add_argument(
        "--raw",
        type=str,
        default="data/raw",
        help="Path to directory containing raw CSV files (default: data/raw)",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="data/clean",
        help="Path to directory where cleaned outputs will be written (default: data/clean)",
    )
    parser.add_argument(
        "--reports",
        type=str,
        default="reports",
        help="Path to directory where reports, value counts and samples will be written (default: reports)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config",
        help="Path to config directory containing season_map.yaml and district_display.csv (default: config)",
    )
    parser.add_argument(
        "--zips",
        nargs="*",
        default=["D:/Downloads/DATASETS.zip", "D:/Downloads/2025-dataset.zip"],
        help="Paths to zip files to extract into raw directory if needed",
    )

    args = parser.parse_args()

    try:
        run_pipeline(
            raw_dir=args.raw,
            out_dir=args.out,
            reports_dir=args.reports,
            config_dir=args.config,
            zip_paths=args.zips,
        )
    except Exception as e:
        print(f"Pipeline error: {e}", file=sys.stderr)
        raise e


if __name__ == "__main__":
    main()
