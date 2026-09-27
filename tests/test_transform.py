import pandas as pd
import pytest
from helpers import GOLD, PESO, report

import config
from cot_pipeline.transform import (
    clean_report,
    extend_with_net_positions,
    merge_symbol_data,
    rewrite_reason,
    rows_for_symbol,
    split_incoming,
)


def test_clean_report_filters_markets_and_unifies_names():
    """Unknown markets are dropped and renamed markets are unified."""
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
    """Space-padded numbers are parsed and rows with unreadable dates are dropped."""
    raw = report([(PESO, "2024-01-02", 10, 5, 1), (PESO, "not a date", 1, 1, 1)])
    raw[config.OPEN_INTEREST_CHANGE_COL] = ["   -42", "1"]
    cleaned, dropped = clean_report(raw)
    assert dropped == 1
    assert cleaned[config.OPEN_INTEREST_CHANGE_COL].tolist() == [-42]


def test_clean_report_rejects_missing_columns():
    """A report without the required columns raises ValueError."""
    with pytest.raises(ValueError, match="missing required columns"):
        clean_report(pd.DataFrame({config.MARKET_COL: [PESO]}))


def test_every_configured_market_maps_to_a_symbol():
    """Every configured market name (after unification) belongs to a symbol."""
    unified = [config.MARKET_NAME_REPLACEMENTS.get(mx, mx) for mx in config.MARKETS_AND_EXCHANGES]
    assert [mx for mx in unified if not any(sym in mx for sym in config.SYMBOL_NAMES)] == []


def test_merge_symbol_data_dedups_and_computes_net_positions_oldest_first():
    """Merging keeps the newest copy of repeated weeks, sorts oldest-first and computes net positions."""
    old = report([(PESO, "2024-01-02", 10, 5, 0), (PESO, "2024-01-09", 20, 5, 0)])
    new = report([(PESO, "2024-01-09", 30, 5, 0), (PESO, "2024-01-16", 25, 5, 0)])
    merged, duplicates = merge_symbol_data([None, old, new])
    assert duplicates == 1
    assert merged[config.DATE_COL].tolist() == ["2024-01-02", "2024-01-09", "2024-01-16"]
    assert merged[config.NET_COL].tolist() == [5, 25, 20]  # newer report wins for 2024-01-09
    assert pd.isna(merged[config.NET_CHANGE_COL].iloc[0])
    assert merged[config.NET_CHANGE_COL].tolist()[1:] == [20, -5]
    assert list(merged.columns) == config.DATA_COLUMNS


def test_split_incoming_returns_only_unsaved_records_and_counts_revisions():
    """Only unsaved weeks are returned as new; changed saved weeks are counted as revisions."""
    saved = report([(PESO, "2024-01-02", 10, 5, 0), (PESO, "2024-01-09", 20, 5, 0)])
    incoming = report([(PESO, "2024-01-02", 10, 5, 0), (PESO, "2024-01-09", 99, 5, 0), (PESO, "2024-01-16", 1, 1, 0)])
    new_rows, revised = split_incoming(saved, incoming)
    assert new_rows[config.DATE_COL].tolist() == ["2024-01-16"]
    assert revised == 1  # 2024-01-09 arrived with a different long position


def test_extend_with_net_positions_continues_from_last_saved_week():
    """Net position changes for new weeks continue from the last saved week."""
    saved = merge_symbol_data([report([(PESO, "2024-01-02", 10, 5, 0), (PESO, "2024-01-09", 20, 5, 0)])])[0]
    new_rows = report([(PESO, "2024-01-16", 25, 5, 0), (PESO, "2024-01-23", 12, 5, 0)])
    extended = extend_with_net_positions(saved, new_rows)
    assert extended[config.DATE_COL].tolist() == ["2024-01-16", "2024-01-23"]
    assert extended[config.NET_CHANGE_COL].tolist() == [5, -13]  # 20 - 15, then 7 - 20
    assert list(extended.columns) == config.DATA_COLUMNS


def test_rewrite_reason():
    """Each unsafe-to-append condition gives a reason; a clean append gives None."""
    saved = merge_symbol_data([report([(PESO, "2024-01-02", 10, 5, 0), (PESO, "2024-01-09", 20, 5, 0)])])[0]
    later = report([(PESO, "2024-01-16", 1, 1, 0)])
    earlier = report([(PESO, "2023-12-26", 1, 1, 0)])
    assert rewrite_reason(saved.columns, saved, later) is None
    assert "older" in rewrite_reason(saved.columns, saved, earlier)
    assert "oldest-first" in rewrite_reason(saved.columns, saved.iloc[::-1], later)
    assert "column layout" in rewrite_reason(saved.columns[:-1], saved, later)
    assert "duplicate" in rewrite_reason(saved.columns, pd.concat([saved, saved.iloc[[-1]]]), later)


def test_rows_for_symbol_matches_all_name_variants():
    """Only rows whose market name contains the symbol are selected."""
    frame = report([(PESO, "2024-01-02", 1, 1, 1), (GOLD, "2024-01-02", 1, 1, 1)])
    assert rows_for_symbol(frame, "GOLD")[config.MARKET_COL].tolist() == [GOLD]
