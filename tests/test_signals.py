import pandas as pd
import pytest

import config
from cot_pipeline.signals import compute_signals


@pytest.mark.parametrize(
    "net_change, oi_change, expected",
    [
        (5, 3, (1, "Bullish")),
        (5, -3, (4, "Bullish Reversal")),
        (-5, 3, (2, "Bearish")),
        (-5, -3, (3, "Bearish Reversal")),
        (0, 3, (0, "No signal")),
        (float("nan"), 3, (0, "No signal")),
    ],
)
def test_compute_signals(net_change, oi_change, expected):
    """Each combination of net-position and open-interest change maps to its signal code."""
    frame = pd.DataFrame({config.NET_CHANGE_COL: [net_change], config.OPEN_INTEREST_CHANGE_COL: [oi_change]})
    result = compute_signals(frame).iloc[0]
    assert (result["signal"], result["Interpretation"]) == expected
