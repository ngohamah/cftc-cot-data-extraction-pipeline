import pandas as pd
import pytest
from helpers import GOLD, PESO, report

import config
from cot_pipeline.transform import (
    clean_report,
    extend_with_net_positions,
    has_duplicate_records,
    merge_symbol_data,
    one_report_per_week,
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
    merged, duplicates, other_contracts = merge_symbol_data([None, old, new])
    assert duplicates == 1 and other_contracts.empty
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
    assert rewrite_reason(saved, saved, later) is None
    assert "older" in rewrite_reason(saved, saved, earlier)
    assert "oldest-first" in rewrite_reason(saved, saved.iloc[::-1], later)
    assert "column layout" in rewrite_reason(saved.iloc[:, :-1], saved, later)
    doubled = pd.concat([saved, saved.iloc[[-1]]])
    assert "same week" in rewrite_reason(doubled, doubled, later)
    assert "unknown markets or unreadable dates" in rewrite_reason(saved, saved.iloc[1:], later)


def test_rows_for_symbol_matches_all_name_variants():
    """Only rows whose market name contains the symbol are selected."""
    frame = report([(PESO, "2024-01-02", 1, 1, 1), (GOLD, "2024-01-02", 1, 1, 1)])
    assert rows_for_symbol(frame, "GOLD")[config.MARKET_COL].tolist() == [GOLD]


GOLD_CBOT = "GOLD, 100 TROY OZ - CHICAGO BOARD OF TRADE"


def gold_weeks(rows):
    """Report rows from (market, date, long, short, open_interest) tuples."""
    frame = report([(market, date, long, short, 0) for market, date, long, short, _ in rows])
    return frame.assign(**{config.OPEN_INTEREST_COL: [oi for *_, oi in rows]})


def test_has_duplicate_records_flags_two_contracts_in_the_same_week():
    """Two market names with the same date are one week reported twice."""
    frame = gold_weeks([(GOLD, "2008-07-15", 10, 5, 500), (GOLD_CBOT, "2008-07-15", 1, 1, 50)])
    assert has_duplicate_records(frame)
    assert not has_duplicate_records(frame.iloc[[0]])


def test_one_report_per_week_keeps_the_largest_contract():
    """The contract with the largest open interest is kept; the others are returned as dropped."""
    frame = gold_weeks(
        [
            (GOLD_CBOT, "2008-07-15", 1, 1, 50),
            (GOLD, "2008-07-15", 10, 5, 500),
            (GOLD, "2008-07-22", 12, 5, 520),
        ]
    )
    kept, dropped = one_report_per_week(frame)
    assert sorted(kept[config.DATE_COL]) == ["2008-07-15", "2008-07-22"]
    assert set(kept[config.MARKET_COL]) == {GOLD}
    assert dropped[config.MARKET_COL].tolist() == [GOLD_CBOT]


def test_merge_symbol_data_net_change_never_mixes_contracts():
    """Net position changes are computed week to week within the main contract only."""
    frame = gold_weeks(
        [
            (GOLD, "2008-07-15", 10, 5, 500),
            (GOLD_CBOT, "2008-07-22", 100, 1, 50),
            (GOLD, "2008-07-22", 12, 5, 520),
        ]
    )
    merged, duplicates, other_contracts = merge_symbol_data([frame])
    assert duplicates == 0 and len(other_contracts) == 1
    assert merged[config.DATE_COL].tolist() == ["2008-07-15", "2008-07-22"]
    assert merged[config.NET_CHANGE_COL].tolist()[1] == 2  # 7 - 5, not 99 - 5


def test_split_incoming_returns_one_report_per_new_week():
    """New weeks reported by several contracts come back once, from the main contract."""
    saved = gold_weeks([(GOLD, "2008-07-08", 10, 5, 500)])
    incoming = gold_weeks([(GOLD, "2008-07-15", 10, 5, 500), (GOLD_CBOT, "2008-07-15", 1, 1, 50)])
    new_rows, revised = split_incoming(saved, incoming)
    assert new_rows[config.MARKET_COL].tolist() == [GOLD] and revised == 0
