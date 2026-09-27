import datetime as dt
from zoneinfo import ZoneInfo

import requests
from helpers import PESO, report, zip_bytes

import config
from cot_pipeline.extract import (
    download_reports,
    expected_latest_report,
    latest_released_report_date,
    load_saved_reports,
    plan_downloads,
    raw_zip_path,
    report_years,
)

ET = ZoneInfo("America/New_York")
# Saturday 2026-09-26: the latest published report is Tuesday 2026-09-22 (released Friday 25th)
SATURDAY = dt.datetime(2026, 9, 26, 9, 0, tzinfo=ET)


def save_year(raw_dir, year, dates):
    """Save a yearly zip whose reports have the given as-of dates."""
    rows = [(PESO, d, 1, 1, 0) for d in dates]
    raw_zip_path(year, raw_dir).write_bytes(zip_bytes(report(rows)))


def plan(years, raw_dir, now=SATURDAY, refresh=False):
    """plan_downloads as {year: (download?, reason)}."""
    return {year: (download, reason) for year, download, reason in plan_downloads(years, raw_dir, now, refresh)}


def test_latest_released_report_date_follows_friday_release_time():
    """The Tuesday report counts as released only from Friday 15:30 US Eastern."""
    assert latest_released_report_date(dt.datetime(2026, 9, 25, 15, 29, tzinfo=ET)) == dt.date(2026, 9, 15)
    assert latest_released_report_date(dt.datetime(2026, 9, 25, 15, 30, tzinfo=ET)) == dt.date(2026, 9, 22)
    assert latest_released_report_date(SATURDAY) == dt.date(2026, 9, 22)
    assert latest_released_report_date(dt.datetime(2026, 9, 24, 12, 0, tzinfo=ET)) == dt.date(2026, 9, 15)


def test_expected_latest_report_for_past_current_and_future_years():
    """Past years end on their last Tuesday, the current year on the latest release, future years have none."""
    latest = dt.date(2026, 9, 22)
    assert expected_latest_report(2025, latest) == dt.date(2025, 12, 30)
    assert expected_latest_report(2026, latest) == latest
    assert expected_latest_report(2027, latest) is None
    assert expected_latest_report(2025, dt.date(2025, 12, 23)) == dt.date(2025, 12, 23)  # before Jan release


def test_plan_downloads_skips_complete_saved_years(tmp_path):
    """A saved past year with its final week, and a current year with the latest week, are not downloaded."""
    save_year(tmp_path, 2025, ["2025-12-23", "2025-12-30"])
    save_year(tmp_path, 2026, ["2026-09-15", "2026-09-22"])
    decisions = plan([2025, 2026], tmp_path)
    assert decisions[2025][0] is False and "up to date" in decisions[2025][1]
    assert decisions[2026][0] is False


def test_plan_downloads_accepts_holiday_shifted_final_week(tmp_path):
    """A final report moved to a Monday still counts as complete; a missing final week does not."""
    save_year(tmp_path, 2018, ["2018-12-18", "2018-12-31"])
    save_year(tmp_path, 2019, ["2019-12-30"])  # Monday before the last Tuesday (Dec 31)
    save_year(tmp_path, 2020, ["2020-12-22"])  # a full week short of the last Tuesday (Dec 29)
    decisions = plan([2018, 2019, 2020], tmp_path)
    assert decisions[2018][0] is False and decisions[2019][0] is False
    assert decisions[2020][0] is True


def test_plan_downloads_fetches_missing_stale_and_unreadable_years(tmp_path):
    """Missing, out-of-date and corrupt saved copies are downloaded, with the reason given."""
    save_year(tmp_path, 2025, ["2025-06-24"])  # downloaded mid-year, never completed
    save_year(tmp_path, 2026, ["2026-09-15"])  # one week behind
    raw_zip_path(2024, tmp_path).write_bytes(b"not a zip")
    decisions = plan([2023, 2024, 2025, 2026], tmp_path)
    assert decisions[2023] == (True, "no saved copy")
    assert decisions[2024] == (True, "saved copy unreadable")
    assert decisions[2025] == (True, "saved copy ends 2025-06-24, report for 2025-12-30 expected")
    assert decisions[2026] == (True, "saved copy ends 2026-09-15, report for 2026-09-22 expected")


def test_plan_downloads_never_fetches_history_or_future_years(tmp_path):
    """Years before 2017 come from FUT86_16.txt and unpublished years are skipped, even with --refresh."""
    decisions = plan([2010, 2016, 2027], tmp_path, refresh=True)
    assert decisions[2010] == (False, "covered by FUT86_16.txt")
    assert decisions[2016][0] is False
    assert decisions[2027][0] is False and "no report published" in decisions[2027][1]
    assert report_years([2010, 2016, 2017, 2026, 2027], SATURDAY) == [2017, 2026]


def test_plan_downloads_refresh_redownloads_saved_years(tmp_path):
    """--refresh downloads a year even when its saved copy is up to date."""
    save_year(tmp_path, 2025, ["2025-12-30"])
    assert plan([2025], tmp_path, refresh=True)[2025] == (True, "--refresh requested")


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
