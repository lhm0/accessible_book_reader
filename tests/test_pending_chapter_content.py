from __future__ import annotations

from pathlib import Path

from abr.book import BookStore, ChapterAssembler, ChapterAssemblerConfig, PageRecord


def _save_page(store: BookStore, tag_id: str, page_number: int, text: str) -> None:
    store.save_page(
        tag_id,
        PageRecord(
            page_id=f"page_{page_number:04d}",
            scan_id=f"scan_{page_number:04d}",
            created_at=f"2026-08-01T10:{page_number:02d}:00Z",
            side="left" if page_number % 2 else "right",
            clean_text=text,
            speak_text=text,
            page_number=page_number,
        ),
    )


def test_collect_pending_content_starts_at_persisted_open_boundary(tmp_path: Path) -> None:
    store = BookStore(tmp_path / "library")
    store.ensure_book("BOOKPENDING")
    assembler = ChapterAssembler(
        store,
        ChapterAssemblerConfig(min_pages=2, max_pages=2),
    )
    _save_page(store, "BOOKPENDING", 1, "Erster Abschnitt, Seite eins.")
    _save_page(
        store,
        "BOOKPENDING",
        2,
        "Abgeschlossener Absatz.\n\nOffener Beginn des naechsten Abschnitts",
    )

    result = assembler.assemble_available_chapters("BOOKPENDING")
    assert len(result.created_chapters) == 1
    completed_text = result.created_chapters[0].text_path.read_text(encoding="utf-8")
    assert "Abgeschlossener Absatz." in completed_text
    assert "Offener Beginn" not in completed_text

    _save_page(store, "BOOKPENDING", 3, "Fortsetzung nach der Abschnittsgrenze.")
    pending = assembler.collect_pending_content("BOOKPENDING")

    assert pending.page_numbers == (2, 3)
    assert pending.page_ids == ("page_0002", "page_0003")
    assert pending.text.startswith("Offener Beginn des naechsten Abschnitts")
    assert "Fortsetzung nach der Abschnittsgrenze." in pending.text
    assert "Abgeschlossener Absatz." not in pending.text


def test_collect_pending_content_returns_all_pages_before_first_completed_section(tmp_path: Path) -> None:
    store = BookStore(tmp_path / "library")
    store.ensure_book("BOOKSTART")
    assembler = ChapterAssembler(store)
    _save_page(store, "BOOKSTART", 1, "Der Anfang.")
    _save_page(store, "BOOKSTART", 2, "Die Geschichte geht weiter.")

    pending = assembler.collect_pending_content("BOOKSTART")

    assert pending.page_numbers == (1, 2)
    assert pending.text == "Der Anfang.\n\nDie Geschichte geht weiter."
