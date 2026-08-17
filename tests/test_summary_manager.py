from __future__ import annotations

from pathlib import Path
import json
import urllib.request
from dataclasses import replace
import pytest

from abr.book import (
    BookStore,
    ChapterRecord,
    GeminiSummaryBackend,
    GeminiSummaryConfig,
    SummaryBackend,
    SummaryManager,
    SummaryManagerConfig,
    SummaryRecord,
)


class _StaticSummaryBackend(SummaryBackend):
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = outputs
        self.prompts: list[str] = []
        self.max_output_tokens: list[int | None] = []

    def is_available(self) -> bool:
        return True

    def model_name(self) -> str:
        return "static-test"

    def generate(self, *, instruction: str, prompt: str, max_output_tokens: int | None = None) -> str:
        self.prompts.append(f"{instruction}\n---\n{prompt}")
        self.max_output_tokens.append(max_output_tokens)
        return self.outputs.pop(0)


def _save_test_chapter(store: BookStore, tag_id: str, *, text: str = "Source text.") -> None:
    chapter = ChapterRecord(
        chapter_id="chapter_0001",
        created_at="2026-08-07T12:00:00Z",
        completed_at="2026-08-07T12:00:00Z",
        text_path=Path("placeholder.txt"),
        page_ids=["page_0001"],
        page_numbers=[1],
        start_page=1,
        end_page=5,
    )
    store.save_chapter(tag_id, chapter, text=text)


def test_summary_manager_uses_us_english_prompts_and_metadata(tmp_path: Path) -> None:
    store = BookStore(tmp_path / "library")
    store.ensure_book("ENGLISH1", language="en")
    _save_test_chapter(store, "ENGLISH1", text="Alice crossed the river.")
    backend = _StaticSummaryBackend(["Alice crosses the river and continues her journey."])
    manager = SummaryManager(store, backend, SummaryManagerConfig(language="en"))

    summary = manager.summarize_chapter("ENGLISH1", "chapter_0001")

    assert summary.metadata["language"] == "en"
    assert "Use natural U.S. English" in backend.prompts[0]
    assert "Summarize the following book section in English" in backend.prompts[0]
    assert "pages 1-5" in backend.prompts[0]
    assert "Alice crossed the river." in backend.prompts[0]


def test_summary_manager_uses_english_progress_and_book_prompts(tmp_path: Path) -> None:
    store = BookStore(tmp_path / "library")
    store.ensure_book("ENGLISH2", language="en")
    _save_test_chapter(store, "ENGLISH2")
    backend = _StaticSummaryBackend(
        [
            "Chapter recap.",
            "Current story recap.",
            "Previously in the book recap.",
        ]
    )
    manager = SummaryManager(store, backend, SummaryManagerConfig(language="en"))

    manager.summarize_chapter_progress("ENGLISH2", "New unfinished pages.")
    book_summary = manager.summarize_book_so_far("ENGLISH2")

    assert "Summary of the latest completed section" in backend.prompts[1]
    assert "Text since that section" in backend.prompts[1]
    assert "Available section summaries" in backend.prompts[2]
    assert book_summary.metadata["language"] == "en"


def test_summary_manager_rejects_language_change_for_existing_book(tmp_path: Path) -> None:
    store = BookStore(tmp_path / "library")
    store.ensure_book("BILINGUAL")
    _save_test_chapter(store, "BILINGUAL", text="Neutral source text.")
    german_backend = _StaticSummaryBackend(["Deutsche Zusammenfassung."])
    german_manager = SummaryManager(store, german_backend)
    german_summary = german_manager.summarize_chapter("BILINGUAL", "chapter_0001")

    english_backend = _StaticSummaryBackend(["English summary."])
    english_manager = SummaryManager(store, english_backend, SummaryManagerConfig(language="en"))
    with pytest.raises(RuntimeError, match="als Sprache de gespeichert"):
        english_manager.summarize_chapter("BILINGUAL", "chapter_0001")

    assert german_summary.metadata["language"] == "de"
    assert english_backend.prompts == []


def test_legacy_summary_without_language_remains_valid_for_german(tmp_path: Path) -> None:
    store = BookStore(tmp_path / "library")
    store.ensure_book("LEGACYDE")
    _save_test_chapter(store, "LEGACYDE")
    first = SummaryManager(store, _StaticSummaryBackend(["Bestehende Zusammenfassung."]))
    summary = first.summarize_chapter("LEGACYDE", "chapter_0001")
    summary.metadata.pop("language")
    path = store.save_summary("LEGACYDE", "chapter_0001_summary.json", summary)
    chapter = store.load_chapter("LEGACYDE", "chapter_0001")
    assert chapter is not None
    store.save_chapter("LEGACYDE", replace(chapter, summary_path=path))
    backend = _StaticSummaryBackend([])

    cached = SummaryManager(store, backend).summarize_chapter("LEGACYDE", "chapter_0001")

    assert cached.text == "Bestehende Zusammenfassung."
    assert backend.prompts == []


def test_english_summary_shortening_uses_english_prompt(tmp_path: Path) -> None:
    store = BookStore(tmp_path / "library")
    store.ensure_book("ENGLISHSHORT", language="en")
    _save_test_chapter(store, "ENGLISHSHORT")
    long_text = " ".join(f"word{index}" for index in range(140))
    short_text = " ".join(f"word{index}" for index in range(120)) + "."
    backend = _StaticSummaryBackend([long_text, short_text])
    manager = SummaryManager(
        store,
        backend,
        SummaryManagerConfig(language="en", chapter_summary_target_pages=0.5),
    )

    summary = manager.summarize_chapter("ENGLISHSHORT", "chapter_0001")

    assert summary.text == short_text
    assert "You shorten English book summaries" in backend.prompts[1]
    assert "Shorten the following summary to no more than 125 words" in backend.prompts[1]


def test_book_summary_rejects_language_change_for_existing_book(tmp_path: Path) -> None:
    store = BookStore(tmp_path / "library")
    store.ensure_book("BOOKCACHELANG")
    _save_test_chapter(store, "BOOKCACHELANG")
    german_manager = SummaryManager(
        store,
        _StaticSummaryBackend(["Kapitelzusammenfassung.", "Buchzusammenfassung."]),
    )
    german_manager.summarize_book_so_far("BOOKCACHELANG")
    english_backend = _StaticSummaryBackend(["Chapter summary.", "Book recap."])

    with pytest.raises(RuntimeError, match="als Sprache de gespeichert"):
        SummaryManager(
            store,
            english_backend,
            SummaryManagerConfig(language="en"),
        ).summarize_book_so_far("BOOKCACHELANG")

    assert english_backend.prompts == []


def test_summary_manager_saves_chapter_summary_and_updates_chapter_record(tmp_path: Path) -> None:
    store = BookStore(tmp_path / "library")
    store.ensure_book("BOOK1")
    chapter = ChapterRecord(
        chapter_id="chapter_0001",
        created_at="2026-07-04T12:00:00Z",
        completed_at="2026-07-04T12:00:00Z",
        text_path=Path("placeholder.txt"),
        page_ids=["page_0001", "page_0002"],
        page_numbers=[1, 2],
        start_page=1,
        end_page=2,
    )
    store.save_chapter("BOOK1", chapter, text="Ein langer Abschnitt.")
    manager = SummaryManager(store, _StaticSummaryBackend(["Kurze Kapitelzusammenfassung."]))

    summary = manager.summarize_chapter("BOOK1", "chapter_0001")

    assert summary.summary_type == "chapter"
    saved = store.load_chapter("BOOK1", "chapter_0001")
    assert saved is not None
    assert saved.summary_path is not None
    assert saved.summary_path.exists()
    assert store.load_summary("BOOK1", "chapter_0001_summary.json") == summary


def test_summary_manager_builds_disposable_progress_summary_from_latest_summary_and_pending_text(
    tmp_path: Path,
) -> None:
    store = BookStore(tmp_path / "library")
    store.ensure_book("BOOKPROGRESS")
    chapter = ChapterRecord(
        chapter_id="chapter_0001",
        created_at="2026-08-01T10:00:00Z",
        completed_at="2026-08-01T10:00:00Z",
        text_path=Path("placeholder.txt"),
        page_ids=["page_0001"],
        page_numbers=[1],
        start_page=1,
        end_page=10,
    )
    store.save_chapter("BOOKPROGRESS", chapter, text="Text des abgeschlossenen Abschnitts.")
    backend = _StaticSummaryBackend(
        [
            "Gespeicherte Zusammenfassung des Abschnitts.",
            "Temporäre Zusammenfassung einschließlich der neuen Ereignisse.",
        ]
    )
    manager = SummaryManager(store, backend)
    saved_summary = manager.summarize_chapter("BOOKPROGRESS", "chapter_0001")

    latest_chapter, temporary = manager.summarize_chapter_progress(
        "BOOKPROGRESS",
        "Seit dem Abschnitt geschah etwas Neues.",
        pending_page_ids=("page_0011",),
        pending_page_numbers=(11,),
    )

    assert latest_chapter is not None
    assert latest_chapter.chapter_id == "chapter_0001"
    assert temporary.text == "Temporäre Zusammenfassung einschließlich der neuen Ereignisse."
    assert temporary.summary_type == "temporary_chapter_progress"
    assert temporary.metadata["temporary"] is True
    assert temporary.metadata["pending_page_numbers"] == [11]
    assert "Gespeicherte Zusammenfassung des Abschnitts." in backend.prompts[-1]
    assert "Seit dem Abschnitt geschah etwas Neues." in backend.prompts[-1]
    assert store.load_summary("BOOKPROGRESS", "chapter_0001_summary.json") == saved_summary
    assert not (store.book_dir("BOOKPROGRESS") / "summaries" / "temporary_chapter_progress.json").exists()


def test_summary_manager_builds_disposable_progress_summary_without_completed_chapter(
    tmp_path: Path,
) -> None:
    store = BookStore(tmp_path / "library")
    store.ensure_book("BOOKPROGRESSSTART")
    backend = _StaticSummaryBackend(["Temporäre Zusammenfassung der ersten Seiten."])
    manager = SummaryManager(store, backend)

    latest_chapter, temporary = manager.summarize_chapter_progress(
        "BOOKPROGRESSSTART",
        "Die ersten noch nicht abgeschlossenen Seiten.",
        pending_page_ids=("page_0001", "page_0002"),
        pending_page_numbers=(1, 2),
    )

    assert latest_chapter is None
    assert temporary.text == "Temporäre Zusammenfassung der ersten Seiten."
    assert temporary.source_chapter_ids == []
    assert "noch keinen abgeschlossenen" in backend.prompts[-1]
    assert list((store.book_dir("BOOKPROGRESSSTART") / "summaries").glob("*.json")) == []


def test_summary_manager_builds_book_summary_from_existing_chapter_summaries(tmp_path: Path) -> None:
    store = BookStore(tmp_path / "library")
    store.ensure_book("BOOK2")
    backend = _StaticSummaryBackend(
        [
            "Zusammenfassung Abschnitt eins.",
            "Zusammenfassung Abschnitt zwei.",
            "Gesamtzusammenfassung.",
        ]
    )
    manager = SummaryManager(store, backend)

    for index in (1, 2):
        chapter = ChapterRecord(
            chapter_id=f"chapter_{index:04d}",
            created_at="2026-07-04T12:00:00Z",
            completed_at="2026-07-04T12:00:00Z",
            text_path=Path("placeholder.txt"),
            page_ids=[f"page_{index:04d}"],
            page_numbers=[index],
            start_page=index,
            end_page=index,
        )
        store.save_chapter("BOOK2", chapter, text=f"Abschnitt {index}.")

    summary = manager.summarize_book_so_far("BOOK2")

    assert summary.summary_type == "book_so_far"
    assert summary.text == "Gesamtzusammenfassung."
    assert summary.source_chapter_ids == ["chapter_0001", "chapter_0002"]
    assert "Vorliegende Abschnittszusammenfassungen" in backend.prompts[-1]


def test_summary_manager_uses_configured_target_pages_in_prompts(tmp_path: Path) -> None:
    store = BookStore(tmp_path / "library")
    store.ensure_book("BOOK3")
    backend = _StaticSummaryBackend(
        [
            "Zusammenfassung Abschnitt eins.",
            "Zusammenfassung Abschnitt zwei.",
            "Gesamtzusammenfassung.",
        ]
    )
    manager = SummaryManager(
        store,
        backend,
        SummaryManagerConfig(
            chapter_summary_target_pages=1.5,
            book_summary_target_pages=2.0,
        ),
    )

    for index in (1, 2):
        chapter = ChapterRecord(
            chapter_id=f"chapter_{index:04d}",
            created_at="2026-07-04T12:00:00Z",
            completed_at="2026-07-04T12:00:00Z",
            text_path=Path("placeholder.txt"),
            page_ids=[f"page_{index:04d}"],
            page_numbers=[index],
            start_page=index,
            end_page=index,
        )
        store.save_chapter("BOOK3", chapter, text=f"Abschnitt {index}.")

    manager.summarize_book_so_far("BOOK3")

    assert "ungefaehr 1.5 Textseiten" in backend.prompts[0]
    assert "ungefaehr 1.5 Textseiten" in backend.prompts[1]
    assert "ungefaehr 2 Textseiten umfassen" in backend.prompts[2]
    assert "hoechstens 375 Woerter" in backend.prompts[0]
    assert "hoechstens 500 Woerter" in backend.prompts[2]
    assert backend.max_output_tokens == [2048, 2048, 2048]


def test_summary_manager_shortens_chapter_summary_above_word_tolerance(tmp_path: Path) -> None:
    store = BookStore(tmp_path / "library")
    store.ensure_book("BOOKWORDS")
    chapter = ChapterRecord(
        chapter_id="chapter_0001",
        created_at="2026-07-04T12:00:00Z",
        completed_at="2026-07-04T12:00:00Z",
        text_path=Path("placeholder.txt"),
        page_ids=["page_0001"],
        page_numbers=[1],
        start_page=1,
        end_page=10,
    )
    store.save_chapter("BOOKWORDS", chapter, text="Ein langer Abschnitt.")
    first_text = " ".join(f"Langwort{index}" for index in range(140))
    shortened_text = " ".join(f"Kurzwort{index}" for index in range(120)) + "."
    backend = _StaticSummaryBackend([first_text, shortened_text])
    manager = SummaryManager(
        store,
        backend,
        SummaryManagerConfig(chapter_summary_target_pages=0.5),
    )

    summary = manager.summarize_chapter("BOOKWORDS", "chapter_0001")

    assert summary.text == shortened_text
    assert len(backend.prompts) == 2
    assert "hoechstens 125 Woerter" in backend.prompts[0]
    assert "Kuerze die folgende Zusammenfassung auf hoechstens 125 Woerter" in backend.prompts[1]
    assert summary.metadata["target_words"] == 125
    assert summary.metadata["initial_word_count"] == 140
    assert summary.metadata["actual_word_count"] == 120
    assert summary.metadata["length_policy_version"] == 1


def test_summary_manager_does_not_shorten_summary_within_word_tolerance(tmp_path: Path) -> None:
    store = BookStore(tmp_path / "library")
    store.ensure_book("BOOKWORDSTOLERANCE")
    chapter = ChapterRecord(
        chapter_id="chapter_0001",
        created_at="2026-07-04T12:00:00Z",
        completed_at="2026-07-04T12:00:00Z",
        text_path=Path("placeholder.txt"),
        page_ids=["page_0001"],
        page_numbers=[1],
        start_page=1,
        end_page=10,
    )
    store.save_chapter("BOOKWORDSTOLERANCE", chapter, text="Ein langer Abschnitt.")
    summary_text = " ".join(f"Wort{index}" for index in range(137)) + "."
    backend = _StaticSummaryBackend([summary_text])
    manager = SummaryManager(
        store,
        backend,
        SummaryManagerConfig(chapter_summary_target_pages=0.5),
    )

    summary = manager.summarize_chapter("BOOKWORDSTOLERANCE", "chapter_0001")

    assert summary.text == summary_text
    assert len(backend.prompts) == 1
    assert summary.metadata["initial_word_count"] == 137
    assert summary.metadata["actual_word_count"] == 137


def test_summary_manager_rejects_still_overlong_shortening_result(tmp_path: Path) -> None:
    store = BookStore(tmp_path / "library")
    store.ensure_book("BOOKWORDSFAIL")
    chapter = ChapterRecord(
        chapter_id="chapter_0001",
        created_at="2026-07-04T12:00:00Z",
        completed_at="2026-07-04T12:00:00Z",
        text_path=Path("placeholder.txt"),
        page_ids=["page_0001"],
        page_numbers=[1],
        start_page=1,
        end_page=10,
    )
    store.save_chapter("BOOKWORDSFAIL", chapter, text="Ein langer Abschnitt.")
    overlong_text = " ".join(f"Wort{index}" for index in range(140))
    backend = _StaticSummaryBackend([overlong_text, overlong_text])
    manager = SummaryManager(
        store,
        backend,
        SummaryManagerConfig(chapter_summary_target_pages=0.5),
    )

    try:
        manager.summarize_chapter("BOOKWORDSFAIL", "chapter_0001")
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("RuntimeError expected")

    assert "140 statt hoechstens 138 Woerter" in message
    assert store.load_summary("BOOKWORDSFAIL", "chapter_0001_summary.json") is None


def test_summary_manager_regenerates_chapter_summary_when_target_pages_change(tmp_path: Path) -> None:
    store = BookStore(tmp_path / "library")
    store.ensure_book("BOOK3B")
    chapter = ChapterRecord(
        chapter_id="chapter_0001",
        created_at="2026-07-04T12:00:00Z",
        completed_at="2026-07-04T12:00:00Z",
        text_path=Path("placeholder.txt"),
        page_ids=["page_0001"],
        page_numbers=[1],
        start_page=1,
        end_page=10,
    )
    store.save_chapter("BOOK3B", chapter, text="Ein langer Abschnitt.")

    first_backend = _StaticSummaryBackend(["Lange Zusammenfassung."])
    first_manager = SummaryManager(
        store,
        first_backend,
        SummaryManagerConfig(chapter_summary_target_pages=1.5),
    )
    first_summary = first_manager.summarize_chapter("BOOK3B", "chapter_0001")

    second_backend = _StaticSummaryBackend(["Kurze Zusammenfassung."])
    second_manager = SummaryManager(
        store,
        second_backend,
        SummaryManagerConfig(chapter_summary_target_pages=0.7),
    )
    second_summary = second_manager.summarize_chapter("BOOK3B", "chapter_0001")

    assert first_summary.text == "Lange Zusammenfassung."
    assert second_summary.text == "Kurze Zusammenfassung."
    assert second_backend.max_output_tokens == [2048]
    saved = store.load_summary("BOOK3B", "chapter_0001_summary.json")
    assert saved is not None
    assert saved.metadata["target_pages"] == 0.7


def test_summary_manager_regenerates_legacy_chapter_summary_without_completion_marker(tmp_path: Path) -> None:
    store = BookStore(tmp_path / "library")
    store.ensure_book("BOOK3LEGACY")
    chapter = ChapterRecord(
        chapter_id="chapter_0001",
        created_at="2026-07-04T12:00:00Z",
        completed_at="2026-07-04T12:00:00Z",
        text_path=Path("placeholder.txt"),
        page_ids=["page_0001"],
        page_numbers=[1],
        start_page=1,
        end_page=10,
    )
    store.save_chapter("BOOK3LEGACY", chapter, text="Ein langer Abschnitt.")
    saved_chapter = store.load_chapter("BOOK3LEGACY", "chapter_0001")
    assert saved_chapter is not None
    legacy_summary = SummaryRecord(
        summary_id="chapter_0001_summary",
        summary_type="chapter",
        updated_at="2026-07-30T12:00:00Z",
        text="Dieser alte Text bricht mitten im Wo",
        source_chapter_ids=["chapter_0001"],
        model_name="gemini-3.5-flash",
        metadata={"target_pages": 1.5, "max_output_tokens": 570},
    )
    summary_path = store.save_summary("BOOK3LEGACY", "chapter_0001_summary.json", legacy_summary)
    store.save_chapter("BOOK3LEGACY", replace(saved_chapter, summary_path=summary_path))
    backend = _StaticSummaryBackend(["Vollständig neu erzeugte Zusammenfassung."])

    summary = SummaryManager(store, backend).summarize_chapter("BOOK3LEGACY", "chapter_0001")

    assert summary.text == "Vollständig neu erzeugte Zusammenfassung."
    assert summary.metadata["generation_complete"] is True
    assert len(backend.prompts) == 1


def test_summary_manager_regenerates_book_summary_when_target_pages_change(tmp_path: Path) -> None:
    store = BookStore(tmp_path / "library")
    store.ensure_book("BOOK3C")
    for index in (1, 2):
        chapter = ChapterRecord(
            chapter_id=f"chapter_{index:04d}",
            created_at="2026-07-04T12:00:00Z",
            completed_at="2026-07-04T12:00:00Z",
            text_path=Path("placeholder.txt"),
            page_ids=[f"page_{index:04d}"],
            page_numbers=[index],
            start_page=index,
            end_page=index + 5,
        )
        store.save_chapter("BOOK3C", chapter, text=f"Abschnitt {index}.")

    first_backend = _StaticSummaryBackend(
        [
            "Zusammenfassung Abschnitt eins.",
            "Zusammenfassung Abschnitt zwei.",
            "Lange Buchzusammenfassung.",
        ]
    )
    first_manager = SummaryManager(
        store,
        first_backend,
        SummaryManagerConfig(book_summary_target_pages=1.5),
    )
    first_summary = first_manager.summarize_book_so_far("BOOK3C")

    second_backend = _StaticSummaryBackend(["Kurze Buchzusammenfassung."])
    second_manager = SummaryManager(
        store,
        second_backend,
        SummaryManagerConfig(book_summary_target_pages=0.7),
    )
    second_summary = second_manager.summarize_book_so_far("BOOK3C")

    assert first_summary.text == "Lange Buchzusammenfassung."
    assert second_summary.text == "Kurze Buchzusammenfassung."
    assert second_backend.max_output_tokens == [2048]
    saved = store.load_summary("BOOK3C", "book_so_far_summary.json")
    assert saved is not None
    assert saved.metadata["target_pages"] == 0.7


def test_summary_manager_regenerates_book_summary_when_chapter_summary_content_changes(
    tmp_path: Path,
) -> None:
    store = BookStore(tmp_path / "library")
    store.ensure_book("BOOK3D")
    chapter = ChapterRecord(
        chapter_id="chapter_0001",
        created_at="2026-07-04T12:00:00Z",
        completed_at="2026-07-04T12:00:00Z",
        text_path=Path("placeholder.txt"),
        page_ids=["page_0001"],
        page_numbers=[1],
        start_page=1,
        end_page=8,
    )
    store.save_chapter("BOOK3D", chapter, text="Ein längerer Abschnitt.")
    first_manager = SummaryManager(
        store,
        _StaticSummaryBackend(
            [
                "Erste Abschnittszusammenfassung.",
                "Veraltete kurze Buchzusammenfassung.",
            ]
        ),
    )
    first_manager.summarize_book_so_far("BOOK3D")

    changed_chapter_summary = store.load_summary("BOOK3D", "chapter_0001_summary.json")
    assert changed_chapter_summary is not None
    changed_chapter_summary.text = "Korrigierte und deutlich ausführlichere Abschnittszusammenfassung."
    changed_chapter_summary.updated_at = "2026-07-31T08:00:00Z"
    store.save_summary("BOOK3D", "chapter_0001_summary.json", changed_chapter_summary)

    second_backend = _StaticSummaryBackend(["Neu erzeugte ausführliche Buchzusammenfassung."])
    second_summary = SummaryManager(store, second_backend).summarize_book_so_far("BOOK3D")

    assert second_summary.text == "Neu erzeugte ausführliche Buchzusammenfassung."
    assert len(second_backend.prompts) == 1
    assert "Korrigierte und deutlich ausführlichere" in second_backend.prompts[0]


def test_summary_manager_loads_latest_available_chapter_summary_not_necessarily_latest_chapter(tmp_path: Path) -> None:
    store = BookStore(tmp_path / "library")
    store.ensure_book("BOOK4")
    backend = _StaticSummaryBackend(["Zusammenfassung Abschnitt eins."])
    manager = SummaryManager(store, backend)

    for index in (1, 2):
        chapter = ChapterRecord(
            chapter_id=f"chapter_{index:04d}",
            created_at="2026-07-04T12:00:00Z",
            completed_at="2026-07-04T12:00:00Z",
            text_path=Path("placeholder.txt"),
            page_ids=[f"page_{index:04d}"],
            page_numbers=[index],
            start_page=index,
            end_page=index,
        )
        store.save_chapter("BOOK4", chapter, text=f"Abschnitt {index}.")

    manager.summarize_chapter("BOOK4", "chapter_0001")

    loaded = manager.load_latest_chapter_summary("BOOK4")

    assert loaded is not None
    chapter, summary = loaded
    assert chapter.chapter_id == "chapter_0001"
    assert summary.summary_type == "chapter"
    assert summary.text == "Zusammenfassung Abschnitt eins."


def test_summary_manager_ignores_non_chapter_summary_when_loading_latest_chapter_summary(tmp_path: Path) -> None:
    store = BookStore(tmp_path / "library")
    store.ensure_book("BOOK5")
    backend = _StaticSummaryBackend(["Zusammenfassung Abschnitt eins."])
    manager = SummaryManager(store, backend)

    first = ChapterRecord(
        chapter_id="chapter_0001",
        created_at="2026-07-04T12:00:00Z",
        completed_at="2026-07-04T12:00:00Z",
        text_path=Path("placeholder.txt"),
        page_ids=["page_0001"],
        page_numbers=[1],
        start_page=1,
        end_page=1,
    )
    second = ChapterRecord(
        chapter_id="chapter_0002",
        created_at="2026-07-04T12:00:00Z",
        completed_at="2026-07-04T12:00:00Z",
        text_path=Path("placeholder.txt"),
        page_ids=["page_0002"],
        page_numbers=[2],
        start_page=2,
        end_page=2,
    )
    store.save_chapter("BOOK5", first, text="Abschnitt 1.")
    store.save_chapter("BOOK5", second, text="Abschnitt 2.")

    manager.summarize_chapter("BOOK5", "chapter_0001")
    book_summary = SummaryRecord(
        summary_id="book_so_far_summary",
        summary_type="book_so_far",
        updated_at="2026-07-04T12:00:00Z",
        text="Gesamtrueckschau.",
        source_chapter_ids=["chapter_0001", "chapter_0002"],
        model_name="static-test",
    )
    wrong_path = store.save_summary("BOOK5", "book_so_far_summary.json", book_summary)
    current_second = store.load_chapter("BOOK5", "chapter_0002")
    assert current_second is not None
    store.save_chapter("BOOK5", replace(current_second, summary_path=wrong_path))

    loaded = manager.load_latest_chapter_summary("BOOK5")

    assert loaded is not None
    chapter, summary = loaded
    assert chapter.chapter_id == "chapter_0001"
    assert summary.summary_type == "chapter"


def test_summary_manager_prefers_highest_chapter_sequence_over_page_order_for_latest_summary(tmp_path: Path) -> None:
    store = BookStore(tmp_path / "library")
    store.ensure_book("BOOK6")
    backend = _StaticSummaryBackend(
        [
            "Zusammenfassung Abschnitt zwei.",
            "Zusammenfassung Abschnitt drei.",
        ]
    )
    manager = SummaryManager(store, backend)

    second = ChapterRecord(
        chapter_id="chapter_0002",
        created_at="2026-07-04T12:00:00Z",
        completed_at="2026-07-04T12:00:00Z",
        text_path=Path("placeholder.txt"),
        page_ids=["page_0002"],
        page_numbers=[23],
        start_page=23,
        end_page=5,
    )
    third = ChapterRecord(
        chapter_id="chapter_0003",
        created_at="2026-07-04T12:10:00Z",
        completed_at="2026-07-04T12:10:00Z",
        text_path=Path("placeholder.txt"),
        page_ids=["page_0003"],
        page_numbers=[7],
        start_page=7,
        end_page=11,
    )
    store.save_chapter("BOOK6", second, text="Abschnitt 2.")
    store.save_chapter("BOOK6", third, text="Abschnitt 3.")

    manager.summarize_chapter("BOOK6", "chapter_0002")
    manager.summarize_chapter("BOOK6", "chapter_0003")

    loaded = manager.load_latest_chapter_summary("BOOK6")

    assert loaded is not None
    chapter, summary = loaded
    assert chapter.chapter_id == "chapter_0003"
    assert summary.summary_id == "chapter_0003_summary"


def test_summary_manager_builds_book_summary_in_chapter_sequence_order_and_includes_all_chapters(tmp_path: Path) -> None:
    store = BookStore(tmp_path / "library")
    store.ensure_book("BOOK7")
    backend = _StaticSummaryBackend(
        [
            "Zusammenfassung Abschnitt eins.",
            "Zusammenfassung Abschnitt zwei.",
            "Zusammenfassung Abschnitt drei.",
            "Gesamtzusammenfassung.",
        ]
    )
    manager = SummaryManager(store, backend)

    chapters = [
        ChapterRecord(
            chapter_id="chapter_0001",
            created_at="2026-07-04T12:00:00Z",
            completed_at="2026-07-04T12:00:00Z",
            text_path=Path("placeholder.txt"),
            page_ids=["page_0001"],
            page_numbers=[1],
            start_page=1,
            end_page=10,
        ),
        ChapterRecord(
            chapter_id="chapter_0002",
            created_at="2026-07-04T12:10:00Z",
            completed_at="2026-07-04T12:10:00Z",
            text_path=Path("placeholder.txt"),
            page_ids=["page_0002"],
            page_numbers=[23],
            start_page=23,
            end_page=5,
        ),
        ChapterRecord(
            chapter_id="chapter_0003",
            created_at="2026-07-04T12:20:00Z",
            completed_at="2026-07-04T12:20:00Z",
            text_path=Path("placeholder.txt"),
            page_ids=["page_0003"],
            page_numbers=[7],
            start_page=7,
            end_page=11,
        ),
    ]
    for index, chapter in enumerate(chapters, start=1):
        store.save_chapter("BOOK7", chapter, text=f"Abschnitt {index}.")

    summary = manager.summarize_book_so_far("BOOK7")

    assert summary.summary_type == "book_so_far"
    assert summary.source_chapter_ids == ["chapter_0001", "chapter_0002", "chapter_0003"]
    prompt = backend.prompts[-1]
    assert "chapter_0001" in prompt
    assert "chapter_0002" in prompt
    assert "chapter_0003" in prompt
    assert prompt.index("chapter_0001") < prompt.index("chapter_0002") < prompt.index("chapter_0003")
    assert "Zusammenfassung Abschnitt eins." in prompt
    assert "Zusammenfassung Abschnitt zwei." in prompt
    assert "Zusammenfassung Abschnitt drei." in prompt


def test_gemini_summary_backend_uses_google_cloud_generate_content_and_extracts_text(monkeypatch) -> None:
    requests: list[urllib.request.Request] = []

    class _FakeResponse:
        def __init__(self, payload: dict[str, object]) -> None:
            self.payload = payload

        def read(self) -> bytes:
            return json.dumps(self.payload).encode("utf-8")

        def __enter__(self) -> _FakeResponse:
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    def _fake_urlopen(request, timeout=None):
        del timeout
        requests.append(request)
        return _FakeResponse(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": "Antwort von Gemini."}],
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr("abr.book.summary_manager.get_google_project_id", lambda: "project-123")
    monkeypatch.setattr("abr.book.summary_manager.get_google_access_token", lambda: ("token-123", 3300.0))
    monkeypatch.setattr("abr.book.summary_manager.get_google_quota_project", lambda: "project-123")
    monkeypatch.setattr("abr.book.summary_manager.urllib.request.urlopen", _fake_urlopen)
    backend = GeminiSummaryBackend(GeminiSummaryConfig(model="gemini-3.5-flash", location="global"))

    text = backend.generate(instruction="System", prompt="Prompt")

    assert text == "Antwort von Gemini."
    assert requests
    request = requests[0]
    assert request.full_url == (
        "https://aiplatform.googleapis.com/v1/projects/project-123/"
        "locations/global/publishers/google/models/gemini-3.5-flash:generateContent"
    )
    assert request.headers["Authorization"] == "Bearer token-123"
    payload = json.loads(request.data.decode("utf-8"))
    assert payload["systemInstruction"]["parts"] == [{"text": "System"}]
    assert payload["contents"][0]["parts"] == [{"text": "Prompt"}]
    assert "maxOutputTokens" not in payload["generationConfig"]


def test_gemini_summary_backend_includes_max_output_tokens_when_provided(monkeypatch) -> None:
    requests: list[urllib.request.Request] = []

    class _FakeResponse:
        def __init__(self, payload: dict[str, object]) -> None:
            self.payload = payload

        def read(self) -> bytes:
            return json.dumps(self.payload).encode("utf-8")

        def __enter__(self) -> _FakeResponse:
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    def _fake_urlopen(request, timeout=None):
        del timeout
        requests.append(request)
        return _FakeResponse(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": "Antwort von Gemini."}],
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr("abr.book.summary_manager.get_google_project_id", lambda: "project-123")
    monkeypatch.setattr("abr.book.summary_manager.get_google_access_token", lambda: ("token-123", 3300.0))
    monkeypatch.setattr("abr.book.summary_manager.get_google_quota_project", lambda: "project-123")
    monkeypatch.setattr("abr.book.summary_manager.urllib.request.urlopen", _fake_urlopen)
    backend = GeminiSummaryBackend(GeminiSummaryConfig(model="gemini-3.5-flash", location="global"))

    backend.generate(instruction="System", prompt="Prompt", max_output_tokens=222)

    payload = json.loads(requests[0].data.decode("utf-8"))
    assert payload["generationConfig"]["maxOutputTokens"] == 222


def test_gemini_summary_backend_retries_without_output_limit_when_first_response_has_no_text(monkeypatch) -> None:
    requests: list[urllib.request.Request] = []
    responses = [
        {
            "candidates": [
                {
                    "content": {"parts": []},
                    "finishReason": "MAX_TOKENS",
                }
            ],
            "usageMetadata": {"totalTokenCount": 321},
        },
        {
            "candidates": [
                {
                    "content": {"parts": [{"text": "Antwort nach Wiederholung."}]},
                    "finishReason": "STOP",
                }
            ]
        },
    ]

    class _FakeResponse:
        def __init__(self, payload: dict[str, object]) -> None:
            self.payload = payload

        def read(self) -> bytes:
            return json.dumps(self.payload).encode("utf-8")

        def __enter__(self) -> _FakeResponse:
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    def _fake_urlopen(request, timeout=None):
        del timeout
        requests.append(request)
        return _FakeResponse(responses.pop(0))

    monkeypatch.setattr("abr.book.summary_manager.get_google_project_id", lambda: "project-123")
    monkeypatch.setattr("abr.book.summary_manager.get_google_access_token", lambda: ("token-123", 3300.0))
    monkeypatch.setattr("abr.book.summary_manager.get_google_quota_project", lambda: "project-123")
    monkeypatch.setattr("abr.book.summary_manager.urllib.request.urlopen", _fake_urlopen)
    backend = GeminiSummaryBackend(GeminiSummaryConfig(model="gemini-3.5-flash", location="global"))

    text = backend.generate(instruction="System", prompt="Prompt", max_output_tokens=222)

    assert text == "Antwort nach Wiederholung."
    assert len(requests) == 2
    first_payload = json.loads(requests[0].data.decode("utf-8"))
    second_payload = json.loads(requests[1].data.decode("utf-8"))
    assert first_payload["generationConfig"]["maxOutputTokens"] == 222
    assert "maxOutputTokens" not in second_payload["generationConfig"]


def test_gemini_summary_backend_retries_when_first_response_contains_truncated_text(monkeypatch) -> None:
    requests: list[urllib.request.Request] = []
    responses = [
        {
            "candidates": [
                {
                    "content": {"parts": [{"text": "Diese Zusammenfassung bricht mitten im Wo"}]},
                    "finishReason": "MAX_TOKENS",
                }
            ],
            "usageMetadata": {
                "candidatesTokenCount": 9,
                "thoughtsTokenCount": 213,
                "totalTokenCount": 222,
            },
        },
        {
            "candidates": [
                {
                    "content": {"parts": [{"text": "Dies ist die vollständige Zusammenfassung."}]},
                    "finishReason": "STOP",
                }
            ]
        },
    ]

    class _FakeResponse:
        def __init__(self, payload: dict[str, object]) -> None:
            self.payload = payload

        def read(self) -> bytes:
            return json.dumps(self.payload).encode("utf-8")

        def __enter__(self) -> _FakeResponse:
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    def _fake_urlopen(request, timeout=None):
        del timeout
        requests.append(request)
        return _FakeResponse(responses.pop(0))

    monkeypatch.setattr("abr.book.summary_manager.get_google_project_id", lambda: "project-123")
    monkeypatch.setattr("abr.book.summary_manager.get_google_access_token", lambda: ("token-123", 3300.0))
    monkeypatch.setattr("abr.book.summary_manager.get_google_quota_project", lambda: "project-123")
    monkeypatch.setattr("abr.book.summary_manager.urllib.request.urlopen", _fake_urlopen)
    backend = GeminiSummaryBackend(GeminiSummaryConfig(model="gemini-3.5-flash", location="global"))

    text = backend.generate(instruction="System", prompt="Prompt", max_output_tokens=222)

    assert text == "Dies ist die vollständige Zusammenfassung."
    assert len(requests) == 2
    first_payload = json.loads(requests[0].data.decode("utf-8"))
    second_payload = json.loads(requests[1].data.decode("utf-8"))
    assert first_payload["generationConfig"]["maxOutputTokens"] == 222
    assert "maxOutputTokens" not in second_payload["generationConfig"]


def test_gemini_summary_backend_rejects_truncated_retry_response(monkeypatch) -> None:
    responses = [
        {
            "candidates": [
                {
                    "content": {"parts": [{"text": "Erster abgebrochener Text"}]},
                    "finishReason": "MAX_TOKENS",
                }
            ]
        },
        {
            "candidates": [
                {
                    "content": {"parts": [{"text": "Auch der zweite Text bricht ab"}]},
                    "finishReason": "MAX_TOKENS",
                }
            ],
            "usageMetadata": {
                "candidatesTokenCount": 8,
                "thoughtsTokenCount": 214,
                "totalTokenCount": 222,
            },
        },
    ]

    class _FakeResponse:
        def __init__(self, payload: dict[str, object]) -> None:
            self.payload = payload

        def read(self) -> bytes:
            return json.dumps(self.payload).encode("utf-8")

        def __enter__(self) -> _FakeResponse:
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    def _fake_urlopen(request, timeout=None):
        del request, timeout
        return _FakeResponse(responses.pop(0))

    monkeypatch.setattr("abr.book.summary_manager.get_google_project_id", lambda: "project-123")
    monkeypatch.setattr("abr.book.summary_manager.get_google_access_token", lambda: ("token-123", 3300.0))
    monkeypatch.setattr("abr.book.summary_manager.get_google_quota_project", lambda: "project-123")
    monkeypatch.setattr("abr.book.summary_manager.urllib.request.urlopen", _fake_urlopen)
    backend = GeminiSummaryBackend(GeminiSummaryConfig(model="gemini-3.5-flash", location="global"))

    try:
        backend.generate(instruction="System", prompt="Prompt", max_output_tokens=222)
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("RuntimeError expected")

    assert "keinen vollstaendigen verwertbaren Text" in message
    assert "finishReason=MAX_TOKENS" in message
    assert "thoughtsTokenCount=214" in message


def test_gemini_summary_backend_reports_finish_reason_when_response_has_no_text(monkeypatch) -> None:
    class _FakeResponse:
        def __init__(self, payload: dict[str, object]) -> None:
            self.payload = payload

        def read(self) -> bytes:
            return json.dumps(self.payload).encode("utf-8")

        def __enter__(self) -> _FakeResponse:
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    def _fake_urlopen(request, timeout=None):
        del request, timeout
        return _FakeResponse(
            {
                "promptFeedback": {"blockReason": "PROHIBITED_CONTENT"},
                "candidates": [
                    {
                        "content": {"parts": []},
                        "finishReason": "PROHIBITED_CONTENT",
                    }
                ],
            }
        )

    monkeypatch.setattr("abr.book.summary_manager.get_google_project_id", lambda: "project-123")
    monkeypatch.setattr("abr.book.summary_manager.get_google_access_token", lambda: ("token-123", 3300.0))
    monkeypatch.setattr("abr.book.summary_manager.get_google_quota_project", lambda: "project-123")
    monkeypatch.setattr("abr.book.summary_manager.urllib.request.urlopen", _fake_urlopen)
    backend = GeminiSummaryBackend(GeminiSummaryConfig(model="gemini-3.5-flash", location="global"))

    try:
        backend.generate(instruction="System", prompt="Prompt", max_output_tokens=222)
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("RuntimeError expected")

    assert "promptBlockReason=PROHIBITED_CONTENT" in message
    assert "finishReason=PROHIBITED_CONTENT" in message
    assert "maxOutputTokens=222" in message


def test_gemini_summary_backend_uses_regional_service_endpoint_for_regional_location(monkeypatch) -> None:
    requests: list[urllib.request.Request] = []

    class _FakeResponse:
        def __init__(self, payload: dict[str, object]) -> None:
            self.payload = payload

        def read(self) -> bytes:
            return json.dumps(self.payload).encode("utf-8")

        def __enter__(self) -> _FakeResponse:
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    def _fake_urlopen(request, timeout=None):
        del timeout
        requests.append(request)
        return _FakeResponse(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": "Antwort von Gemini."}],
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr("abr.book.summary_manager.get_google_project_id", lambda: "project-123")
    monkeypatch.setattr("abr.book.summary_manager.get_google_access_token", lambda: ("token-123", 3300.0))
    monkeypatch.setattr("abr.book.summary_manager.get_google_quota_project", lambda: "project-123")
    monkeypatch.setattr("abr.book.summary_manager.urllib.request.urlopen", _fake_urlopen)
    backend = GeminiSummaryBackend(GeminiSummaryConfig(model="gemini-3.5-flash", location="us-central1"))

    backend.generate(instruction="System", prompt="Prompt")

    assert requests
    request = requests[0]
    assert request.full_url == (
        "https://us-central1-aiplatform.googleapis.com/v1/projects/project-123/"
        "locations/us-central1/publishers/google/models/gemini-3.5-flash:generateContent"
    )
