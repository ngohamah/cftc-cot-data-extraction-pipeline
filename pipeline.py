"""End-to-end COT pipeline: download -> clean -> merge -> signals -> report.

Converted from cot_report_analysis.ipynb. Run with ``python pipeline.py``
(see ``python pipeline.py --help`` for options).
"""

import argparse
import datetime as dt
import io
import logging
import os
import sys
import tempfile
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import config

logger = logging.getLogger("cot_pipeline")


# --- setup -----------------------------------------------------------------
def configure_logging(log_file=config.LOG_FILE):
    """Log to a file (full history) and to the console (progress)."""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    file_handler = logging.FileHandler(log_file)
    console_handler = logging.StreamHandler(sys.stdout)
    for handler in (file_handler, console_handler):
        handler.setFormatter(formatter)
    logger.handlers = [file_handler, console_handler]
    logger.setLevel(logging.INFO)


# --- extract: CFTC yearly reports -------------------------------------------
def raw_zip_path(year, raw_dir):
    return raw_dir / f"legacy_fut_{year}.zip"


def years_to_download(years, raw_dir, current_year, refresh=False):
    """Years with no saved batch, plus the current year (CFTC updates it weekly)."""
    return [year for year in years if refresh or year == current_year or not raw_zip_path(year, raw_dir).exists()]


def make_session(retries=config.REQUEST_RETRIES):
    """HTTP session that retries transient failures with backoff."""
    retry = Retry(total=retries, backoff_factor=2, status_forcelist=(429, 500, 502, 503, 504))
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def download_reports(years, raw_dir, session_factory=make_session):
    """Download each year's zip once over a single session and save it to raw_dir.

    Returns the list of years that failed; failures are logged and skipped.
    """
    raw_dir.mkdir(parents=True, exist_ok=True)
    failed = []
    with session_factory() as session:
        for year in years:
            url = config.CFTC_YEAR_URL.format(year=year)
            try:
                response = session.get(url, timeout=config.REQUEST_TIMEOUT_SECONDS)
                response.raise_for_status()
                zipfile.ZipFile(io.BytesIO(response.content)).testzip()
            except (requests.RequestException, zipfile.BadZipFile) as err:
                logger.error("Could not download %s report from %s (%s)", year, url, err)
                failed.append(year)
                continue
            path = raw_zip_path(year, raw_dir)
            write_atomically(path, lambda tmp, data=response.content: Path(tmp).write_bytes(data))
            logger.info("Downloaded %s report (%d KB) -> %s", year, len(response.content) // 1024, path)
    return failed


def read_report_zip(path):
    """Read the single .txt report inside a CFTC zip."""
    with zipfile.ZipFile(path) as archive:
        name = next(n for n in archive.namelist() if n.lower().endswith(".txt"))
        with archive.open(name) as handle:
            return pd.read_csv(handle, low_memory=False)


def load_saved_reports(years, raw_dir):
    """Load every saved yearly batch; missing/corrupt years are logged and skipped."""

    def load(year):
        path = raw_zip_path(year, raw_dir)
        if not path.exists():
            logger.warning("No saved report for %s (%s missing) - year skipped", year, path)
            return None
        try:
            report = read_report_zip(path)
        except (zipfile.BadZipFile, StopIteration, pd.errors.ParserError) as err:
            logger.error("Could not read %s (%s) - year skipped", path, err)
            return None
        logger.info("Loaded %s report: %d rows", year, len(report))
        return report

    reports = [r for r in map(load, years) if r is not None]
    return pd.concat(reports, ignore_index=True) if reports else pd.DataFrame(columns=config.SPECIAL_COLUMNS)


def load_historical_file(path=config.HISTORICAL_FILE):
    """Legacy futures 1986-2016 from the local file, or None if it is unavailable."""
    if not path.exists():
        logger.warning("%s not found - history before %s will be missing", path, config.FIRST_API_YEAR)
        return None
    try:
        history = pd.read_csv(path, usecols=config.SPECIAL_COLUMNS, low_memory=False)
    except (ValueError, pd.errors.ParserError) as err:
        logger.error("Could not read %s (%s) - history before %s will be missing", path, err, config.FIRST_API_YEAR)
        return None
    logger.info("Loaded historical file %s: %d rows", path, len(history))
    return history


# --- transform (pure functions) --------------------------------------------
def missing_columns(dataframe, required=config.SPECIAL_COLUMNS):
    return [c for c in required if c not in dataframe.columns]


def clean_report(dataframe):
    """Keep our markets and columns, unify names, parse numbers and dates.

    Returns (cleaned_frame, dropped_row_count). Rows with unreadable dates are dropped.
    """
    missing = missing_columns(dataframe)
    if missing:
        raise ValueError(f"Report is missing required columns: {missing}")
    selected = dataframe.loc[dataframe[config.MARKET_COL].isin(config.MARKETS_AND_EXCHANGES), config.SPECIAL_COLUMNS]
    numeric = {c: pd.to_numeric(selected[c].astype(str).str.strip(), errors="coerce") for c in config.NUMERIC_COLUMNS}
    cleaned = selected.assign(
        **{config.MARKET_COL: selected[config.MARKET_COL].replace(config.MARKET_NAME_REPLACEMENTS)},
        **{config.DATE_COL: pd.to_datetime(selected[config.DATE_COL], errors="coerce").dt.strftime("%Y-%m-%d")},
        **numeric,
    )
    valid = cleaned.dropna(subset=[config.DATE_COL])
    return valid, len(cleaned) - len(valid)


def rows_for_symbol(dataframe, symbol, markets=config.MARKETS_AND_EXCHANGES):
    """Rows whose market name belongs to symbol."""
    names = [mx for mx in markets if symbol in mx]
    return dataframe[dataframe[config.MARKET_COL].isin(names)]


def add_net_positions(dataframe):
    """Sort newest-first and add Net Positions and Change Net Positions."""
    ordered = dataframe.sort_values(by=config.DATE_COL, ascending=False, kind="stable").reset_index(drop=True)
    net = ordered[config.LONG_COL] - ordered[config.SHORT_COL]
    return ordered.assign(**{config.NET_COL: net, config.NET_CHANGE_COL: net.diff(-1)})


def merge_symbol_data(frames):
    """Combine frames (oldest source first); later frames win on repeated reports.

    Returns (merged_frame, duplicate_row_count).
    """
    combined = pd.concat([f[config.SPECIAL_COLUMNS] for f in frames if f is not None], ignore_index=True)
    deduped = combined.drop_duplicates(subset=[config.MARKET_COL, config.DATE_COL], keep="last")
    return add_net_positions(deduped)[config.DATA_COLUMNS], len(combined) - len(deduped)


def compute_signals(dataframe):
    """Signal code and interpretation from Change Net Positions vs Change in Open Interest.

    Change in net positions stands in for price direction (see notebook for rationale):
        net up,   OI up   -> 1 Bullish           net up,   OI down -> 4 Bullish Reversal
        net down, OI up   -> 2 Bearish           net down, OI down -> 3 Bearish Reversal
    """
    net_change = dataframe[config.NET_CHANGE_COL]
    oi_change = pd.to_numeric(dataframe[config.OPEN_INTEREST_CHANGE_COL], errors="coerce").fillna(0).astype(int)
    conditions = [
        (net_change > 0) & (oi_change > 0),
        (net_change > 0) & (oi_change < 0),
        (net_change < 0) & (oi_change > 0),
        (net_change < 0) & (oi_change < 0),
    ]
    outcomes = [
        config.SIGNAL_BULLISH,
        config.SIGNAL_BULLISH_REVERSAL,
        config.SIGNAL_BEARISH,
        config.SIGNAL_BEARISH_REVERSAL,
    ]
    return dataframe.assign(
        **{
            config.OPEN_INTEREST_CHANGE_COL: oi_change,
            "signal": np.select(conditions, [code for code, _ in outcomes], default=config.SIGNAL_NONE[0]),
            "Interpretation": np.select(conditions, [text for _, text in outcomes], default=config.SIGNAL_NONE[1]),
        }
    )


def summarise_symbol(symbol, signals):
    """One plain-language row describing a symbol's latest week."""
    latest = signals.iloc[0]
    return {
        "Market": symbol,
        "Week of": latest[config.DATE_COL],
        "Large speculators net position (contracts)": f"{int(latest[config.NET_COL]):,}",
        "Change vs previous week": "n/a"
        if pd.isna(latest[config.NET_CHANGE_COL])
        else f"{int(latest[config.NET_CHANGE_COL]):+,}",
        "Reading": latest["Interpretation"],
    }


def render_report(rows, run_time, problems):
    """Markdown summary for non-technical readers."""
    table = pd.DataFrame(rows)
    header = "| " + " | ".join(table.columns) + " |\n|" + "---|" * len(table.columns) + "\n" if rows else ""
    body = "".join("| " + " | ".join(str(v) for v in row) + " |\n" for row in table.itertuples(index=False))
    issues = "".join(f"- {p}\n" for p in problems) or "- None\n"
    return (
        "# Commitments of Traders - weekly summary\n\n"
        f"_Generated {run_time:%Y-%m-%d %H:%M}_\n\n"
        "**What this shows:** each week the CFTC reports how many futures contracts large "
        "speculators (hedge funds, money managers) hold betting on prices rising (long) or "
        "falling (short). The *net position* is longs minus shorts. The *reading* combines the "
        "weekly change in that net position with the change in open interest (total contracts "
        "outstanding):\n\n"
        "- **Bullish** - speculators added to bets on rising prices while new money entered.\n"
        "- **Bearish** - speculators cut bets on rising prices while new money entered.\n"
        "- **Bullish / Bearish Reversal** - the same moves but with money leaving the market, "
        "which often comes before a change in direction.\n\n"
        "This is an indicator, not a trading recommendation.\n\n"
        "## Latest week by market\n\n"
        f"{header}{body}\n"
        "## Issues during this run\n\n"
        f"{issues}"
    )


# --- load: storage ----------------------------------------------------------
def write_atomically(path, write):
    """Write via a temp file in the same folder, then rename, so a crash never leaves a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    os.close(fd)
    try:
        write(tmp)
        os.chmod(tmp, 0o644)  # mkstemp creates owner-only files
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_csv(dataframe, path):
    write_atomically(path, lambda tmp: dataframe.to_csv(tmp, index=False))


def read_existing(path):
    """Saved data for a symbol, or None if missing/unreadable (it is then rebuilt)."""
    if not path.exists():
        logger.warning("%s not found - it will be created", path)
        return None
    try:
        existing = pd.read_csv(path)
    except (pd.errors.EmptyDataError, pd.errors.ParserError) as err:
        logger.error("Could not read %s (%s) - it will be rebuilt", path, err)
        return None
    missing = missing_columns(existing)
    if missing:
        logger.error("%s is missing columns %s - it will be rebuilt", path, missing)
        return None
    return clean_report(existing)[0]


# --- orchestration ----------------------------------------------------------
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

    def get_history():
        history = load_historical_file(historical_file)
        return None if history is None else clean_report(history)[0]

    get_history = memoize(get_history)
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
    write_atomically(report_path, lambda tmp: Path(tmp).write_text(render_report(summaries, now, problems)))
    logger.info("Saved %s", report_path)
    logger.info("Pipeline finished: %d symbols updated, %d problems", len(summaries), len(problems))
    return 1 if problems else 0


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
