from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from abr.book import BookStore
from abr.usage_report import render_period_report
from abr.usage_statistics import UsageStatisticsStore


BERLIN = ZoneInfo("Europe/Berlin")


def test_statistics_day_changes_at_four_and_counts_pages_only_once(tmp_path) -> None:
    store = UsageStatisticsStore(tmp_path / "library")
    before_four = datetime(2026, 8, 2, 3, 59, tzinfo=BERLIN)
    after_four = datetime(2026, 8, 2, 4, 0, tzinfo=BERLIN)

    assert store.period_key(before_four) == "2026-08-01"
    assert store.period_key(after_four) == "2026-08-02"

    store.record_scanned_pages("book1", ["scan1:left", "scan1:right"], now=before_four)
    store.record_scanned_pages("book1", ["scan1:left", "scan1:right"], now=before_four)
    store.record_scanned_pages("book1", ["scan2:left"], now=after_four)

    closed = store.closed_periods(now=after_four)
    assert len(closed) == 1
    assert closed[0]["books"]["BOOK1"]["pages_scanned"] == 2


def test_statistics_records_each_metric_per_book(tmp_path) -> None:
    store = UsageStatisticsStore(tmp_path / "library")
    now = datetime(2026, 8, 1, 12, 0, tzinfo=BERLIN)

    store.record_scanned_pages("book1", ["scan1:left", "scan1:right"], now=now)
    store.record_audio_seconds("book1", 61.4, now=now)
    store.record_chapter_summary("book1", now=now)
    store.record_book_summary("book1", now=now)

    period = store._read_state()["periods"]["2026-08-01"]
    book = period["books"]["BOOK1"]
    assert book["pages_scanned"] == 2
    assert book["audio_seconds"] == 61.4
    assert book["chapter_summary_uses"] == 1
    assert book["book_summary_uses"] == 1
    assert store.current_period(now=now) == period


def test_report_contains_bookwise_values_and_archive_resets_period(tmp_path) -> None:
    library = tmp_path / "library"
    book_store = BookStore(library)
    book_store.ensure_book("book1")
    statistics = UsageStatisticsStore(library)
    now = datetime(2026, 8, 1, 12, 0, tzinfo=BERLIN)
    statistics.record_scanned_pages("book1", ["scan1:left"], now=now)
    statistics.record_audio_seconds("book1", 3661, now=now)
    statistics.record_chapter_summary("book1", now=now)
    period = statistics._read_state()["periods"]["2026-08-01"]

    report = render_period_report(period, book_store)

    assert "Buch: BOOK1" in report
    assert "Gescannte Seiten: 1" in report
    assert "Audio-Wiedergabe: 01:01:01" in report
    assert "Zusammenfassungsfunktion: 1" in report
    archive = statistics.archive_period("2026-08-01")
    assert archive is not None and archive.is_file()
    assert statistics._read_state()["periods"] == {}


def test_closed_periods_includes_previous_day_without_usage(tmp_path) -> None:
    store = UsageStatisticsStore(tmp_path / "library")
    now = datetime(2026, 8, 7, 4, 0, tzinfo=BERLIN)

    periods = store.closed_periods(now=now)

    assert periods == [
        {
            "period_key": "2026-08-06",
            "starts_at": "2026-08-06T04:00:00",
            "ends_at": "2026-08-07T04:00:00",
            "books": {},
        }
    ]
    assert "Keine Nutzung erfasst." in render_period_report(periods[0], BookStore(tmp_path / "library"))


def test_archived_empty_period_is_not_reported_twice(tmp_path) -> None:
    store = UsageStatisticsStore(tmp_path / "library")
    now = datetime(2026, 8, 7, 4, 0, tzinfo=BERLIN)
    period = store.closed_periods(now=now)[0]

    archive = store.archive_reported_period(period)

    assert archive.is_file()
    assert store.closed_periods(now=now) == []


def test_empty_gaps_after_latest_archive_are_reported_in_order(tmp_path) -> None:
    store = UsageStatisticsStore(tmp_path / "library")
    first = store.closed_periods(now=datetime(2026, 8, 5, 4, 0, tzinfo=BERLIN))[0]
    store.archive_reported_period(first)

    periods = store.closed_periods(now=datetime(2026, 8, 8, 4, 0, tzinfo=BERLIN))

    assert [period["period_key"] for period in periods] == ["2026-08-05", "2026-08-06", "2026-08-07"]
