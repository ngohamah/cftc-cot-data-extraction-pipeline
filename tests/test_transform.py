import pandas as pd
import pytest
from helpers import GOLD, PESO, report

import config
from cot_pipeline.transform import clean_report, merge_symbol_data, rows_for_symbol


def test_clean_report_filters_markets_and_unifies_names():
    raw = report(
        [
            (PESO, "2024-01-02", 10, 5, 1),
            ("DOW JONES INDUSTRIAL AVERAGE - CHICAGO BOARD OF TRADE", "2024-01-02", 1, 1, 1),
            ("SOMETHING ELSE - NOWHERE", "2024-01-02", 1, 1, 1),
        ]
    )
    cleaned, dropped = clean_report(raw)
    assert dropped == 0
    assert list(cleaned[config.MARKET_COL]) == [PESO, "DJIA Consolidated - CHICAGO BOARD OF TRADE"]


def test_clean_report_parses_padded_numbers_and_drops_bad_dates():
    raw = report([(PESO, "2024-01-02", 10, 5, 1), (PESO, "not a date", 1, 1, 1)])
    raw[config.OPEN_INTEREST_CHANGE_COL] = ["   -42", "1"]
    cleaned, dropped = clean_report(raw)
    assert dropped == 1
    assert cleaned[config.OPEN_INTEREST_CHANGE_COL].tolist() == [-42]


def test_clean_report_rejects_missing_columns():
    with pytest.raises(ValueError, match="missing required columns"):
        clean_report(pd.DataFrame({config.MARKET_COL: [PESO]}))


def test_every_configured_market_maps_to_a_symbol():
    unified = [config.MARKET_NAME_REPLACEMENTS.get(mx, mx) for mx in config.MARKETS_AND_EXCHANGES]
    assert [mx for mx in unified if not any(sym in mx for sym in config.SYMBOL_NAMES)] == []


def test_merge_symbol_data_dedups_and_computes_net_positions():
    old = report([(PESO, "2024-01-02", 10, 5, 0), (PESO, "2024-01-09", 20, 5, 0)])
    new = report([(PESO, "2024-01-09", 30, 5, 0), (PESO, "2024-01-16", 25, 5, 0)])
    merged, duplicates = merge_symbol_data([None, old, new])
    assert duplicates == 1
    assert merged[config.DATE_COL].tolist() == ["2024-01-16", "2024-01-09", "2024-01-02"]
    assert merged[config.NET_COL].tolist() == [20, 25, 5]  # newer report wins for 2024-01-09
    assert merged[config.NET_CHANGE_COL].tolist()[:2] == [-5, 20]
    assert pd.isna(merged[config.NET_CHANGE_COL].iloc[-1])
    assert list(merged.columns) == config.DATA_COLUMNS


def test_rows_for_symbol_matches_all_name_variants():
    frame = report([(PESO, "2024-01-02", 1, 1, 1), (GOLD, "2024-01-02", 1, 1, 1)])
    assert rows_for_symbol(frame, "GOLD")[config.MARKET_COL].tolist() == [GOLD]
