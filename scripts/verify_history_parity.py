"""Verify that raw/FUT86_16.txt matches the CFTC's own per-year files for 1986-2016.

Downloads each year's legacy futures zip once (saved to raw/parity_check/, reused on later runs),
compares it with the same year in the history file, and writes:
  reports/history_parity.md              plain-language summary
  reports/history_parity_mismatches.csv  every differing cell found (first 200 per year)
Progress and decisions are logged to logs/pipeline.log. Exit code 0 = full match, 1 = differences.

Usage: python scripts/verify_history_parity.py [--start-year 1986] [--end-year 2016] [--refresh]
"""

import argparse
import datetime as dt
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # allow running from any folder

import pandas as pd  # noqa: E402

import config  # noqa: E402
from cot_pipeline.extract import (  # noqa: E402
    download_reports,
    raw_zip_path,
    read_report_zip,
    saved_report_latest_date,
)
from cot_pipeline.logging_setup import LOGGER_NAME, configure_logging  # noqa: E402
from cot_pipeline.parity import compare_year, pipeline_subset, render_parity_report, rows_for_year  # noqa: E402
from cot_pipeline.storage import write_csv, write_text  # noqa: E402

logger = logging.getLogger(f"{LOGGER_NAME}.parity")

PARITY_DIR = config.RAW_DIR / "parity_check"
REPORT_NAME = "history_parity.md"
MISMATCH_NAME = "history_parity_mismatches.csv"


def parse_args(argv=None):
    """Parse command-line options for the parity check."""
    parser = argparse.ArgumentParser(description="Compare FUT86_16.txt with per-year CFTC downloads.")
    parser.add_argument("--start-year", type=int, default=1986)
    parser.add_argument("--end-year", type=int, default=config.FIRST_API_YEAR - 1)
    parser.add_argument("--refresh", action="store_true", help="re-download years already saved for the check")
    parser.add_argument("--history-file", type=Path, default=config.HISTORICAL_FILE)
    parser.add_argument("--download-dir", type=Path, default=PARITY_DIR)
    parser.add_argument("--report-dir", type=Path, default=config.REPORT_DIR)
    parser.add_argument("--log-file", type=Path, default=config.LOG_FILE)
    return parser.parse_args(argv)


def ensure_downloads(years, download_dir, refresh):
    """Download only years without a readable saved zip (or all with refresh); returns failed years."""
    needed = [y for y in years if refresh or saved_report_latest_date(raw_zip_path(y, download_dir)) is None]
    for year in years:
        logger.info("Parity %s: %s", year, "download" if year in needed else "using saved download")
    return download_reports(needed, download_dir) if needed else []


def main(argv=None):
    """Run the parity check and return 0 for a full match, 1 if anything differs or is missing."""
    args = parse_args(argv)
    configure_logging(args.log_file)
    years = list(range(args.start_year, args.end_year + 1))
    logger.info("Parity check started: %s vs CFTC yearly files %s-%s", args.history_file, years[0], years[-1])

    if not args.history_file.exists():
        logger.error("%s not found - nothing to compare", args.history_file)
        return 1
    history = pd.read_csv(args.history_file, low_memory=False)
    logger.info("Loaded %s: %d rows, %d columns", args.history_file, len(history), history.shape[1])

    failed = ensure_downloads(years, args.download_dir, args.refresh)
    full_results, pipeline_results, examples = [], [], []
    for year in years:
        if year in failed:
            logger.error("Parity %s: download failed - year not compared", year)
            continue
        download = read_report_zip(raw_zip_path(year, args.download_dir))
        history_year = rows_for_year(history, year)
        full = compare_year(year, history_year, download)
        pipeline = compare_year(
            year, pipeline_subset(history_year), pipeline_subset(download), columns=config.SPECIAL_COLUMNS
        )
        full_results.append(full)
        pipeline_results.append(pipeline)
        examples.append(full.examples)
        logger.info(
            "Parity %s: %s - rows history %d / download %d, missing %d, extra %d, cells differ %d of %d; "
            "pipeline data %s",
            year,
            "MATCH" if full.matches else "DIFFERENT",
            full.history_rows,
            full.download_rows,
            full.rows_only_in_download,
            full.rows_only_in_history,
            full.cells_different,
            full.cells_compared,
            "match" if pipeline.matches else "DIFFERENT",
        )

    outside = rows_for_year_range_outside(history, years)
    if outside:
        logger.warning("History file has %d rows dated outside %s-%s (not compared)", outside, years[0], years[-1])

    report_file, mismatch_file = args.report_dir / REPORT_NAME, args.report_dir / MISMATCH_NAME
    write_text(render_parity_report(full_results, pipeline_results, args.history_file, dt.datetime.now()), report_file)
    mismatches = (
        pd.concat([e for e in examples if len(e)], ignore_index=True) if any(len(e) for e in examples) else None
    )
    if mismatches is not None:
        write_csv(mismatches, mismatch_file)
        logger.info("Saved %s: %d example mismatches", mismatch_file, len(mismatches))
    logger.info("Saved %s", report_file)

    ok = not failed and all(r.matches for r in full_results)
    logger.info(
        "Parity check finished: %d/%d years match fully, %d/%d match on pipeline data, %d downloads failed",
        sum(r.matches for r in full_results),
        len(years),
        sum(r.matches for r in pipeline_results),
        len(years),
        len(failed),
    )
    return 0 if ok else 1


def rows_for_year_range_outside(history, years):
    """Number of history rows dated outside the compared years (or with unreadable dates)."""
    dates = pd.to_datetime(history[config.DATE_COL], errors="coerce")
    return int((~dates.dt.year.isin(years)).sum())


if __name__ == "__main__":
    sys.exit(main())
