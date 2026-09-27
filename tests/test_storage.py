import pandas as pd

from cot_pipeline.storage import append_csv


def test_append_csv_adds_rows_without_header_and_keeps_saved_bytes(tmp_path):
    path = tmp_path / "x.csv"
    path.write_text("a,b\n1,2\n")
    append_csv(pd.DataFrame({"a": [3], "b": [4]}), path)
    assert path.read_text() == "a,b\n1,2\n3,4\n"


def test_append_csv_adds_missing_trailing_newline(tmp_path):
    path = tmp_path / "x.csv"
    path.write_text("a,b\n1,2")
    append_csv(pd.DataFrame({"a": [3], "b": [4]}), path)
    assert path.read_text() == "a,b\n1,2\n3,4\n"
