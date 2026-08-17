from __future__ import annotations

from pathlib import Path

import pytest

from abr.book import (
    BookSessionResolver,
    BookStore,
    ChapterRecord,
    PageRecord,
    ScanRecord,
    SummaryRecord,
    normalize_tag_id,
    page_lookup_key,
    page_storage_key,
)


def test_book_store_ensures_layout_and_updates_book_record(tmp_path: Path) -> None:
    store = BookStore(tmp_path / "library")

    record = store.ensure_book("04a224b19c7780", seen_at="2026-07-02T10:00:00Z")

    assert record.tag_id == "04A224B19C7780"
    assert (tmp_path / "library" / "04A224B19C7780" / "book.json").exists()
    assert (tmp_path / "library" / "04A224B19C7780" / "state").is_dir()
    assert (tmp_path / "library" / "04A224B19C7780" / "scans").is_dir()
    assert (tmp_path / "library" / "04A224B19C7780" / "pages").is_dir()
    assert (tmp_path / "library" / "04A224B19C7780" / "chapters").is_dir()
    assert (tmp_path / "library" / "04A224B19C7780" / "summaries").is_dir()

    updated = store.ensure_book("04a224b19c7780", seen_at="2026-07-02T10:05:00Z")
    assert updated.created_at == "2026-07-02T10:00:00Z"
    assert updated.last_seen_at == "2026-07-02T10:05:00Z"


def test_book_store_persists_language_and_rejects_different_profile(tmp_path: Path) -> None:
    store = BookStore(tmp_path / "library")

    record = store.ensure_book("ENGLISH", language="en")

    assert record.language == "en"
    assert store.load_book("ENGLISH").language == "en"  # type: ignore[union-attr]
    with pytest.raises(RuntimeError, match="als Sprache en gespeichert"):
        store.ensure_book("ENGLISH", language="de")


def test_book_store_treats_legacy_book_without_language_as_german(tmp_path: Path) -> None:
    store = BookStore(tmp_path / "library")
    legacy = store.ensure_book("LEGACY")
    assert legacy.language is None

    migrated = store.ensure_book("LEGACY", language="de")

    assert migrated.language == "de"
    with pytest.raises(RuntimeError, match="als Sprache de gespeichert"):
        store.require_book_language("LEGACY", "en")


def test_book_session_resolver_returns_book_root_and_record(tmp_path: Path) -> None:
    resolver = BookSessionResolver(tmp_path / "library")

    session = resolver.resolve("abcd1234", seen_at="2026-07-02T11:00:00Z")

    assert session.tag_id == "ABCD1234"
    assert session.root_dir == tmp_path / "library" / "ABCD1234"
    assert session.record.last_seen_at == "2026-07-02T11:00:00Z"


def test_save_and_load_scan_page_chapter_and_summary(tmp_path: Path) -> None:
    store = BookStore(tmp_path / "library")
    store.ensure_book("TAG001", seen_at="2026-07-02T10:00:00Z")

    scan = ScanRecord(
        scan_id="scan_001",
        created_at="2026-07-02T10:01:00Z",
        session_dir=Path("captures/scan_001"),
        capture_dir=Path("captures/scan_001/raw"),
        ocr_dir=Path("captures/scan_001/ocr"),
        report_path=Path("captures/scan_001/report.json"),
        left_page_id="page_0008",
        right_page_id="page_0009",
    )
    scan_path = store.save_scan("TAG001", scan)
    assert scan_path == tmp_path / "library" / "TAG001" / "scans" / "scan_001" / "manifest.json"
    assert store.load_scan("TAG001", "scan_001") == scan

    left_page = PageRecord(
        page_id="page_0008",
        scan_id="scan_001",
        created_at="2026-07-02T10:02:00Z",
        side="left",
        page_number=8,
        clean_text="Dies ist Seite acht.",
        speak_text="Dies ist Seite acht.",
        chapter_number=1,
        chapter_heading="Kapitel Eins",
        tail_fragment=None,
        source_report_path=Path("captures/scan_001/report.json"),
    )
    page_path = store.save_page("TAG001", left_page)
    assert page_path == tmp_path / "library" / "TAG001" / "pages" / "0008.json"
    assert store.load_page("TAG001", 8) == left_page

    right_page = PageRecord(
        page_id="page_0009",
        scan_id="scan_001",
        created_at="2026-07-02T10:03:00Z",
        side="right",
        page_number=9,
        clean_text="Sie oeffnete die Tuer",
        speak_text="ging weiter. Sie oeffnete die Tuer",
        tail_fragment="ging weiter.",
    )
    store.save_page("TAG001", right_page)
    pages = store.list_pages("TAG001")
    assert [page.page_number for page in pages] == [8, 9]

    chapter = ChapterRecord(
        chapter_id="chapter_0001",
        created_at="2026-07-02T10:04:00Z",
        completed_at="2026-07-02T10:05:00Z",
        chapter_number=1,
        chapter_heading="Kapitel Eins",
        start_page=8,
        end_page=9,
        page_ids=["page_0008", "page_0009"],
        page_numbers=[8, 9],
        text_path=Path("placeholder.txt"),
    )
    chapter_path = store.save_chapter("TAG001", chapter, text="Kapiteltext.")
    loaded_chapter = store.load_chapter("TAG001", "chapter_0001")
    assert chapter_path == tmp_path / "library" / "TAG001" / "chapters" / "chapter_0001" / "chapter.json"
    assert loaded_chapter is not None
    assert loaded_chapter.text_path == tmp_path / "library" / "TAG001" / "chapters" / "chapter_0001" / "text.txt"
    assert loaded_chapter.page_numbers == [8, 9]
    assert loaded_chapter.text_path.read_text(encoding="utf-8") == "Kapiteltext.\n"

    summary = SummaryRecord(
        summary_id="latest_chapter_summary",
        summary_type="latest_chapter",
        updated_at="2026-07-02T10:06:00Z",
        text="Kurze Zusammenfassung.",
        source_chapter_ids=["chapter_0001"],
        model_name="gemini",
    )
    summary_path = store.save_summary("TAG001", "latest_chapter_summary.json", summary)
    assert summary_path == tmp_path / "library" / "TAG001" / "summaries" / "latest_chapter_summary.json"
    assert store.load_summary("TAG001", "latest_chapter_summary.json") == summary


def test_runtime_state_roundtrip(tmp_path: Path) -> None:
    store = BookStore(tmp_path / "library")
    store.ensure_book("TAG001", seen_at="2026-07-02T12:00:00Z")

    store.save_runtime_state(
        "TAG001",
        "pending_fragment.json",
        {"page_number": 9, "tail_fragment": "ging weiter."},
    )

    assert store.load_runtime_state("TAG001", "pending_fragment.json") == {
        "page_number": 9,
        "tail_fragment": "ging weiter.",
    }


def test_iso15693_tag_association_can_resolve_existing_book(tmp_path: Path) -> None:
    store = BookStore(tmp_path / "library")
    store.ensure_book("04A1B2C3")

    path = store.associate_iso15693_tag("04A1B2C3", "E004010916F34897")
    store.associate_iso15693_tag("04A1B2C3", "E004010916F34897")

    assert path.read_text(encoding="utf-8") == "E004010916F34897\n"
    assert store.find_book_by_iso15693_tag("e004010916f34897") == "04A1B2C3"


def test_storage_key_helpers_normalize_and_reject_invalid_values(tmp_path: Path) -> None:
    assert normalize_tag_id("  aa11bb22  ") == "AA11BB22"
    assert page_lookup_key(8) == "0008"
    assert page_lookup_key("9") == "0009"
    assert page_storage_key(
        PageRecord(
            page_id="page_0010",
            scan_id="scan_001",
            created_at="2026-07-02T10:00:00Z",
            side="left",
            page_number=10,
            clean_text="x",
            speak_text="x",
        )
    ) == "0010"

    with pytest.raises(ValueError):
        normalize_tag_id("../oops")

    with pytest.raises(ValueError):
        store = BookStore(tmp_path / "library")
        store.save_summary("TAG001", "latest_chapter_summary.txt", SummaryRecord("id", "book", "now", "x"))
