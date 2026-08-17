from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from abr.book import (
    BookStore,
    ChapterAssembler,
    ChapterAssemblerConfig,
    PageIngestor,
    SummaryBackend,
    SummaryManager,
    SummaryManagerConfig,
)
from abr.capture_ocr import run_capture_ocr
from abr.control.runtime import PageAudioPlayer, PageSpeechConfig
from abr.models import OCRLine


class _EnglishSummaryBackend(SummaryBackend):
    def __init__(self) -> None:
        self.prompt = ""

    def is_available(self) -> bool:
        return True

    def model_name(self) -> str:
        return "integration-summary"

    def generate(self, *, instruction: str, prompt: str, max_output_tokens: int | None = None) -> str:
        del max_output_tokens
        self.prompt = f"{instruction}\n{prompt}"
        return "Alice leaves home and begins her journey."


def _write_image(path: Path) -> None:
    assert cv2.imwrite(str(path), np.full((40, 60, 3), 220, dtype=np.uint8))


def _line(text: str, y: int) -> OCRLine:
    return OCRLine(
        text=text,
        confidence=0.95,
        bbox=((2, y), (55, y), (55, y + 3), (2, y + 3)),
        metadata={"ocr_language": "en", "ocr_model_profile": "en-test"},
    )


def test_english_capture_ocr_ingest_chapter_summary_and_tts_handoff(tmp_path: Path, monkeypatch) -> None:
    ocr_dir = tmp_path / "capture" / "ocr"
    ocr_dir.mkdir(parents=True)
    _write_image(ocr_dir / "left.png")
    _write_image(ocr_dir / "right.png")
    (ocr_dir / "manifest.json").write_text("{}", encoding="utf-8")

    class _EnglishOCRBackend:
        calls = 0

        def recognize(self, _image, language: str = "de") -> list[OCRLine]:
            assert language == "en"
            self.calls += 1
            if self.calls == 1:
                return [_line("Chapter I", 2), _line("Alice leaves home.", 10), _line("1", 35)]
            return [_line("Chapter II", 2), _line("A new journey begins.", 10), _line("2", 35)]

    monkeypatch.setattr("abr.capture_ocr.create_ocr_backend", lambda _name: _EnglishOCRBackend())
    ocr_result = run_capture_ocr(
        ocr_dir=ocr_dir,
        output_dir=tmp_path / "capture" / "ocr_text",
        orientation_mode="off",
        language="en",
    )

    store = BookStore(tmp_path / "library")
    ingest_result = PageIngestor(store, language_code="en").ingest_report(
        "ENGLISH-NFC",
        ocr_result.report_path,
        scan_id="scan_english",
        session_dir=tmp_path / "capture",
    )
    book = store.load_book("ENGLISH-NFC")
    assert book is not None and book.language == "en"
    assert [page.metadata["language"] for page in ingest_result.pages] == ["en", "en"]

    assembly = ChapterAssembler(
        store,
        ChapterAssemblerConfig(min_pages=2, max_pages=3),
    ).assemble_available_chapters("ENGLISH-NFC")
    assert len(assembly.created_chapters) == 1
    chapter = assembly.created_chapters[0]
    assert chapter.metadata["language"] == "en"
    assert "Alice leaves home." in chapter.text_path.read_text(encoding="utf-8")

    summary_backend = _EnglishSummaryBackend()
    summary = SummaryManager(
        store,
        summary_backend,
        SummaryManagerConfig(language="en"),
    ).summarize_chapter("ENGLISH-NFC", chapter.chapter_id)
    assert summary.metadata["language"] == "en"
    assert "Use natural U.S. English" in summary_backend.prompt

    player = PageAudioPlayer(
        PageSpeechConfig(
            language_code="en",
            chapter_label="Chapter",
            google_tts_voice_name="en-US-Standard-D",
            google_tts_language_code="en-US",
        )
    )
    queued: list[tuple[str, str]] = []
    player._enqueue_utterances = lambda utterances: queued.extend(utterances)  # type: ignore[method-assign]
    try:
        player.enqueue_text("chapter-summary", summary.text, language_code=summary.metadata["language"])
    finally:
        player.shutdown()

    assert queued == [("chapter-summary", "Alice leaves home and begins her journey.")]
    assert player.config.google_tts_language_code == "en-US"
    assert player.config.google_tts_voice_name == "en-US-Standard-D"
