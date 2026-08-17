from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from abr.book import BookStore
from abr.remote_mail import DEFAULT_CONFIG, load_config, send_text
from abr.usage_statistics import UsageStatisticsStore


def format_duration(seconds: float) -> str:
    total = max(0, round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def render_period_report(period: dict[str, Any], book_store: BookStore) -> str:
    lines = [
        "ABR Nutzerstatistik",
        f"Zeitraum: {period['starts_at']} bis {period['ends_at']} (Europe/Berlin)",
        "",
    ]
    books = period.get("books", {})
    totals = {"pages": 0, "audio": 0.0, "chapter": 0, "book": 0}
    if not books:
        lines.append("Keine Nutzung erfasst.")
    for tag_id in sorted(books):
        data = books[tag_id]
        record = book_store.load_book(tag_id)
        label = tag_id
        if record is not None and record.title:
            label = f"{record.title} ({tag_id})"
        pages = int(data.get("pages_scanned", 0))
        audio = float(data.get("audio_seconds", 0.0))
        chapter = int(data.get("chapter_summary_uses", 0))
        book = int(data.get("book_summary_uses", 0))
        totals["pages"] += pages
        totals["audio"] += audio
        totals["chapter"] += chapter
        totals["book"] += book
        lines.extend(
            [
                f"Buch: {label}",
                f"  Gescannte Seiten: {pages}",
                f"  Audio-Wiedergabe: {format_duration(audio)}",
                f"  Zusammenfassungsfunktion: {chapter}",
                f"  Was bisher geschah: {book}",
                "",
            ]
        )
    lines.extend(
        [
            "Gesamt:",
            f"  Gescannte Seiten: {totals['pages']}",
            f"  Audio-Wiedergabe: {format_duration(totals['audio'])}",
            f"  Zusammenfassungsfunktion: {totals['chapter']}",
            f"  Was bisher geschah: {totals['book']}",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Abgeschlossene ABR-Nutzungsstatistik per E-Mail senden")
    parser.add_argument("--library-root", type=Path, default=Path("library"))
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--recipient",
        default=None,
        help="Optionaler Empfaenger; standardmaessig recipient aus mail.ini.",
    )
    parser.add_argument(
        "--preview-current",
        action="store_true",
        help="Laufende Periode als Testmail senden, ohne sie zu archivieren oder zurueckzusetzen.",
    )
    args = parser.parse_args(argv)
    try:
        library_root = args.library_root.expanduser().resolve()
        statistics = UsageStatisticsStore(library_root)
        book_store = BookStore(library_root)
        config = load_config(args.config)
        recipient = args.recipient or config.recipient
        if args.preview_current:
            period = statistics.current_period()
            if period is None:
                print("In der laufenden Statistikperiode sind noch keine Daten vorhanden.")
                return 0
            period_key = str(period["period_key"])
            send_text(
                subject=f"ABR Nutzerstatistik Vorschau {period_key}",
                body="VORSCHAU – laufende Periode, keine Ruecksetzung\n\n"
                + render_period_report(period, book_store),
                config=config,
                recipient=recipient,
            )
            print(f"Vorschau fuer {period_key} gesendet an {recipient}; Daten bleiben erhalten.")
            return 0
        periods = statistics.closed_periods()
        if not periods:
            print("Keine abgeschlossene Statistikperiode vorhanden.")
            return 0
        for period in periods:
            period_key = str(period["period_key"])
            send_text(
                subject=f"ABR Nutzerstatistik {period_key}",
                body=render_period_report(period, book_store),
                config=config,
                recipient=recipient,
            )
            archive_path = statistics.archive_reported_period(period)
            print(f"Statistik {period_key} gesendet an {recipient}; archiviert: {archive_path}")
    except Exception as exc:
        print(f"abr_usage_report: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
