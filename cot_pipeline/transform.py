"""Transform (pure functions): clean reports, split by symbol, merge and add net positions.

Symbol data is kept oldest-first so each run only has to append the newest weeks.
"""

import pandas as pd

import config

KEY_COLUMNS = [config.MARKET_COL, config.DATE_COL]


def missing_columns(dataframe, required=config.SPECIAL_COLUMNS):
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
    return dataframe[config.DATE_COL].is_monotonic_increasing


def has_duplicate_records(dataframe):
    return dataframe.duplicated(subset=KEY_COLUMNS).any()


def add_net_positions(dataframe):
    """Sort oldest-first and add Net Positions and Change Net Positions (vs the previous week)."""
    ordered = sort_oldest_first(dataframe)
    net = ordered[config.LONG_COL] - ordered[config.SHORT_COL]
    return ordered.assign(**{config.NET_COL: net, config.NET_CHANGE_COL: net.diff()})


def merge_symbol_data(frames):
    """Combine frames (oldest source first); later frames win on repeated reports.

    Returns (merged_frame, duplicate_row_count).
    """
    combined = pd.concat([f[config.SPECIAL_COLUMNS] for f in frames if f is not None], ignore_index=True)
    deduped = combined.drop_duplicates(subset=KEY_COLUMNS, keep="last")
    return add_net_positions(deduped)[config.DATA_COLUMNS], len(combined) - len(deduped)


def split_incoming(existing, incoming):
    """Split incoming rows against saved ones.

    Returns (new_rows, revised_count): new_rows are reports not saved yet; revised_count is how
    many already-saved reports arrived with different values (the CFTC occasionally corrects a week).
    """
    incoming = incoming[config.SPECIAL_COLUMNS].drop_duplicates(subset=KEY_COLUMNS, keep="last")
    saved = existing[config.SPECIAL_COLUMNS].drop_duplicates(subset=KEY_COLUMNS, keep="last")
    joined = incoming.merge(saved, on=KEY_COLUMNS, how="left", suffixes=("", "_saved"), indicator=True)
    is_new = (joined["_merge"] == "left_only").to_numpy()
    matched = joined[~is_new]
    differs = pd.concat(
        [
            ~((matched[c] == matched[f"{c}_saved"]) | (matched[c].isna() & matched[f"{c}_saved"].isna()))
            for c in config.NUMERIC_COLUMNS
        ],
        axis=1,
    ).any(axis=1)
    return incoming[is_new].reset_index(drop=True), int(differs.sum())


def extend_with_net_positions(existing, new_rows):
    """Net positions for new_rows, continuing from the latest saved week in existing."""
    anchor = sort_oldest_first(existing[config.SPECIAL_COLUMNS]).iloc[[-1]]
    extended = add_net_positions(pd.concat([anchor, new_rows[config.SPECIAL_COLUMNS]], ignore_index=True))
    return extended.iloc[1:][config.DATA_COLUMNS].reset_index(drop=True)


def rewrite_reason(saved_columns, existing, new_rows):
    """Why a saved file can't simply be appended to, or None if appending is safe."""
    if list(saved_columns) != config.DATA_COLUMNS:
        return "column layout differs from the expected one"
    if has_duplicate_records(existing):
        return "file contains duplicate records"
    if not is_oldest_first(existing):
        return "converting to oldest-first order"
    if len(new_rows) and new_rows[config.DATE_COL].min() <= existing[config.DATE_COL].max():
        return "new records are older than the latest saved week"
    return None
