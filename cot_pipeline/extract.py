"""Extract: download CFTC yearly reports once, save them as batches, and load them back."""

import io
import logging
import zipfile

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import config
from cot_pipeline.storage import write_bytes

logger = logging.getLogger(__name__)


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
            write_bytes(response.content, path)
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


def historical_file_path(raw_dir):
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
