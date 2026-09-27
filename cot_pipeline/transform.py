"""Transform (pure functions): clean reports, split by symbol, merge and add net positions."""

import pandas as pd

import config


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


def add_net_positions(dataframe):
    """Sort newest-first and add Net Positions and Change Net Positions."""
    ordered = dataframe.sort_values(by=config.DATE_COL, ascending=False, kind="stable").reset_index(drop=True)
    net = ordered[config.LONG_COL] - ordered[config.SHORT_COL]
    return ordered.assign(**{config.NET_COL: net, config.NET_CHANGE_COL: net.diff(-1)})


def merge_symbol_data(frames):
    """Combine frames (oldest source first); later frames win on repeated reports.

    Returns (merged_frame, duplicate_row_count).
    """
    combined = pd.concat([f[config.SPECIAL_COLUMNS] for f in frames if f is not None], ignore_index=True)
    deduped = combined.drop_duplicates(subset=[config.MARKET_COL, config.DATE_COL], keep="last")
    return add_net_positions(deduped)[config.DATA_COLUMNS], len(combined) - len(deduped)
