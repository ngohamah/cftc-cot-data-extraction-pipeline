"""Orchestration: wire the stages together for one pipeline run."""

import datetime as dt
import logging

import config
from cot_pipeline.extract import download_reports, load_historical_file, load_saved_reports, years_to_download
from cot_pipeline.report import render_report, summarise_symbol
from cot_pipeline.signals import compute_signals
from cot_pipeline.storage import read_existing, write_csv, write_text
from cot_pipeline.transform import clean_report, merge_symbol_data, rows_for_symbol

logger = logging.getLogger(__name__)


def update_symbol(symbol, new_rows, data_dir, get_history, rebuild=False):
    """Merge new rows into data/<symbol>.csv. Returns the saved frame or None."""
    path = data_dir / f"{symbol}.csv"
    existing = None if rebuild else read_existing(path)
    history = None
    if existing is None:
        history_rows = get_history()
        history = None if history_rows is None else rows_for_symbol(history_rows, symbol)
    sources = [history, existing, rows_for_symbol(new_rows, symbol)]
    if all(s is None or s.empty for s in sources):
        logger.warning("No data at all for %s - %s not written", symbol, path)
        return None
    merged, duplicates = merge_symbol_data(sources)
    if duplicates:
        logger.info("%s: dropped %d duplicate rows (same market and date)", symbol, duplicates)
    if existing is not None and len(merged) < len(existing):
        logger.error(
            "%s: merged data has fewer rows (%d) than saved file (%d) - not overwritten",
            symbol,
            len(merged),
            len(existing),
        )
        return existing
    write_csv(merged, path)
    added = len(merged) - (0 if existing is None else len(existing))
    logger.info("Saved %s: %d rows (%+d)", path, len(merged), added)
    return merged


def write_signals(symbol, data, signal_dir):
    signals = compute_signals(data)
    path = signal_dir / f"{symbol}.csv"
    write_csv(signals[config.SIGNAL_COLUMNS], path)
    logger.info("Saved %s: %d rows", path, len(signals))
    return signals


def memoize(func):
    """Call func at most once (used so the large historical file is only read if needed)."""
    cache = {}

    def wrapper():
        if "value" not in cache:
            cache["value"] = func()
        return cache["value"]

    return wrapper


def run(years, data_dir, signal_dir, raw_dir, report_dir, historical_file, refresh=False, rebuild=False, offline=False):
    """Run every stage; returns a process exit code (0 ok, 1 finished with problems)."""
    now = dt.datetime.now()
    problems = []
    logger.info("Pipeline started for years %s-%s", years[0], years[-1])

    if offline:
        logger.info("Offline mode - using saved reports in %s only", raw_dir)
    else:
        failed = download_reports(years_to_download(years, raw_dir, now.year, refresh), raw_dir)
        problems += [f"Could not download the {y} report; saved copy used if available." for y in failed]

    raw_reports = load_saved_reports(years, raw_dir)
    try:
        new_rows, dropped = clean_report(raw_reports) if len(raw_reports) else (raw_reports, 0)
    except ValueError as err:
        logger.error("Downloaded reports are not in the expected format: %s", err)
        return 1
    if dropped:
        logger.warning("Dropped %d report rows with unreadable dates", dropped)

    @memoize
    def get_history():
        history = load_historical_file(historical_file)
        return None if history is None else clean_report(history)[0]

    summaries = []
    for symbol in config.SYMBOL_NAMES:
        try:
            data = update_symbol(symbol, new_rows, data_dir, get_history, rebuild)
            if data is None:
                problems.append(f"No data found for {symbol}; no files written.")
                continue
            summaries.append(summarise_symbol(symbol, write_signals(symbol, data, signal_dir)))
        except (OSError, ValueError, KeyError) as err:
            logger.exception("Failed to process %s", symbol)
            problems.append(f"{symbol} could not be updated ({err}).")

    report_path = report_dir / "latest_signals.md"
    write_text(render_report(summaries, now, problems), report_path)
    logger.info("Saved %s", report_path)
    logger.info("Pipeline finished: %d symbols updated, %d problems", len(summaries), len(problems))
    return 1 if problems else 0
