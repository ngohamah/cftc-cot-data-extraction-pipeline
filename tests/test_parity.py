import pandas as pd
from helpers import GOLD, PESO

import config
from cot_pipeline.parity import CODE_COL, compare_year, pipeline_subset, render_parity_report, rows_for_year


def frame(rows, pad_names=False):
    """CFTC-like rows from (market, date, code, long, other) tuples; pad_names mimics the history file."""
    market = f"{config.MARKET_COL} " if pad_names else config.MARKET_COL
    return pd.DataFrame(
        [
            {market: m, config.DATE_COL: d, CODE_COL: c, config.LONG_COL: long, "Other": other}
            for m, d, c, long, other in rows
        ]
    )


ROWS = [(PESO, "2010-01-05", "095741", 10, "x"), (GOLD, "2010-01-05", "088691", 20, "y")]


def test_identical_sources_match_despite_formatting_differences():
    """Padded column names, leading-zero codes and padded numbers still count as identical."""
    history = frame(ROWS, pad_names=True)
    download = frame([(m, d, int(c), f"  {long}", other) for m, d, c, long, other in ROWS])
    result = compare_year(2010, history, download)
    assert result.matches
    assert result.cells_compared == 4 and result.cells_different == 0


def test_differences_are_counted_by_kind():
    """Missing rows, extra rows and differing cells are each reported."""
    history = frame(ROWS + [(PESO, "2010-01-12", "095741", 11, "x")])
    download = frame([ROWS[0], (GOLD, "2010-01-05", "088691", 21, "y"), (PESO, "2010-01-19", "095741", 12, "x")])
    result = compare_year(2010, history, download)
    assert not result.matches
    assert (result.rows_only_in_history, result.rows_only_in_download) == (1, 1)
    assert result.different_by_column == {config.LONG_COL: 1}
    example = result.examples.iloc[0]
    assert (example["history_value"], example["download_value"]) == ("20", "21")


def test_column_and_duplicate_differences_break_parity():
    """A column missing from one source, or repeated rows, is not a match."""
    history = frame(ROWS)
    assert not compare_year(2010, history, history.drop(columns=["Other"])).matches
    assert compare_year(2010, pd.concat([history, history.iloc[[0]]]), history).duplicate_keys_history == 1


def test_rows_for_year_and_pipeline_subset():
    """History rows are split by report year, and the pipeline subset keeps tracked markets only."""
    history = frame(ROWS + [("OTHER - NOWHERE", "2011-01-04", "1", 1, "z")])
    assert len(rows_for_year(history, 2010)) == 2
    assert pipeline_subset(history)[config.MARKET_COL].tolist() == [PESO, GOLD]


def test_render_parity_report_states_verdict_in_plain_language():
    """The report leads with a plain verdict and lists every year."""
    good = compare_year(2010, frame(ROWS), frame(ROWS))
    text = render_parity_report([good], [good], "raw/FUT86_16.txt", pd.Timestamp("2026-09-27"))
    assert "Full match" in text and "| 2010 |" in text
