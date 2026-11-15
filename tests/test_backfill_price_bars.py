import importlib.util
import re
from pathlib import Path

import pytest
import requests

import config

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_SQL = ROOT / "supabase" / "migrations" / "20261115000000_price_pipeline_schema.sql"


@pytest.fixture(scope="module")
def script():
    path = ROOT / "scripts" / "backfill_price_bars.py"
    spec = importlib.util.spec_from_file_location("backfill_price_bars", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")


class FakeSession:
    """Answers GET with the asset list and POST from a per-asset table of responses."""

    def __init__(self, assets, responses):
        self.assets = assets
        self.responses = responses
        self.calls = []

    def get(self, url, headers, timeout):
        self.calls.append(("GET", url, headers))
        return FakeResponse(200, {"assets": self.assets})

    def post(self, url, json, headers, timeout):
        self.calls.append(("POST", json["assets"][0], json["range"]))
        answer = self.responses[json["assets"][0]]
        if isinstance(answer, Exception):
            raise answer
        return answer


def test_summarize_splits_ok_and_failed(script):
    ok, failed = script.summarize(
        [
            {"asset": "GOLD", "bars": 6500},
            {"asset": "SILVER", "error": "Yahoo responded 404 for SI=F"},
        ]
    )
    assert ok == ["GOLD: 6500 bars"]
    assert failed == ["SILVER: Yahoo responded 404 for SI=F"]


def test_read_settings_names_every_missing_variable(script):
    with pytest.raises(ValueError, match="INGEST_PRICE_BARS_URL, INGEST_PRICE_BARS_SECRET"):
        script.read_settings({})
    with pytest.raises(ValueError, match="INGEST_PRICE_BARS_SECRET"):
        script.read_settings({"INGEST_PRICE_BARS_URL": "https://x/functions/v1/ingest-price-bars"})
    assert script.read_settings({"INGEST_PRICE_BARS_URL": "u", "INGEST_PRICE_BARS_SECRET": "s"}) == ("u", "s")


def test_parse_args_rejects_ranges_yahoo_does_not_know(script):
    args = script.parse_args(["--assets", "GOLD", "JPYUSD", "--range", "1y"])
    assert args.assets == ["GOLD", "JPYUSD"] and args.range == "1y"
    assert script.parse_args([]).range == "max"
    with pytest.raises(SystemExit):
        script.parse_args(["--range", "20y"])


def test_ingest_reads_the_summary_even_on_207(script):
    session = FakeSession([], {"SILVER": FakeResponse(207, {"summary": [{"asset": "SILVER", "error": "boom"}]})})
    assert script.ingest(session, "u", "s", "SILVER", "max") == {"asset": "SILVER", "error": "boom"}
    assert session.calls == [("POST", "SILVER", "max")]


def test_ingest_all_keeps_going_when_one_request_fails(script):
    session = FakeSession(
        [],
        {
            "GOLD": FakeResponse(200, {"summary": [{"asset": "GOLD", "bars": 12}]}),
            "SILVER": requests.ConnectionError("no route"),
            "COPPER": FakeResponse(200, {"summary": []}),
        },
    )
    results = script.ingest_all(session, "u", "s", ["GOLD", "SILVER", "COPPER"], "1mo")
    assert results[0] == {"asset": "GOLD", "bars": 12}
    assert results[1]["asset"] == "SILVER" and "no route" in results[1]["error"]
    assert results[2]["asset"] == "COPPER" and "not an enabled asset" in results[2]["error"]


def test_main_lists_assets_when_none_given_and_fails_if_any_failed(script, monkeypatch, tmp_path, capsys):
    session = FakeSession(
        ["GOLD", "SILVER"],
        {
            "GOLD": FakeResponse(200, {"summary": [{"asset": "GOLD", "bars": 3}]}),
            "SILVER": FakeResponse(207, {"summary": [{"asset": "SILVER", "error": "Yahoo responded 500"}]}),
        },
    )
    monkeypatch.setattr(script.requests, "Session", lambda: _closing(session))
    env = {"INGEST_PRICE_BARS_URL": "https://x/functions/v1/ingest-price-bars", "INGEST_PRICE_BARS_SECRET": "s"}
    log = tmp_path / "price.log"

    assert script.main(["--log-file", str(log)], env=env) == 1
    out = capsys.readouterr()
    assert "GOLD: 3 bars" in out.out and "SILVER: Yahoo responded 500" in out.err
    assert [c[:2] for c in session.calls] == [
        ("GET", env["INGEST_PRICE_BARS_URL"]),
        ("POST", "GOLD"),
        ("POST", "SILVER"),
    ]
    assert "SILVER failed" in log.read_text()


def test_main_exits_2_without_settings(script, tmp_path, capsys):
    assert script.main(["--log-file", str(tmp_path / "p.log")], env={}) == 2
    assert "missing environment variable" in capsys.readouterr().err


def test_registry_matches_sql_seed_and_signal_files():
    """config.PRICE_ASSETS, the database seed and the signal files must describe the same assets."""
    seed = re.findall(
        r"\('([^']+)',\s*'([^']+)',\s*'([^']+)',\s*(true|false),\s*(true|false)\)", SCHEMA_SQL.read_text()
    )
    assert [(a, f, y, inv == "true", fx == "true") for a, f, y, inv, fx in seed] == config.PRICE_ASSETS
    assets = [a for a, *_ in config.PRICE_ASSETS]
    assert len(set(assets)) == len(assets)
    for asset, signal_file, yahoo_symbol, invert, is_forex in config.PRICE_ASSETS:
        assert signal_file in config.SYMBOL_NAMES
        assert yahoo_symbol.endswith("=X") == is_forex
        # inverted exactly when Yahoo quotes the pair the other way round (USDJPY=X for JPYUSD)
        assert invert == (is_forex and yahoo_symbol[:6] != asset)


class _closing:
    """Wrap the fake session so `with requests.Session() as s` works."""

    def __init__(self, session):
        self.session = session

    def __enter__(self):
        return self.session

    def __exit__(self, *exc):
        return False
