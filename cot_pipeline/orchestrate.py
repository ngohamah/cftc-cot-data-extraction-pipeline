"""Orchestration: wire the stages together for one pipeline run.

Saved files only grow by appending new weeks; a full rewrite happens only when a file is
created, rebuilt, or can't be appended to safely (the reason is logged).
"""

import datetime as dt
import logging
from dataclasses import dataclass

import pandas as pd

import config
from cot_pipeline.extract import (
    download_reports,
    historical_file_path,
    load_historical_file,
    load_saved_reports,
    plan_downloads,
    report_years,
)
from cot_pipeline.report import render_report, summarise_symbol
from cot_pipeline.signals import compute_signals
from cot_pipeline.storage import append_csv, read_saved_csv, write_csv, write_text
from cot_pipeline.transform import (
    add_net_positions,
    clean_report,
    extend_with_net_positions,
    has_duplicate_records,
    history_to_backfill,
    is_oldest_first,
    may_lack_history,
    merge_symbol_data,
    rewrite_reason,
    rows_for_symbol,
    split_incoming,
)

logger = logging.getLogger(__name__)

CREATED, REWRITTEN, APPENDED, UNCHANGED = "created", "rewritten", "appended", "unchanged"


@dataclass(frozen=True)
class SymbolUpdate:
    """Outcome of updating one symbol's data file during a run."""

    data: pd.DataFrame  # full history after this run, oldest first
    written: pd.DataFrame  # rows written to the file this run
    mode: str  # CREATED | REWRITTEN | APPENDED | UNCHANGED
    new_count: int  # records this run added that weren't saved before


def log_merge_drops(symbol, duplicates, other_contracts):
    """Log rows merge_symbol_data dropped: repeated reports, and smaller contracts per market name."""
    if duplicates:
        logger.info("%s: dropped %d duplicate rows (same market and date)", symbol, duplicates)
    for market, count in other_contracts[config.MARKET_COL].value_counts().items():
        logger.info(
            "%s: dropped %d weeks of %s - a larger contract of %s was reported the same week (one report per week)",
            symbol,
            count,
            market,
            symbol,
        )


def validation_problems(data):
    """Reasons data can't be saved as a symbol's history (empty list if it is valid)."""
    checks = [
        (has_duplicate_records(data), "more than one record for the same week"),
        (not is_oldest_first(data), "weeks are not in oldest-first order"),
        (data[config.DATE_COL].isna().any(), "records without a report date"),
    ]
    return [reason for failed, reason in checks if failed]


def create_symbol_file(symbol, path, incoming, get_history, rebuild):
    """Write data/<symbol>.csv from scratch: 1986-2016 history (if available) followed by the new reports.

    Used when the file is missing or unreadable, or when rebuild=True (the saved file is then overwritten).
    incoming holds the symbol's cleaned 2017+ report rows; get_history returns the cleaned history rows
    for all markets, or None if raw/FUT86_16.txt is unavailable. Returns a SymbolUpdate (mode CREATED),
    or None if there is no data at all, in which case no file is written.
    """
    history_rows = get_history()
    history = None if history_rows is None else rows_for_symbol(history_rows, symbol)
    sources = [history, incoming]
    if all(s is None or s.empty for s in sources):
        logger.warning("No data at all for %s - %s not written", symbol, path)
        return None
    merged, duplicates, other_contracts = merge_symbol_data(sources)
    log_merge_drops(symbol, duplicates, other_contracts)
    write_csv(merged, path)
    logger.info("%s: %s %s with %d records", symbol, "rebuilt" if rebuild else "created", path, len(merged))
    return SymbolUpdate(merged, merged, CREATED, len(merged))


def missing_history(symbol, existing, get_history):
    """1986-2016 history for symbol that the saved file doesn't have yet (empty if none or not needed)."""
    if not may_lack_history(existing):
        return existing.iloc[0:0]
    history_rows = get_history()
    if history_rows is None:
        return existing.iloc[0:0]
    return history_to_backfill(existing, rows_for_symbol(history_rows, symbol))


def update_symbol(symbol, new_rows, data_dir, get_history, rebuild=False):
    """Bring data/<symbol>.csv up to date, appending only records it doesn't have yet.

    Returns a SymbolUpdate, or None if there is no data at all for the symbol.
    """
    path = data_dir / f"{symbol}.csv"
    incoming = rows_for_symbol(new_rows, symbol)
    saved = None if rebuild else read_saved_csv(path)
    if saved is None:
        return create_symbol_file(symbol, path, incoming, get_history, rebuild)

    existing, unreadable = clean_report(saved)
    if len(existing) < len(saved):
        logger.warning(
            "%s: %s has %d rows with unknown markets and %d with unreadable dates - they will be removed",
            symbol,
            path,
            len(saved) - len(existing) - unreadable,
            unreadable,
        )
    fresh, revised = split_incoming(existing, incoming)
    if revised:
        logger.warning(
            "%s: CFTC revised %d already-saved records - saved values kept (run with --rebuild to apply)",
            symbol,
            revised,
        )

    backfill = missing_history(symbol, existing, get_history)
    reason = rewrite_reason(saved, existing, fresh)
    if len(backfill):
        history_note = f"adding {len(backfill)} older records from {config.HISTORICAL_FILENAME}"
        reason = f"{history_note}; {reason}" if reason else history_note
    if reason:
        merged, duplicates, other_contracts = merge_symbol_data([backfill, existing, fresh])
        log_merge_drops(symbol, duplicates, other_contracts)
        write_csv(merged, path)
        kept = int(merged[config.DATE_COL].isin(existing[config.DATE_COL]).sum())
        added = len(merged) - kept
        logger.info(
            "%s: rewrote %s in full (%s): %d records, %d added, %d saved rows removed",
            symbol,
            path,
            reason,
            len(merged),
            added,
            len(saved) - kept,
        )
        return SymbolUpdate(merged, merged, REWRITTEN, added)

    data = add_net_positions(existing)[config.DATA_COLUMNS]
    if fresh.empty:
        logger.info("%s: no new records - %s unchanged (%d records)", symbol, path, len(data))
        return SymbolUpdate(data, data.iloc[0:0], UNCHANGED, 0)

    appended = extend_with_net_positions(existing, fresh)
    append_csv(appended, path)
    logger.info(
        "%s: appended %d new records to %s (%s to %s)",
        symbol,
        len(appended),
        path,
        appended[config.DATE_COL].iloc[0],
        appended[config.DATE_COL].iloc[-1],
    )
    return SymbolUpdate(pd.concat([data, appended], ignore_index=True), appended, APPENDED, len(appended))


def signal_file_matches(path, data):
    """True if the saved signal file has exactly data's weeks, in the same order."""
    saved = read_saved_csv(path, required=config.SIGNAL_COLUMNS) if path.exists() else None
    return (
        saved is not None
        and list(saved.columns) == config.SIGNAL_COLUMNS
        and saved[config.DATE_COL].astype(str).tolist() == data[config.DATE_COL].tolist()
    )


def update_signals(symbol, update, signal_dir):
    """Append signals for new records; write the file in full only if it is missing or out of step."""
    path = signal_dir / f"{symbol}.csv"
    before = update.data.iloc[: len(update.data) - len(update.written)]
    if update.mode in (APPENDED, UNCHANGED) and signal_file_matches(path, before):
        if update.mode == UNCHANGED:
            logger.info("%s: no new signals - %s unchanged", symbol, path)
            return
        append_csv(compute_signals(update.written)[config.SIGNAL_COLUMNS], path)
        logger.info("%s: appended %d new signals to %s", symbol, len(update.written), path)
        return
    write_csv(compute_signals(update.data)[config.SIGNAL_COLUMNS], path)
    logger.info("%s: wrote %s in full: %d signals", symbol, path, len(update.data))


def memoize(func):
    """Call func at most once (used so the large historical file is only read if needed)."""
    cache = {}

    def wrapper():
        """Return the cached result, calling func on first use."""
        if "value" not in cache:
            cache["value"] = func()
        return cache["value"]

    return wrapper


def run(years, data_dir, signal_dir, raw_dir, report_dir, refresh=False, rebuild=False, offline=False):
    """Run every stage; returns a process exit code (0 ok, 1 finished with problems)."""
    now = dt.datetime.now(dt.UTC)
    problems = []
    logger.info("Pipeline started for years %s-%s", years[0], years[-1])

    if offline:
        logger.info("Offline mode - using saved reports in %s only", raw_dir)
    else:
        plan = plan_downloads(years, raw_dir, now, refresh)
        for year, download, reason in plan:
            logger.info("%s report: %s (%s)", year, "download" if download else "not downloaded", reason)
        failed = download_reports([year for year, download, _ in plan if download], raw_dir)
        problems += [f"Could not download the {y} report; saved copy used if available." for y in failed]

    raw_reports = load_saved_reports(report_years(years, now), raw_dir)
    try:
        new_rows, dropped = clean_report(raw_reports) if len(raw_reports) else (raw_reports, 0)
    except ValueError as err:
        logger.error("Downloaded reports are not in the expected format: %s", err)
        return 1
    if dropped:
        logger.warning("Dropped %d report rows with unreadable dates", dropped)

    @memoize
    def get_history():
        """Cleaned 1986-2016 history for all markets, or None if the file is unavailable (read at most once per run)."""
        history = load_historical_file(historical_file_path(raw_dir))
        return None if history is None else clean_report(history)[0]

    summaries, new_records = [], 0
    for symbol in config.SYMBOL_NAMES:
        try:
            update = update_symbol(symbol, new_rows, data_dir, get_history, rebuild)
            if update is None:
                problems.append(f"No data found for {symbol}; no files written.")
                continue
            invalid = validation_problems(update.data)
            if invalid:
                logger.error("%s: data failed validation (%s) - signals not updated", symbol, "; ".join(invalid))
                problems.append(f"{symbol} data failed validation ({'; '.join(invalid)}); signals not updated.")
                continue
            update_signals(symbol, update, signal_dir)
            new_records += update.new_count
            summaries.append(summarise_symbol(symbol, compute_signals(update.data), update.new_count))
        except (OSError, ValueError, KeyError) as err:
            logger.exception("Failed to process %s", symbol)
            problems.append(f"{symbol} could not be updated ({err}).")

    report_path = report_dir / "latest_signals.md"
    write_text(render_report(summaries, now.astimezone(), problems), report_path)
    logger.info("Saved %s", report_path)
    logger.info(
        "Pipeline finished: %d symbols processed, %d new records written, %d problems",
        len(summaries),
        new_records,
        len(problems),
    )
    return 1 if problems else 0
