import numpy as np
import pandas as pd
import pytest

import config
from cot_pipeline import big_moves, prices


def weekly_frame(weeks=600, seed=0):
    """Weekly reports with prices whose jumpiness switches between calm and wild spells, so jumpiness is a real
    clue to the size of the next move; the COT columns are pure noise."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2001-01-02", periods=weeks, freq="7D")
    spread = np.where((np.arange(weeks) // 40) % 2 == 0, 0.005, 0.04)
    close = 1000 * np.exp(np.cumsum(rng.normal(0, spread)))
    daily = pd.DataFrame({"date": dates, "close": close})
    # one price per day: copy each Tuesday close forward to the rest of its week
    daily = (
        daily.set_index("date")
        .reindex(pd.date_range(dates[0], dates[-1] + pd.Timedelta(days=6)))
        .ffill()
        .rename_axis("date")
        .reset_index()
    )
    features = pd.DataFrame(
        {
            "date": dates,
            "close": close,
            "return_13w": pd.Series(close).pct_change(13).to_numpy(),
            "net_flow_4w": rng.normal(0, 0.05, weeks),
            "oi_growth_4w": rng.normal(0, 0.05, weeks),
            "cot_index": rng.uniform(0, 1, weeks),
        }
    )
    return features, daily


def test_add_move_columns_flags_the_largest_fifth_and_starts_after_publication():
    features, daily = weekly_frame()
    frame, threshold = big_moves.add_move_columns(features, daily)
    known = frame.dropna(subset=[big_moves.MOVE_COLUMN])
    assert known[big_moves.BIG_COLUMN].astype(bool).mean() == pytest.approx(1 - config.BIG_MOVE_QUANTILE, abs=0.01)
    assert (known.loc[known[big_moves.BIG_COLUMN].astype(bool), big_moves.MOVE_COLUMN].abs() >= threshold).all()
    entry_day = frame["date"].iloc[10] + pd.Timedelta(days=config.REPORT_DAYS_BEFORE_RELEASE + 1)
    by_date = daily.set_index("date")["close"]
    entry = by_date[entry_day]
    exit_ = by_date[entry_day + pd.Timedelta(weeks=config.BIG_MOVE_WEEKS)]
    assert frame[big_moves.MOVE_COLUMN].iloc[10] == pytest.approx(exit_ / entry - 1)
    assert frame[big_moves.MOVE_COLUMN].tail(config.BIG_MOVE_WEEKS).isna().all()


def test_clue_summary_finds_the_planted_clue_only():
    features, daily = weekly_frame()
    frame = big_moves.usable_weeks(big_moves.add_move_columns(features, daily)[0])
    summary = big_moves.clue_summary(frame).set_index("clue")
    assert summary.loc[big_moves.VOLATILITY_CLUE, "reliable"]
    jumpy = summary.loc[big_moves.VOLATILITY_CLUE]
    assert jumpy["chance_highest_fifth"] > 3 * jumpy["chance_lowest_fifth"]
    noise = summary.drop(index=[big_moves.VOLATILITY_CLUE, "How strong gold's recent trend is (13 weeks, up or down)"])
    assert not noise["reliable"].any()


def test_clue_table_and_direction_summary_shapes():
    features, daily = weekly_frame()
    frame = big_moves.usable_weeks(big_moves.add_move_columns(features, daily)[0])
    table = big_moves.clue_table(frame, frame["cot_index"])
    assert len(table) == config.CLUE_GROUPS
    assert table["weeks"].sum() == len(frame)
    direction, share_up, count = big_moves.direction_summary(frame)
    assert count == int(frame[big_moves.BIG_COLUMN].sum())
    assert 0 <= share_up <= 1
    assert len(direction) == 3


def test_close_on_or_after_keeps_input_order():
    daily = pd.DataFrame({"date": pd.to_datetime(["2020-01-01", "2020-01-03"]), "close": [1.0, 2.0]})
    dates = pd.to_datetime(["2020-01-02", "2020-01-01", "2020-02-01"])
    result = prices.close_on_or_after(daily, dates)
    assert result[0] == 2.0 and result[1] == 1.0 and np.isnan(result[2])
