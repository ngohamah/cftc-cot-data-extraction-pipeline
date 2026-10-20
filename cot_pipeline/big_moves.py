"""Big price moves: can anything known on report day warn that a big gold move (up or down) is coming?

A "big move" is gold's change over the BIG_MOVE_WEEKS after a report is published that ranks among the
largest (1 - BIG_MOVE_QUANTILE) of all such changes by size, whichever the direction. Each possible clue is
split into fifths (from lowest to highest) and we compare how often a big move followed in each fifth.

Pure functions on the weekly frame from prices.add_price_features (optionally with regimes).
"""

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

import config
from cot_pipeline.prices import close_on_or_after

MOVE_COLUMN = "move_next"
BIG_COLUMN = "big_move"

# clue name -> how to compute it from the weekly frame (all known by the time the report is published)
CLUES = {
    "How jumpy gold has been (last 13 weeks)": lambda f: f["volatility"],
    "How strong gold's recent trend is (13 weeks, up or down)": lambda f: f["return_13w"].abs(),
    "How much speculators just bought or sold (4 weeks)": lambda f: f["net_flow_4w"].abs(),
    "How fast open interest is changing (4 weeks)": lambda f: f["oi_growth_4w"].abs(),
    "How extreme speculators' positioning is (3-yr range)": lambda f: (f["cot_index"] - 0.5).abs(),
}
VOLATILITY_CLUE = "How jumpy gold has been (last 13 weeks)"
POSITIONING_CLUE = "Speculators' positioning (3-yr percentile)"


def add_move_columns(features, prices, weeks=config.BIG_MOVE_WEEKS, quantile=config.BIG_MOVE_QUANTILE):
    """Add gold's recent jumpiness, its move over the `weeks` after publication, and whether that move was big.

    volatility: spread (standard deviation) of gold's weekly % moves over the last VOLATILITY_WEEKS, yearly terms
    move_next: % change from the first close after publication to `weeks` later
    big_move: True when the size of move_next is in the top (1 - quantile) of all weeks
    Returns (frame, threshold) where threshold is the size that counts as big.
    """
    daily = prices[["date", "close"]].sort_values("date")
    entry_dates = features["date"] + pd.Timedelta(days=config.REPORT_DAYS_BEFORE_RELEASE + 1)
    entry = close_on_or_after(daily, entry_dates)
    exit_ = close_on_or_after(daily, entry_dates + pd.Timedelta(weeks=weeks))
    weekly_moves = features["close"].pct_change(fill_method=None)
    move = pd.Series(exit_ / entry - 1, index=features.index)
    threshold = move.abs().quantile(quantile)
    frame = features.assign(
        volatility=weekly_moves.rolling(config.VOLATILITY_WEEKS).std() * np.sqrt(52),
        **{MOVE_COLUMN: move, BIG_COLUMN: (move.abs() >= threshold).where(move.notna())},
    )
    return frame, float(threshold)


def usable_weeks(frame):
    """Weeks with a known next move and every clue."""
    clues = pd.DataFrame({name: fn(frame) for name, fn in CLUES.items()})
    keep = frame[MOVE_COLUMN].notna() & clues.notna().all(axis=1)
    return frame[keep].reset_index(drop=True)


def clue_table(frame, clue, groups=config.CLUE_GROUPS):
    """For each fifth of a clue (lowest to highest): weeks, chance a big move followed, and how many of those
    big moves were up."""
    group = pd.qcut(clue.rank(method="first"), groups, labels=range(1, groups + 1))
    big = frame[BIG_COLUMN].astype(bool)
    up_when_big = (frame[MOVE_COLUMN] > 0).where(big)
    table = pd.DataFrame({"group": group, "big": big, "up_when_big": up_when_big}).groupby("group", observed=True)
    return table.agg(weeks=("big", "size"), big_move_chance=("big", "mean"), share_up=("up_when_big", "mean"))


def clue_summary(frame, weeks=config.BIG_MOVE_WEEKS, groups=config.CLUE_GROUPS):
    """One row per clue: chance of a big move in its lowest and highest fifth, and a rank-correlation test of
    clue vs size of the next move on non-overlapping weeks (p below 0.05 = a reliable clue)."""
    sample = frame.iloc[::weeks]

    def summarise(name, fn):
        table = clue_table(frame, fn(frame), groups)
        values = fn(sample)
        # a clue that never changes can't be tested (and isn't a clue)
        correlation, p_value = spearmanr(values, sample[MOVE_COLUMN].abs()) if values.nunique() > 1 else (np.nan, 1.0)
        return {
            "clue": name,
            "chance_lowest_fifth": table["big_move_chance"].iloc[0],
            "chance_highest_fifth": table["big_move_chance"].iloc[-1],
            "correlation_with_move_size": correlation,
            "p_value": p_value,
            "reliable": p_value < 0.05,
            "weeks_tested": len(sample),
        }

    return pd.DataFrame([summarise(name, fn) for name, fn in CLUES.items()])


def direction_summary(frame):
    """Of the big moves, how many were up, and does anything known on report day hint at the direction?
    Rank correlation between each clue (signed) and the direction of the big move (+1 up, -1 down)."""
    big = frame[frame[BIG_COLUMN].astype(bool)]
    direction = np.sign(big[MOVE_COLUMN])
    signed = {
        "Speculators' positioning (3-yr percentile)": big["cot_index"],
        "Gold's recent trend (13 weeks)": big["return_13w"],
        "What speculators just did (4 weeks)": big["net_flow_4w"],
    }
    rows = [
        {"clue": name, "correlation_with_direction": spearmanr(values, direction)[0]} for name, values in signed.items()
    ]
    return pd.DataFrame(rows), float((direction > 0).mean()), len(big)
