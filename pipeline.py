"""End-to-end COT pipeline: download -> clean -> merge -> signals -> report.

Converted from cot_report_analysis.ipynb. Run with ``python pipeline.py``
(see ``python pipeline.py --help`` for options). The stages live in cot_pipeline/.
"""

import argparse
import datetime as dt
import sys
from pathlib import Path

import config
from cot_pipeline.logging_setup import configure_logging
from cot_pipeline.orchestrate import run


def parse_args(argv=None):
    current_year = dt.date.today().year
    parser = argparse.ArgumentParser(description="Download, clean and score CFTC Commitments of Traders data.")
    parser.add_argument("--start-year", type=int, default=config.FIRST_API_YEAR)
    parser.add_argument("--end-year", type=int, default=current_year)
    parser.add_argument("--refresh", action="store_true", help="re-download every year, not just new/current ones")
    parser.add_argument(
        "--rebuild", action="store_true", help="ignore saved data/*.csv and rebuild from history + reports"
    )
    parser.add_argument("--offline", action="store_true", help="skip downloads and use saved reports in raw/")
    parser.add_argument("--data-dir", type=Path, default=config.DATA_DIR)
    parser.add_argument("--signal-dir", type=Path, default=config.SIGNAL_DIR)
    parser.add_argument("--raw-dir", type=Path, default=config.RAW_DIR)
    parser.add_argument("--report-dir", type=Path, default=config.REPORT_DIR)
    parser.add_argument("--historical-file", type=Path, default=config.HISTORICAL_FILE)
    parser.add_argument("--log-file", type=Path, default=config.LOG_FILE)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    configure_logging(args.log_file)
    years = list(range(args.start_year, args.end_year + 1))
    return run(
        years,
        args.data_dir,
        args.signal_dir,
        args.raw_dir,
        args.report_dir,
        args.historical_file,
        refresh=args.refresh,
        rebuild=args.rebuild,
        offline=args.offline,
    )


if __name__ == "__main__":
    sys.exit(main())
