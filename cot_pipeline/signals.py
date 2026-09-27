"""Signal engineering (pure): change in net positions vs change in open interest."""

import numpy as np
import pandas as pd

import config


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
