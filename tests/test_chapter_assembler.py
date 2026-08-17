from __future__ import annotations

from pathlib import Path
import pytest

from abr.book import BookStore, ChapterAssembler, PageChapterMarker, PageRecord


def test_chapter_assembler_rejects_page_language_different_from_book(tmp_path: Path) -> None:
    store = BookStore(tmp_path / "library")
    store.ensure_book("MIXED", language="en")
    store.save_page(
        "MIXED",
        PageRecord(
            page_id="page_0001",
            scan_id="scan_1",
            created_at="2026-08-07T12:00:00Z",
            side="left",
            clean_text="Deutscher Text.",
            speak_text="Deutscher Text.",
            page_number=1,
            metadata={"language": "de"},
        ),
    )

    with pytest.raises(RuntimeError, match="Gemischte Buchdaten"):
        ChapterAssembler(store).assemble_available_chapters("MIXED")


def test_chapter_assembler_closes_section_at_first_marker_after_minimum_page_window(tmp_path: Path) -> None:
    store = BookStore(tmp_path / "library")
    store.ensure_book("BOOK1")
    assembler = ChapterAssembler(store)

    for page_number in range(1, 13):
        markers = []
        clean_text = f"Seite {page_number}."
        if page_number == 12:
            clean_text = "Kapitel 12\nDer neue Abschnitt beginnt."
            markers = [PageChapterMarker(line_index=0, chapter_number=12, detection_kind="explicit_label")]
        store.save_page(
            "BOOK1",
            PageRecord(
                page_id=f"page_{page_number:04d}",
                scan_id=f"scan_{(page_number + 1) // 2:03d}",
                created_at="2026-07-04T10:00:00Z",
                side="left" if page_number % 2 else "right",
                clean_text=clean_text,
                speak_text=clean_text,
                page_number=page_number,
                chapter_markers=markers,
            ),
        )

    result = assembler.assemble_available_chapters("BOOK1")

    assert [chapter.chapter_id for chapter in result.created_chapters] == ["chapter_0001"]
    chapter = result.created_chapters[0]
    assert chapter.page_numbers == list(range(1, 12))
    assert chapter.start_page == 1
    assert chapter.end_page == 11
    assert "Kapitel 12" not in chapter.text_path.read_text(encoding="utf-8")
    state = store.load_runtime_state("BOOK1", "chapter_assembler_state.json")
    assert state is not None
    assert state["current_start"]["page_number"] == 12
    assert state["current_start"]["offset"] == 0
    assert assembler.assemble_available_chapters("BOOK1").created_chapters == ()


def test_chapter_assembler_uses_last_complete_paragraph_on_page_twenty_and_resumes_inside_same_page(
    tmp_path: Path,
) -> None:
    store = BookStore(tmp_path / "library")
    store.ensure_book("BOOK2")
    assembler = ChapterAssembler(store)

    for page_number in range(1, 21):
        clean_text = f"Seite {page_number}."
        if page_number == 20:
            clean_text = "Erster Absatz.\n\nOffener Satz ohne Ende"
        store.save_page(
            "BOOK2",
            PageRecord(
                page_id=f"page_{page_number:04d}",
                scan_id=f"scan_{(page_number + 1) // 2:03d}",
                created_at="2026-07-04T11:00:00Z",
                side="left" if page_number % 2 else "right",
                clean_text=clean_text,
                speak_text=clean_text,
                page_number=page_number,
            ),
        )

    first_result = assembler.assemble_available_chapters("BOOK2")

    assert [chapter.chapter_id for chapter in first_result.created_chapters] == ["chapter_0001"]
    first_text = first_result.created_chapters[0].text_path.read_text(encoding="utf-8")
    assert "Erster Absatz." in first_text
    assert "Offener Satz ohne Ende" not in first_text

    for page_number in range(21, 31):
        markers = []
        clean_text = f"Seite {page_number}."
        if page_number == 30:
            clean_text = "Kapitel 30\nDer neue Abschnitt."
            markers = [PageChapterMarker(line_index=0, chapter_number=30, detection_kind="explicit_label")]
        store.save_page(
            "BOOK2",
            PageRecord(
                page_id=f"page_{page_number:04d}",
                scan_id=f"scan_{(page_number + 1) // 2:03d}",
                created_at="2026-07-04T11:30:00Z",
                side="left" if page_number % 2 else "right",
                clean_text=clean_text,
                speak_text=clean_text,
                page_number=page_number,
                chapter_markers=markers,
            ),
        )

    second_result = assembler.assemble_available_chapters("BOOK2")

    assert [chapter.chapter_id for chapter in second_result.created_chapters] == ["chapter_0002"]
    second_chapter = second_result.created_chapters[0]
    second_text = second_chapter.text_path.read_text(encoding="utf-8")
    assert second_text.startswith("Offener Satz ohne Ende")
    assert "Kapitel 30" not in second_text
    assert second_chapter.start_page == 20
    assert second_chapter.end_page == 29


def test_chapter_assembler_keeps_scan_order_when_initial_pages_have_no_page_numbers(tmp_path: Path) -> None:
    store = BookStore(tmp_path / "library")
    store.ensure_book("BOOK3")
    assembler = ChapterAssembler(store)

    store.save_page(
        "BOOK3",
        PageRecord(
            page_id="page_1",
            scan_id="scan_001",
            created_at="2026-07-04T10:00:00Z",
            side="left",
            clean_text="Unnummerierte erste Seite.",
            speak_text="Unnummerierte erste Seite.",
        ),
    )
    store.save_page(
        "BOOK3",
        PageRecord(
            page_id="page_2",
            scan_id="scan_001",
            created_at="2026-07-04T10:00:00Z",
            side="right",
            clean_text="Unnummerierte zweite Seite.",
            speak_text="Unnummerierte zweite Seite.",
        ),
    )

    assert assembler.assemble_available_chapters("BOOK3").created_chapters == ()

    for page_number in range(8, 26):
        store.save_page(
            "BOOK3",
            PageRecord(
                page_id=f"page_{page_number:04d}",
                scan_id=f"scan_{page_number:03d}",
                created_at=f"2026-07-04T10:{page_number:02d}:00Z",
                side="left" if page_number % 2 else "right",
                clean_text=f"Seite {page_number}.",
                speak_text=f"Seite {page_number}.",
                page_number=page_number,
            ),
        )

    result = assembler.assemble_available_chapters("BOOK3")

    assert [chapter.chapter_id for chapter in result.created_chapters] == ["chapter_0001"]
    chapter = result.created_chapters[0]
    assert chapter.page_ids[:2] == ["page_1", "page_2"]
    assert chapter.page_numbers == list(range(8, 26))
