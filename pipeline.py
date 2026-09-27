"""End-to-end COT pipeline: download -> clean -> merge -> signals -> report.

Converted from cot_report_analysis.ipynb. Run with ``python pipeline.py``
(see ``python pipeline.py --help`` for options). The stages live in cot_pipeline/.
"""

import argparse
import datetime as dt
import logging
import os
import sys
from pathlib import Path

import config
from cot_pipeline.logging_setup import LOGGER_NAME, configure_logging
from cot_pipeline.orchestrate import run

logger = logging.getLogger(f"{LOGGER_NAME}.cli")


def parse_args(argv=None):
    """Parse command-line options; defaults come from config.py (argv=None reads sys.argv)."""
    current_year = dt.date.today().year
    parser = argparse.ArgumentParser(description="Download, clean and score CFTC Commitments of Traders data.")
    parser.add_argument("--start-year", type=int, default=config.FIRST_API_YEAR)
    parser.add_argument("--end-year", type=int, default=current_year)
    parser.add_argument(
        "--refresh", action="store_true", help="re-download every year even if saved copies are up to date"
    )
    parser.add_argument(
        "--rebuild", action="store_true", help="ignore saved data/*.csv and rebuild from history + reports"
    )
    parser.add_argument("--offline", action="store_true", help="skip downloads and use saved reports in raw/")
    parser.add_argument("--data-dir", type=Path, default=config.DATA_DIR)
    parser.add_argument("--signal-dir", type=Path, default=config.SIGNAL_DIR)
    parser.add_argument(
        "--raw-dir", type=Path, default=config.RAW_DIR, help="saved source data: FUT86_16.txt + yearly zips"
    )
    parser.add_argument("--report-dir", type=Path, default=config.REPORT_DIR)
    parser.add_argument("--log-file", type=Path, default=config.LOG_FILE)
    return parser.parse_args(argv)


def ci_run_description(env):
    """'<event> run <url>' when running inside GitHub Actions, else None (for tracing bot commits)."""
    if env.get("GITHUB_ACTIONS") != "true":
        return None
    url = f"{env.get('GITHUB_SERVER_URL', 'https://github.com')}/{env.get('GITHUB_REPOSITORY')}/actions/runs/"
    return f"{env.get('GITHUB_EVENT_NAME', 'unknown')} run {url}{env.get('GITHUB_RUN_ID')}"


def main(argv=None):
    """Command-line entry point: set up logging, run the pipeline for the chosen years, return the exit code."""
    args = parse_args(argv)
    configure_logging(args.log_file)
    ci_run = ci_run_description(os.environ)
    if ci_run:
        logger.info("Started by GitHub Actions: %s", ci_run)
    years = list(range(args.start_year, args.end_year + 1))
    return run(
        years,
        args.data_dir,
        args.signal_dir,
        args.raw_dir,
        args.report_dir,
        refresh=args.refresh,
        rebuild=args.rebuild,
        offline=args.offline,
    )


if __name__ == "__main__":
    sys.exit(main())
