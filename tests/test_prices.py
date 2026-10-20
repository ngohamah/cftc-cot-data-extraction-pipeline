import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import config
from cot_pipeline import prices


def daily_prices(start="1999-06-01", days=3000, seed=0):
    """Business-day closes following a random walk (tidy layout, like the saved file)."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start, periods=days)
    close = 300 * np.exp(np.cumsum(rng.normal(0, 0.01, days)))
    return pd.DataFrame({"date": dates, "open": close, "high": close, "low": close, "close": close, "volume": 0})


def yahoo_layout(frame, ticker="GC=F"):
    """The same prices as yfinance returns them: date index and (field, ticker) column labels."""
    renamed = frame.set_index("date").rename(columns=str.title).rename_axis("Date")
    renamed["Adj Close"] = renamed["Close"]
    renamed.columns = pd.MultiIndex.from_product([renamed.columns, [ticker]], names=["Price", "Ticker"])
    return renamed


def test_tidy_prices_flattens_yahoo_columns_and_drops_bad_rows():
    frame = daily_prices(days=5)
    frame.loc[1, "close"] = np.nan
    frame.loc[2, "close"] = 0
    tidy = prices.tidy_prices(yahoo_layout(pd.concat([frame, frame.tail(1)])))
    assert list(tidy.columns) == config.PRICE_COLUMNS
    assert len(tidy) == 3
    assert tidy["date"].is_monotonic_increasing


def test_tidy_prices_requires_close():
    with pytest.raises(ValueError, match="missing"):
        prices.tidy_prices(yahoo_layout(daily_prices(days=3)).drop(columns="Close", level=0))


@pytest.mark.parametrize(
    "downloader, message",
    [(lambda ticker, start: pd.DataFrame(), "no rows"), (lambda ticker, start: 1 / 0, "failed")],
)
def test_download_prices_reports_failures(downloader, message):
    with pytest.raises(prices.PriceDownloadError, match=message):
        prices.download_prices("GC=F", downloader=downloader)


def test_read_saved_prices_validates_columns(tmp_path):
    path = tmp_path / "prices.csv"
    daily_prices(days=3).drop(columns="close").to_csv(path, index=False)
    with pytest.raises(ValueError, match="close"):
        prices.read_saved_prices(path)


def weekly_features(weeks=200, start="2000-01-04"):
    """Tuesday report dates with a net-share series (as build_features would give)."""
    rng = np.random.default_rng(3)
    return pd.DataFrame(
        {"date": pd.date_range(start, periods=weeks, freq="7D"), "net_share": rng.normal(0.3, 0.05, weeks)}
    )


def test_add_price_features_uses_report_day_close_and_waits_for_publication():
    """Close is the as-of Tuesday's; the forward return starts after Friday's release, not on Tuesday."""
    daily = daily_prices()
    result = prices.add_price_features(weekly_features(), daily)
    week = result.iloc[60]
    by_date = daily.set_index("date")["close"]
    assert week["close"] == pytest.approx(by_date[week["date"]])
    entry_day = week["date"] + pd.Timedelta(days=config.REPORT_DAYS_BEFORE_RELEASE + 1)  # the Saturday after
    entry = by_date[by_date.index >= entry_day].iloc[0]  # Monday's close
    exit_ = by_date[by_date.index >= entry_day + pd.Timedelta(weeks=config.FORWARD_HORIZON_WEEKS)].iloc[0]
    assert week["forward_return"] == pytest.approx(exit_ / entry - 1)
    assert result["price_pct_3y"].dropna().between(0, 1).all()


def test_add_price_features_leaves_gaps_where_prices_are_missing():
    """Weeks before the price history get no close; weeks too recent for a full 8 weeks get no forward return."""
    features = weekly_features()
    daily = daily_prices(start="2000-06-01")
    daily = daily[daily["date"] <= features["date"].iloc[-1]]
    result = prices.add_price_features(features, daily)
    assert result.loc[result["date"] < "2000-05-27", "close"].isna().all()
    assert result["forward_return"].tail(config.FORWARD_HORIZON_WEEKS).isna().all()
    assert result["close"].iloc[-1] == pytest.approx(daily["close"].iloc[-1])


def test_lead_lag_finds_a_planted_lag():
    """If speculators copy gold's move from two weeks earlier, the peak shows at lag -2."""
    rng = np.random.default_rng(5)
    gold = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.02, 400))))
    net_change = gold.pct_change().shift(2).fillna(0)
    features = pd.DataFrame({"close": gold, "net_share": net_change.cumsum()})
    lead_lag = prices.lead_lag_correlations(features, max_weeks=4)
    assert lead_lag.loc[lead_lag["correlation"].idxmax(), "lag_weeks"] == -2
    assert lead_lag.loc[lead_lag["lag_weeks"] > 0, "correlation"].abs().max() < 0.2


def test_fetch_script_saves_once_and_reuses(tmp_path, monkeypatch):
    """The download happens once; a second run reads the saved file without contacting Yahoo."""
    path = Path(__file__).resolve().parents[1] / "scripts" / "fetch_prices.py"
    spec = importlib.util.spec_from_file_location("fetch_prices", path)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    calls = []

    def fake_download(ticker):
        calls.append(ticker)
        return yahoo_layout(daily_prices(days=10))

    monkeypatch.setattr(script, "download_prices", fake_download)
    monkeypatch.setattr(script.config, "PRICE_FILE", tmp_path / "gold.csv")
    monkeypatch.setattr(script.config, "REGIME_LOG_FILE", tmp_path / "regimes.log")
    assert script.main([]) == 0
    assert script.main([]) == 0
    assert calls == [config.PRICE_TICKER]
    assert len(prices.read_saved_prices(tmp_path / "gold.csv")) == 10
