"""Synthetic report builders shared by the tests (no network, no real files)."""

import io
import zipfile

import pandas as pd

import config

PESO = "MEXICAN PESO - CHICAGO MERCANTILE EXCHANGE"
GOLD = "GOLD - COMMODITY EXCHANGE INC."


def report(rows):
    """Build a raw-report-like frame from (market, date, long, short, oi_change) tuples."""
    base = {c: 0 for c in config.SPECIAL_COLUMNS}
    return pd.DataFrame(
        [
            {
                **base,
                config.MARKET_COL: market,
                config.DATE_COL: date,
                config.LONG_COL: long,
                config.SHORT_COL: short,
                config.OPEN_INTEREST_CHANGE_COL: oi,
            }
            for market, date, long, short, oi in rows
        ],
        columns=config.SPECIAL_COLUMNS,
    )


def zip_bytes(frame):
    """Bytes of a CFTC-style zip holding frame as annual.txt."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("annual.txt", frame.to_csv(index=False))
    return buffer.getvalue()
