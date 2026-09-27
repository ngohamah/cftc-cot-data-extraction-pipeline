import requests
from helpers import PESO, report, zip_bytes

import config
from cot_pipeline.extract import download_reports, load_saved_reports, raw_zip_path, years_to_download


def test_years_to_download_uses_saved_batches(tmp_path):
    """Only years without a saved zip, plus the current year, are downloaded."""
    raw_zip_path(2020, tmp_path).write_bytes(b"x")
    assert years_to_download([2020, 2021, 2026], tmp_path, current_year=2026) == [2021, 2026]
    assert years_to_download([2020], tmp_path, current_year=2026, refresh=True) == [2020]


class FakeSession:
    """Stand-in for requests.Session that returns canned responses per URL and records closing."""

    def __init__(self, responses):
        """responses maps URL -> zip bytes, or an exception to raise."""
        self.responses, self.closed = responses, False

    def get(self, url, timeout):
        """Return a 200 response with the canned bytes for url, or raise its canned exception."""
        outcome = self.responses[url]
        if isinstance(outcome, Exception):
            raise outcome
        response = requests.Response()
        response.status_code, response._content = 200, outcome
        return response

    def __enter__(self):
        """Enter the session context."""
        return self

    def __exit__(self, *exc):
        """Mark the session as closed when the context exits."""
        self.closed = True


def test_download_reports_saves_batches_logs_failures_and_closes_session(tmp_path):
    """Good years are saved, failed years are returned, and the session is closed."""
    good = zip_bytes(report([(PESO, "2024-01-02", 10, 5, 0)]))
    session = FakeSession(
        {
            config.CFTC_YEAR_URL.format(year=2024): good,
            config.CFTC_YEAR_URL.format(year=2025): requests.ConnectionError("boom"),
        }
    )
    failed = download_reports([2024, 2025], tmp_path, session_factory=lambda: session)
    assert failed == [2025]
    assert session.closed
    loaded = load_saved_reports([2024, 2025], tmp_path)
    assert loaded[config.MARKET_COL].tolist() == [PESO]
