import io
import zipfile

import pandas as pd
import pytest
import requests

import config
import pipeline

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
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("annual.txt", frame.to_csv(index=False))
    return buffer.getvalue()


# --- clean_report ------------------------------------------------------------
def test_clean_report_filters_markets_and_unifies_names():
    raw = report(
        [
            (PESO, "2024-01-02", 10, 5, 1),
            ("DOW JONES INDUSTRIAL AVERAGE - CHICAGO BOARD OF TRADE", "2024-01-02", 1, 1, 1),
            ("SOMETHING ELSE - NOWHERE", "2024-01-02", 1, 1, 1),
        ]
    )
    cleaned, dropped = pipeline.clean_report(raw)
    assert dropped == 0
    assert list(cleaned[config.MARKET_COL]) == [PESO, "DJIA Consolidated - CHICAGO BOARD OF TRADE"]


def test_clean_report_parses_padded_numbers_and_drops_bad_dates():
    raw = report([(PESO, "2024-01-02", 10, 5, 1), (PESO, "not a date", 1, 1, 1)])
    raw[config.OPEN_INTEREST_CHANGE_COL] = ["   -42", "1"]
    cleaned, dropped = pipeline.clean_report(raw)
    assert dropped == 1
    assert cleaned[config.OPEN_INTEREST_CHANGE_COL].tolist() == [-42]


def test_clean_report_rejects_missing_columns():
    with pytest.raises(ValueError, match="missing required columns"):
        pipeline.clean_report(pd.DataFrame({config.MARKET_COL: [PESO]}))


def test_every_configured_market_maps_to_a_symbol():
    unified = [config.MARKET_NAME_REPLACEMENTS.get(mx, mx) for mx in config.MARKETS_AND_EXCHANGES]
    assert [mx for mx in unified if not any(sym in mx for sym in config.SYMBOL_NAMES)] == []


# --- merge / net positions ---------------------------------------------------
def test_merge_symbol_data_dedups_and_computes_net_positions():
    old = report([(PESO, "2024-01-02", 10, 5, 0), (PESO, "2024-01-09", 20, 5, 0)])
    new = report([(PESO, "2024-01-09", 30, 5, 0), (PESO, "2024-01-16", 25, 5, 0)])
    merged, duplicates = pipeline.merge_symbol_data([None, old, new])
    assert duplicates == 1
    assert merged[config.DATE_COL].tolist() == ["2024-01-16", "2024-01-09", "2024-01-02"]
    assert merged[config.NET_COL].tolist() == [20, 25, 5]  # newer report wins for 2024-01-09
    assert merged[config.NET_CHANGE_COL].tolist()[:2] == [-5, 20]
    assert pd.isna(merged[config.NET_CHANGE_COL].iloc[-1])
    assert list(merged.columns) == config.DATA_COLUMNS


def test_rows_for_symbol_matches_all_name_variants():
    frame = report([(PESO, "2024-01-02", 1, 1, 1), (GOLD, "2024-01-02", 1, 1, 1)])
    assert pipeline.rows_for_symbol(frame, "GOLD")[config.MARKET_COL].tolist() == [GOLD]


# --- signals -----------------------------------------------------------------
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
    frame = pd.DataFrame({config.NET_CHANGE_COL: [net_change], config.OPEN_INTEREST_CHANGE_COL: [oi_change]})
    result = pipeline.compute_signals(frame).iloc[0]
    assert (result["signal"], result["Interpretation"]) == expected


# --- storage / download ------------------------------------------------------
def test_update_symbol_creates_missing_file_from_history_and_new_rows(tmp_path):
    history = pipeline.clean_report(report([(PESO, "2016-12-27", 1, 1, 0)]))[0]
    new_rows = pipeline.clean_report(report([(PESO, "2024-01-02", 10, 5, 0)]))[0]
    saved = pipeline.update_symbol("MEXICAN PESO", new_rows, tmp_path / "data", lambda: history)
    on_disk = pd.read_csv(tmp_path / "data" / "MEXICAN PESO.csv")
    assert len(saved) == len(on_disk) == 2


def test_update_symbol_skips_symbol_with_no_data(tmp_path):
    empty = pipeline.clean_report(report([]))[0]
    assert pipeline.update_symbol("GOLD", empty, tmp_path, lambda: None) is None
    assert not (tmp_path / "GOLD.csv").exists()


def test_years_to_download_uses_saved_batches(tmp_path):
    pipeline.raw_zip_path(2020, tmp_path).write_bytes(b"x")
    assert pipeline.years_to_download([2020, 2021, 2026], tmp_path, current_year=2026) == [2021, 2026]
    assert pipeline.years_to_download([2020], tmp_path, current_year=2026, refresh=True) == [2020]


class FakeSession:
    def __init__(self, responses):
        self.responses, self.closed = responses, False

    def get(self, url, timeout):
        outcome = self.responses[url]
        if isinstance(outcome, Exception):
            raise outcome
        response = requests.Response()
        response.status_code, response._content = 200, outcome
        return response

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True


def test_download_reports_saves_batches_logs_failures_and_closes_session(tmp_path):
    good = zip_bytes(report([(PESO, "2024-01-02", 10, 5, 0)]))
    session = FakeSession(
        {
            config.CFTC_YEAR_URL.format(year=2024): good,
            config.CFTC_YEAR_URL.format(year=2025): requests.ConnectionError("boom"),
        }
    )
    failed = pipeline.download_reports([2024, 2025], tmp_path, session_factory=lambda: session)
    assert failed == [2025]
    assert session.closed
    loaded = pipeline.load_saved_reports([2024, 2025], tmp_path)
    assert loaded[config.MARKET_COL].tolist() == [PESO]


def test_run_offline_end_to_end(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    pipeline.raw_zip_path(2024, raw).write_bytes(
        zip_bytes(report([(PESO, "2024-01-02", 10, 5, 2), (PESO, "2024-01-09", 30, 5, 2)]))
    )
    code = pipeline.run(
        [2024], tmp_path / "data", tmp_path / "signal", raw, tmp_path / "reports", tmp_path / "none.txt", offline=True
    )
    signals = pd.read_csv(tmp_path / "signal" / "MEXICAN PESO.csv")
    assert list(signals.columns) == config.SIGNAL_COLUMNS
    assert signals["Interpretation"].tolist() == ["Bullish", "No signal"]
    assert "MEXICAN PESO" in (tmp_path / "reports" / "latest_signals.md").read_text()
    assert code == 1  # other symbols had no data, reported as problems
