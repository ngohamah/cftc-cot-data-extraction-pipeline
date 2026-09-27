import logging

import pandas as pd
from helpers import PESO, report, zip_bytes

import config
from cot_pipeline.extract import raw_zip_path
from cot_pipeline.orchestrate import APPENDED, CREATED, REWRITTEN, UNCHANGED, run, update_signals, update_symbol
from cot_pipeline.transform import clean_report, merge_symbol_data

WEEKS = [(PESO, "2024-01-02", 10, 5, 2), (PESO, "2024-01-09", 30, 5, 2)]
NEXT_WEEK = [(PESO, "2024-01-16", 25, 5, -1)]


def cleaned(rows):
    """Cleaned report rows built from (market, date, long, short, oi_change) tuples."""
    return clean_report(report(rows))[0]


def test_update_symbol_creates_missing_file_from_history_and_new_rows(tmp_path):
    """A missing file is created with history first, then the new reports."""
    history = cleaned([(PESO, "2016-12-27", 1, 1, 0)])
    update = update_symbol("MEXICAN PESO", cleaned([(PESO, "2024-01-02", 10, 5, 0)]), tmp_path, lambda: history)
    on_disk = pd.read_csv(tmp_path / "MEXICAN PESO.csv")
    assert update.mode == CREATED and update.new_count == 2
    assert on_disk[config.DATE_COL].tolist() == ["2016-12-27", "2024-01-02"]


def test_update_symbol_skips_symbol_with_no_data(tmp_path):
    """No file is written for a symbol with no rows anywhere."""
    assert update_symbol("GOLD", cleaned([]), tmp_path, lambda: None) is None
    assert not (tmp_path / "GOLD.csv").exists()


def test_update_symbol_appends_only_new_records(tmp_path):
    """A new week is appended and saved rows stay byte-for-byte identical."""
    update_symbol("MEXICAN PESO", cleaned(WEEKS), tmp_path, lambda: None)
    path = tmp_path / "MEXICAN PESO.csv"
    before = path.read_text()

    update = update_symbol("MEXICAN PESO", cleaned(WEEKS + NEXT_WEEK), tmp_path, lambda: None)

    after = path.read_text()
    assert update.mode == APPENDED and update.new_count == 1
    assert after.startswith(before)  # saved rows untouched
    assert len(after.splitlines()) == len(before.splitlines()) + 1
    assert pd.read_csv(path)[config.NET_CHANGE_COL].tolist()[-1] == -5  # 20 - 25


def test_update_symbol_writes_nothing_when_no_new_records(tmp_path):
    """Re-running with no new reports leaves the file untouched."""
    update_symbol("MEXICAN PESO", cleaned(WEEKS), tmp_path, lambda: None)
    path = tmp_path / "MEXICAN PESO.csv"
    before = path.read_bytes()
    update = update_symbol("MEXICAN PESO", cleaned(WEEKS), tmp_path, lambda: None)
    assert update.mode == UNCHANGED and update.new_count == 0
    assert path.read_bytes() == before


def test_update_symbol_converts_newest_first_file_once_then_appends(tmp_path):
    """A legacy newest-first file is rewritten oldest-first once, then appended to."""
    newest_first = merge_symbol_data([cleaned(WEEKS)])[0].iloc[::-1]
    newest_first.to_csv(tmp_path / "MEXICAN PESO.csv", index=False)
    first = update_symbol("MEXICAN PESO", cleaned(WEEKS), tmp_path, lambda: None)
    second = update_symbol("MEXICAN PESO", cleaned(WEEKS + NEXT_WEEK), tmp_path, lambda: None)
    assert (first.mode, second.mode) == (REWRITTEN, APPENDED)
    dates = pd.read_csv(tmp_path / "MEXICAN PESO.csv")[config.DATE_COL].tolist()
    assert dates == ["2024-01-02", "2024-01-09", "2024-01-16"]


def test_update_symbol_logs_revised_records_and_keeps_saved_values(tmp_path, caplog):
    """CFTC revisions to saved weeks are logged and the saved values are kept."""
    update_symbol("MEXICAN PESO", cleaned(WEEKS), tmp_path, lambda: None)
    revised = [(PESO, "2024-01-02", 999, 5, 2), WEEKS[1]]
    with caplog.at_level(logging.WARNING):
        update = update_symbol("MEXICAN PESO", cleaned(revised), tmp_path, lambda: None)
    assert update.mode == UNCHANGED
    assert "revised 1 already-saved records" in caplog.text
    assert pd.read_csv(tmp_path / "MEXICAN PESO.csv")[config.LONG_COL].tolist()[0] == 10


def test_update_signals_appends_new_signals_only(tmp_path):
    """Signal files grow by the new weeks only."""
    data_dir, signal_dir = tmp_path / "data", tmp_path / "signal"
    update_signals("MEXICAN PESO", update_symbol("MEXICAN PESO", cleaned(WEEKS), data_dir, lambda: None), signal_dir)
    path = signal_dir / "MEXICAN PESO.csv"
    before = path.read_text()
    update = update_symbol("MEXICAN PESO", cleaned(WEEKS + NEXT_WEEK), data_dir, lambda: None)
    update_signals("MEXICAN PESO", update, signal_dir)
    after = path.read_text()
    assert after.startswith(before) and len(after.splitlines()) == len(before.splitlines()) + 1
    assert pd.read_csv(path)["Interpretation"].tolist()[-1] == "Bearish Reversal"


def test_run_offline_end_to_end(tmp_path):
    """An offline run writes data, signals and the report from saved zips."""
    raw = tmp_path / "raw"
    raw.mkdir()
    raw_zip_path(2024, raw).write_bytes(zip_bytes(report(WEEKS)))
    code = run([2024], tmp_path / "data", tmp_path / "signal", raw, tmp_path / "reports", offline=True)
    signals = pd.read_csv(tmp_path / "signal" / "MEXICAN PESO.csv")
    assert list(signals.columns) == config.SIGNAL_COLUMNS
    assert signals["Interpretation"].tolist() == ["No signal", "Bullish"]
    assert "MEXICAN PESO" in (tmp_path / "reports" / "latest_signals.md").read_text()
    assert code == 1  # other symbols had no data, reported as problems


def test_update_symbol_backfills_history_into_file_that_starts_in_2017(tmp_path):
    """A file starting in 2017 gets older history added once, then stays unchanged."""
    recent = [(PESO, "2017-01-03", 10, 5, 0), (PESO, "2017-01-10", 20, 5, 0)]
    history = cleaned([(PESO, "2016-12-20", 1, 1, 0), (PESO, "2016-12-27", 2, 1, 0)])
    update_symbol("MEXICAN PESO", cleaned(recent), tmp_path, lambda: None)  # created without history

    update = update_symbol("MEXICAN PESO", cleaned(recent), tmp_path, lambda: history)

    assert update.mode == REWRITTEN and update.new_count == 2
    saved = pd.read_csv(tmp_path / "MEXICAN PESO.csv")
    assert saved[config.DATE_COL].tolist() == ["2016-12-20", "2016-12-27", "2017-01-03", "2017-01-10"]
    assert saved[config.NET_CHANGE_COL].tolist()[2] == 4  # 5 - 1: 2017 now continues from 2016
    # next run: history already present, nothing to add
    assert update_symbol("MEXICAN PESO", cleaned(recent), tmp_path, lambda: history).mode == UNCHANGED


def test_update_symbol_does_not_rewrite_when_history_has_nothing_older(tmp_path):
    """A symbol with no older history (e.g. BITCOIN) is not rewritten."""
    update_symbol("BITCOIN", cleaned([]), tmp_path, lambda: None)
    rows = [("BITCOIN - CHICAGO MERCANTILE EXCHANGE", "2018-04-10", 1, 1, 0)]
    update_symbol("BITCOIN", cleaned(rows), tmp_path, lambda: None)
    history = cleaned([(PESO, "2016-12-27", 1, 1, 0)])  # other markets only
    assert update_symbol("BITCOIN", cleaned(rows), tmp_path, lambda: history).mode == UNCHANGED
