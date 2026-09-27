import pandas as pd
from helpers import PESO, report, zip_bytes

import config
from cot_pipeline.extract import raw_zip_path
from cot_pipeline.orchestrate import run, update_symbol
from cot_pipeline.transform import clean_report


def test_update_symbol_creates_missing_file_from_history_and_new_rows(tmp_path):
    history = clean_report(report([(PESO, "2016-12-27", 1, 1, 0)]))[0]
    new_rows = clean_report(report([(PESO, "2024-01-02", 10, 5, 0)]))[0]
    saved = update_symbol("MEXICAN PESO", new_rows, tmp_path / "data", lambda: history)
    on_disk = pd.read_csv(tmp_path / "data" / "MEXICAN PESO.csv")
    assert len(saved) == len(on_disk) == 2


def test_update_symbol_skips_symbol_with_no_data(tmp_path):
    empty = clean_report(report([]))[0]
    assert update_symbol("GOLD", empty, tmp_path, lambda: None) is None
    assert not (tmp_path / "GOLD.csv").exists()


def test_run_offline_end_to_end(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    raw_zip_path(2024, raw).write_bytes(
        zip_bytes(report([(PESO, "2024-01-02", 10, 5, 2), (PESO, "2024-01-09", 30, 5, 2)]))
    )
    code = run([2024], tmp_path / "data", tmp_path / "signal", raw, tmp_path / "reports", offline=True)
    signals = pd.read_csv(tmp_path / "signal" / "MEXICAN PESO.csv")
    assert list(signals.columns) == config.SIGNAL_COLUMNS
    assert signals["Interpretation"].tolist() == ["Bullish", "No signal"]
    assert "MEXICAN PESO" in (tmp_path / "reports" / "latest_signals.md").read_text()
    assert code == 1  # other symbols had no data, reported as problems
