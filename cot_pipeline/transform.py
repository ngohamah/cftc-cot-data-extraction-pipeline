"""Transform (pure functions): clean reports, split by symbol, merge and add net positions.

Symbol data is kept oldest-first so each run only has to append the newest weeks.
"""

import pandas as pd

import config

KEY_COLUMNS = [config.MARKET_COL, config.DATE_COL]


def missing_columns(dataframe, required=config.SPECIAL_COLUMNS):
    """Columns from required that dataframe doesn't have (empty list if none are missing)."""
    return [c for c in required if c not in dataframe.columns]


def clean_report(dataframe):
    """Keep our markets and columns, unify names, parse numbers and dates.

    Returns (cleaned_frame, dropped_row_count). Rows with unreadable dates are dropped.
    """
    missing = missing_columns(dataframe)
    if missing:
        raise ValueError(f"Report is missing required columns: {missing}")
    selected = dataframe.loc[dataframe[config.MARKET_COL].isin(config.MARKETS_AND_EXCHANGES), config.SPECIAL_COLUMNS]
    numeric = {c: pd.to_numeric(selected[c].astype(str).str.strip(), errors="coerce") for c in config.NUMERIC_COLUMNS}
    cleaned = selected.assign(
        **{config.MARKET_COL: selected[config.MARKET_COL].replace(config.MARKET_NAME_REPLACEMENTS)},
        **{config.DATE_COL: pd.to_datetime(selected[config.DATE_COL], errors="coerce").dt.strftime("%Y-%m-%d")},
        **numeric,
    )
    valid = cleaned.dropna(subset=[config.DATE_COL])
    return valid, len(cleaned) - len(valid)


def rows_for_symbol(dataframe, symbol, markets=config.MARKETS_AND_EXCHANGES):
    """Rows whose market name belongs to symbol."""
    names = [mx for mx in markets if symbol in mx]
    return dataframe[dataframe[config.MARKET_COL].isin(names)]


def sort_oldest_first(dataframe):
    """Oldest week first; same-day rows keep the pairing of the original newest-first order."""
    newest_first = dataframe.sort_values(by=config.DATE_COL, ascending=False, kind="stable")
    return newest_first.iloc[::-1].reset_index(drop=True)


def is_oldest_first(dataframe):
    """True if rows are in ascending date order (same-day rows allowed)."""
    return dataframe[config.DATE_COL].is_monotonic_increasing


def has_duplicate_records(dataframe):
    """True if any week appears more than once.

    A symbol's file holds one report per week. Two rows with the same date are duplicates even when
    their market names differ (e.g. COMEX gold and CBOT 100 oz gold): the signal files have no market
    column, and net position changes would be computed between two different contracts.
    """
    return dataframe.duplicated(subset=[config.DATE_COL]).any()


def one_report_per_week(dataframe):
    """Keep one contract per week: the one with the largest open interest (the symbol's main contract).

    Several contracts of one symbol were reported in the same week in some periods (e.g. COMEX and CBOT
    silver until 2007, NASDAQ-100 Consolidated and its stock index part in 2010-2015).
    Returns (kept_rows, dropped_rows); row order is not preserved.
    """
    by_size = dataframe.sort_values(by=config.OPEN_INTEREST_COL, ascending=False, kind="stable", na_position="last")
    is_main = ~by_size.duplicated(subset=[config.DATE_COL], keep="first")
    return by_size[is_main], by_size[~is_main]


def add_net_positions(dataframe):
    """Sort oldest-first and add Net Positions and Change Net Positions (vs the previous week)."""
    ordered = sort_oldest_first(dataframe)
    net = ordered[config.LONG_COL] - ordered[config.SHORT_COL]
    return ordered.assign(**{config.NET_COL: net, config.NET_CHANGE_COL: net.diff()})


def merge_symbol_data(frames):
    """Combine frames (oldest source first) into one report per week; later frames win on repeated reports.

    Returns (merged_frame, duplicate_row_count, other_contract_rows): duplicate_row_count counts repeated
    reports of the same market and week; other_contract_rows are smaller contracts reported in a week
    that already has the main contract (see one_report_per_week).
    """
    combined = pd.concat([f[config.SPECIAL_COLUMNS] for f in frames if f is not None], ignore_index=True)
    deduped = combined.drop_duplicates(subset=KEY_COLUMNS, keep="last")
    weekly, other_contracts = one_report_per_week(deduped)
    return add_net_positions(weekly)[config.DATA_COLUMNS], len(combined) - len(deduped), other_contracts


def split_incoming(existing, incoming):
    """Split incoming rows against saved ones, by week.

    Returns (new_rows, revised_count): new_rows are weeks not saved yet (one report per week, oldest
    first); revised_count is how many already-saved weeks arrived with different values or a different
    main contract (the CFTC occasionally corrects a week).
    """
    deduped = incoming[config.SPECIAL_COLUMNS].drop_duplicates(subset=KEY_COLUMNS, keep="last")
    weekly = sort_oldest_first(one_report_per_week(deduped)[0])
    saved = existing[config.SPECIAL_COLUMNS].drop_duplicates(subset=[config.DATE_COL], keep="last")
    joined = weekly.merge(saved, on=config.DATE_COL, how="left", suffixes=("", "_saved"), indicator=True)
    is_new = (joined["_merge"] == "left_only").to_numpy()
    matched = joined[~is_new]
    compared = [config.MARKET_COL, *config.NUMERIC_COLUMNS]
    differs = pd.concat(
        [
            ~((matched[c] == matched[f"{c}_saved"]) | (matched[c].isna() & matched[f"{c}_saved"].isna()))
            for c in compared
        ],
        axis=1,
    ).any(axis=1)
    return weekly[is_new].reset_index(drop=True), int(differs.sum())


def extend_with_net_positions(existing, new_rows):
    """Net positions for new_rows, continuing from the latest saved week in existing."""
    anchor = sort_oldest_first(existing[config.SPECIAL_COLUMNS]).iloc[[-1]]
    extended = add_net_positions(pd.concat([anchor, new_rows[config.SPECIAL_COLUMNS]], ignore_index=True))
    return extended.iloc[1:][config.DATA_COLUMNS].reset_index(drop=True)


def may_lack_history(existing):
    """True if the saved file starts at/after the first API year, i.e. 1986-2016 history may be missing."""
    return existing.empty or existing[config.DATE_COL].min() >= f"{config.FIRST_API_YEAR}-01-01"


def history_to_backfill(existing, history_rows):
    """History rows older than the earliest saved week (they belong before the saved data)."""
    earliest = existing[config.DATE_COL].min() if len(existing) else "9999-12-31"
    return history_rows[history_rows[config.DATE_COL] < earliest]


def rewrite_reason(saved, existing, new_rows):
    """Why a saved file can't simply be appended to, or None if appending is safe.

    saved is the file as read from disk; existing is the same rows after clean_report.
    """
    if list(saved.columns) != config.DATA_COLUMNS:
        return "column layout differs from the expected one"
    if len(existing) != len(saved):
        return f"file contains {len(saved) - len(existing)} rows with unknown markets or unreadable dates"
    if has_duplicate_records(existing):
        return "file contains more than one record for the same week"
    if not is_oldest_first(existing):
        return "converting to oldest-first order"
    if len(new_rows) and new_rows[config.DATE_COL].min() <= existing[config.DATE_COL].max():
        return "new records are older than the latest saved week"
    return None
