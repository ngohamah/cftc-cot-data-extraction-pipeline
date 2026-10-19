"""Daily prices: download once from Yahoo Finance, save to disk, then line them up with the weekly COT reports.

download_prices is the only network call (scripts/fetch_prices.py saves its result); everything else is pure
and works on the saved batch.

No peeking ahead: each report shows positions as of a Tuesday but is only published on Friday at 15:30 US
Eastern, after gold futures have closed. So "what gold did next" is measured from the first close after the
release day, never from the Tuesday itself.
"""

import logging

import numpy as np
import pandas as pd

import config

logger = logging.getLogger(__name__)

FORWARD_RETURN_COLUMN = "forward_return"


class PriceDownloadError(RuntimeError):
    """The price download failed or returned no rows."""


def download_prices(ticker=config.PRICE_TICKER, start=config.PRICE_START, downloader=None):
    """Daily prices for ticker in one request, as returned by yfinance (raises PriceDownloadError on failure).

    downloader can be swapped in tests; by default a yfinance download over a session that is closed afterwards.
    """
    if downloader is None:
        downloader = _yahoo_download
    try:
        raw = downloader(ticker, start)
    except Exception as error:  # yfinance and its HTTP client raise many unrelated exception types
        raise PriceDownloadError(f"Download of {ticker} failed: {error}") from error
    if raw is None or raw.empty:
        raise PriceDownloadError(f"Yahoo Finance returned no rows for {ticker} (rate limit or unknown ticker?)")
    return raw


def _yahoo_download(ticker, start):
    """One yfinance request over its own HTTP session, closed when done (imported here: tests never need it)."""
    import yfinance as yf
    from curl_cffi import requests as curl_requests

    session = curl_requests.Session(impersonate="chrome")
    try:
        return yf.download(
            ticker, start=start, interval="1d", auto_adjust=False, progress=False, threads=False, session=session
        )
    finally:
        session.close()


def tidy_prices(raw):
    """yfinance output -> one row per trading day with PRICE_COLUMNS, oldest first; drops unusable rows."""
    frame = raw.copy()
    if isinstance(frame.columns, pd.MultiIndex):  # yfinance labels columns (field, ticker)
        frame.columns = frame.columns.get_level_values(0)
    frame = frame.rename(columns=str.lower).rename_axis("date").reset_index()
    frame["date"] = pd.to_datetime(frame["date"]).dt.tz_localize(None).dt.normalize()
    missing = [c for c in config.PRICE_COLUMNS if c not in frame.columns]
    if missing:
        raise ValueError(f"Price data is missing columns: {missing}")
    usable = frame[config.PRICE_COLUMNS].dropna(subset=["close"])
    usable = usable[usable["close"] > 0].sort_values("date").drop_duplicates(subset="date", keep="last")
    if len(usable) < len(frame):
        logger.warning("Dropped %d price rows with a missing, zero or duplicate close", len(frame) - len(usable))
    return usable.reset_index(drop=True)


def read_saved_prices(path=config.PRICE_FILE):
    """The saved daily price batch (raises FileNotFoundError if it hasn't been downloaded yet)."""
    prices = pd.read_csv(path, parse_dates=["date"])
    missing = [c for c in config.PRICE_COLUMNS if c not in prices.columns]
    if missing:
        raise ValueError(f"{path} is missing columns: {missing}")
    return prices


def _close_on_or_after(daily, dates, max_days=7):
    """First close on or after each date (NaN if none within max_days, e.g. beyond the last saved day)."""
    targets = pd.DataFrame({"target": pd.to_datetime(dates).to_numpy()}).reset_index()
    found = pd.merge_asof(
        targets.sort_values("target"),
        daily.rename(columns={"date": "target"}),
        on="target",
        direction="forward",
        tolerance=pd.Timedelta(days=max_days),
    )
    return found.sort_values("index")["close"].to_numpy()


def add_price_features(features, prices, settings=None):
    """Weekly features plus gold's price on each report date and what it did before and after.

    close: last close on or before the report (as-of) date
    return_4w / return_13w: gold's % change over the last 4 / 13 weeks (the recent trend)
    price_pct_3y: where the price sits in its range of the last 3 years (0 = lowest, 1 = highest)
    forward_return: % change from the first close after the report is published to FORWARD_HORIZON_WEEKS later
    """
    s = {
        "tolerance": config.PRICE_MATCH_TOLERANCE_DAYS,
        "flow": config.FLOW_WINDOW_WEEKS,
        "trend": config.PRICE_TREND_WEEKS,
        "window": config.COT_INDEX_WINDOW_WEEKS,
        "min_weeks": config.COT_INDEX_MIN_WEEKS,
        "horizon": config.FORWARD_HORIZON_WEEKS,
        "release_days": config.REPORT_DAYS_BEFORE_RELEASE,
        **(settings or {}),
    }
    daily = prices[["date", "close"]].sort_values("date")
    merged = pd.merge_asof(
        features.sort_values("date"),
        daily,
        on="date",
        direction="backward",
        tolerance=pd.Timedelta(days=s["tolerance"]),
    ).reset_index(drop=True)
    close = merged["close"]
    rolling = close.rolling(s["window"], min_periods=s["min_weeks"])
    entry_dates = merged["date"] + pd.Timedelta(days=s["release_days"] + 1)
    entry = _close_on_or_after(daily, entry_dates)
    exit_ = _close_on_or_after(daily, entry_dates + pd.Timedelta(weeks=s["horizon"]))
    unmatched = close.isna().sum()
    if unmatched:
        logger.info(
            "%d report weeks have no price within %d days (before the price history starts)", unmatched, s["tolerance"]
        )
    return merged.assign(
        return_4w=close / close.shift(s["flow"]) - 1,
        return_13w=close / close.shift(s["trend"]) - 1,
        price_pct_3y=(close - rolling.min()) / (rolling.max() - rolling.min()),
        **{FORWARD_RETURN_COLUMN: exit_ / entry - 1},
    ).replace([np.inf, -np.inf], np.nan)


def lead_lag_correlations(features, max_weeks=config.LEAD_LAG_WEEKS):
    """Rank correlation between speculators' change in net position in a week and gold's return in a week
    `lag_weeks` away: negative lag = gold's week came first, 0 = same week, positive = gold's week came after.
    Single weeks never overlap, so a non-zero value at a positive lag would mean speculators move ahead of gold."""
    speculator_change = features["net_share"].diff()
    gold_change = features["close"].pct_change(fill_method=None)
    rows = [
        {"lag_weeks": lag, "correlation": speculator_change.corr(gold_change.shift(-lag), method="spearman")}
        for lag in range(-max_weeks, max_weeks + 1)
    ]
    return pd.DataFrame(rows)
