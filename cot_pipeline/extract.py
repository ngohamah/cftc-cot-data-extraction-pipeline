"""Extract: download CFTC yearly reports only when needed, save them as batches in raw/, and load them back."""

import datetime as dt
import io
import logging
import zipfile
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import config
from cot_pipeline.storage import write_bytes

logger = logging.getLogger(__name__)


def raw_zip_path(year, raw_dir):
    """Path of the saved CFTC zip for year inside raw_dir (raw/legacy_fut_<year>.zip)."""
    return raw_dir / f"legacy_fut_{year}.zip"


def latest_released_report_date(now):
    """As-of date (Tuesday) of the newest COT report the CFTC should have published by now (tz-aware)."""
    local = now.astimezone(ZoneInfo(config.RELEASE_TIMEZONE))
    days_since_release_day = (local.weekday() - config.RELEASE_WEEKDAY) % 7
    release_day = local.date() - dt.timedelta(days=days_since_release_day)
    if days_since_release_day == 0 and local.time() < dt.time(config.RELEASE_HOUR, config.RELEASE_MINUTE):
        release_day -= dt.timedelta(days=7)
    return release_day - dt.timedelta(days=config.REPORT_DAYS_BEFORE_RELEASE)


def last_report_day_of_year(year):
    """Last Tuesday of year: the usual as-of date of a year's final weekly report."""
    dec_31 = dt.date(year, 12, 31)
    report_weekday = (config.RELEASE_WEEKDAY - config.REPORT_DAYS_BEFORE_RELEASE) % 7
    return dec_31 - dt.timedelta(days=(dec_31.weekday() - report_weekday) % 7)


def expected_latest_report(year, latest_released):
    """Latest as-of date a complete copy of year's file should contain, or None if nothing is published yet."""
    if year > latest_released.year:
        return None
    return min(last_report_day_of_year(year), latest_released)


def saved_report_latest_date(path):
    """Newest as-of date in a saved yearly zip, or None if it is missing or unreadable."""
    if not path.exists():
        return None
    try:
        dates = read_report_zip(path, usecols=[config.DATE_COL])[config.DATE_COL]
        return pd.to_datetime(dates).max().date()
    except (zipfile.BadZipFile, StopIteration, ValueError, pd.errors.ParserError):
        return None


def plan_downloads(years, raw_dir, now, refresh=False):
    """Decide per year whether a download is needed: [(year, download?, reason)].

    Years before FIRST_API_YEAR come from FUT86_16.txt, years with no report published yet are skipped,
    and a saved zip is re-downloaded only if it is missing, unreadable, or lacks the latest expected week.
    """
    latest_released = latest_released_report_date(now)
    tolerance = dt.timedelta(days=config.REPORT_DATE_TOLERANCE_DAYS)

    def decide(year):
        if year < config.FIRST_API_YEAR:
            return year, False, f"covered by {config.HISTORICAL_FILENAME}"
        expected = expected_latest_report(year, latest_released)
        if expected is None:
            return year, False, f"no report published for {year} yet, latest release is {latest_released}"
        if refresh:
            return year, True, "--refresh requested"
        path = raw_zip_path(year, raw_dir)
        saved_latest = saved_report_latest_date(path)
        if saved_latest is None:
            return year, True, "saved copy unreadable" if path.exists() else "no saved copy"
        if saved_latest >= expected - tolerance:
            return year, False, f"saved copy is up to date, latest report {saved_latest}"
        return year, True, f"saved copy ends {saved_latest}, report for {expected} expected"

    return [decide(year) for year in years]


def report_years(years, now):
    """Years that have (or should have) a yearly CFTC file: from FIRST_API_YEAR up to the latest release."""
    latest_released = latest_released_report_date(now)
    return [y for y in years if y >= config.FIRST_API_YEAR and expected_latest_report(y, latest_released)]


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
            write_bytes(response.content, path)
            logger.info("Downloaded %s report (%d KB) -> %s", year, len(response.content) // 1024, path)
    return failed


def read_report_zip(path, usecols=None):
    """Read the single .txt report inside a CFTC zip (optionally only usecols)."""
    with zipfile.ZipFile(path) as archive:
        name = next(n for n in archive.namelist() if n.lower().endswith(".txt"))
        with archive.open(name) as handle:
            return pd.read_csv(handle, usecols=usecols, low_memory=False)


def load_saved_reports(years, raw_dir):
    """Load every saved yearly batch; missing/corrupt years are logged and skipped."""

    def load(year):
        """Load one saved year, or None (logged) if its zip is missing or unreadable."""
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


def historical_file_path(raw_dir):
    """Path of the 1986-2016 history file inside raw_dir (raw/FUT86_16.txt)."""
    return raw_dir / config.HISTORICAL_FILENAME


def load_historical_file(path=config.HISTORICAL_FILE):
    """Legacy futures 1986-2016 from the saved file in raw/, or None if it is unavailable."""
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
