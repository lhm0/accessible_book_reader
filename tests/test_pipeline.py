from pathlib import Path
import json

from abr.models import OCRLine, OrientationCandidate, PageAnalysis, PageInput, PreprocessArtifacts
from abr.ocr.base import OCRBackend
from abr.pipeline import ABRPipeline
from abr.tts.base import TTSBackend


class _DummyOCRBackend(OCRBackend):
    def recognize(self, image, language: str = "de") -> list[OCRLine]:
        return []


class _RecordingTTSBackend(TTSBackend):
    def __init__(self) -> None:
        self.spoken_texts: list[str] = []
        self.files: list[Path] = []
        self.synthesized_texts: list[str] = []
        self.played_files: list[Path] = []

    def speak(self, text: str) -> None:
        self.spoken_texts.append(text)

    def synthesize_to_file(self, text: str, output_path: Path) -> Path:
        self.synthesized_texts.append(text)
        self.files.append(output_path)
        output_path.write_text(text, encoding="utf-8")
        return output_path

    def supports_file_playback(self) -> bool:
        return True

    def live_audio_suffix(self) -> str:
        return ".wav"

    def play_file(self, audio_path: Path) -> None:
        self.played_files.append(audio_path)
        self.spoken_texts.append(audio_path.read_text(encoding="utf-8"))


def _page_analysis(page_id: str, source_path: Path, paragraphs: list[str], slot: str) -> PageAnalysis:
    empty_artifacts = PreprocessArtifacts(gray=None, enhanced=None, sharpened=None, binary=None, ocr_input=None)
    orientation = OrientationCandidate(rotation_deg=0, score=1.0, lines=[], reason="test")
    return PageAnalysis(
        page_id=page_id,
        source_path=source_path,
        slot=slot,
        rotated_image=None,
        preprocessing=empty_artifacts,
        orientation=orientation,
        lines=[],
        layout_blocks=[],
        paragraphs=paragraphs,
        text="\n\n".join(paragraphs),
        debug_paths={},
        timings={},
    )


def test_pipeline_processes_pages_sequentially_and_speaks_complete_chunks(tmp_path: Path) -> None:
    pipeline = ABRPipeline(ocr_backend=_DummyOCRBackend())
    tts_backend = _RecordingTTSBackend()
    statuses: list[str] = []

    page_inputs = [
        PageInput(page_id="page_1", source_path=tmp_path / "left.jpg", image=None),
        PageInput(page_id="page_2", source_path=tmp_path / "right.jpg", image=None),
    ]

    analyses = [
        _page_analysis(
            page_id="page_1",
            source_path=page_inputs[0].source_path,
            paragraphs=["Er sagte Guten Tag.", "Dann oeffnete er die Tuer und"],
            slot="left",
        ),
        _page_analysis(
            page_id="page_2",
            source_path=page_inputs[1].source_path,
            paragraphs=["blickte in den Raum."],
            slot="right",
        ),
    ]

    def _fake_process_page(page_input, index: int, language: str) -> PageAnalysis:
        return analyses[index]

    from abr import pipeline as pipeline_module

    original_loader = pipeline_module.load_page_inputs
    original_process_page = pipeline._process_page
    try:
        pipeline_module.load_page_inputs = lambda paths: page_inputs
        pipeline._process_page = _fake_process_page
        result = pipeline.run(
            ["left.jpg", "right.jpg"],
            speak=True,
            tts_backend=tts_backend,
            status_callback=statuses.append,
        )
    finally:
        pipeline_module.load_page_inputs = original_loader
        pipeline._process_page = original_process_page

    assert [page.page_id for page in result.ordered_pages] == ["page_1", "page_2"]
    assert [chunk.text for chunk in result.reading_chunks] == [
        "Er sagte Guten Tag.",
        "Dann oeffnete er die Tuer und blickte in den Raum.",
    ]
    assert tts_backend.spoken_texts == [
        "Er sagte Guten Tag.",
        "Dann oeffnete er die Tuer und blickte in den Raum.",
    ]
    assert tts_backend.synthesized_texts == tts_backend.spoken_texts
    assert any("Starte Analyse von left" in status for status in statuses)
    assert any("Sende TTS-Block an Server" in status for status in statuses)
    assert any("Starte Wiedergabe" in status for status in statuses)
    assert result.timings["total_pipeline_sec"] >= 0.0
    assert "input_load_sec" in result.timings
    assert result.tts_metrics is not None
    assert result.tts_metrics.time_to_first_audio_sec is not None
    assert result.tts_metrics.time_to_first_playback_sec is not None
    assert result.tts_metrics.queued_blocks == 2
    assert all("page_total_sec" in page.timings for page in result.pages)


def test_pipeline_batches_multiple_complete_sentences_for_live_tts(tmp_path: Path) -> None:
    pipeline = ABRPipeline(ocr_backend=_DummyOCRBackend())
    tts_backend = _RecordingTTSBackend()

    page_inputs = [
        PageInput(page_id="page_1", source_path=tmp_path / "left.jpg", image=None),
        PageInput(page_id="page_2", source_path=tmp_path / "right.jpg", image=None),
    ]

    analyses = [
        _page_analysis(
            page_id="page_1",
            source_path=page_inputs[0].source_path,
            paragraphs=["Eins. Zwei. Drei."],
            slot="left",
        ),
        _page_analysis(
            page_id="page_2",
            source_path=page_inputs[1].source_path,
            paragraphs=["Vier."],
            slot="right",
        ),
    ]

    def _fake_process_page(page_input, index: int, language: str) -> PageAnalysis:
        return analyses[index]

    from abr import pipeline as pipeline_module

    original_loader = pipeline_module.load_page_inputs
    original_process_page = pipeline._process_page
    try:
        pipeline_module.load_page_inputs = lambda paths: page_inputs
        pipeline._process_page = _fake_process_page
        result = pipeline.run(["left.jpg", "right.jpg"], speak=True, tts_backend=tts_backend)
    finally:
        pipeline_module.load_page_inputs = original_loader
        pipeline._process_page = original_process_page

    assert [chunk.text for chunk in result.reading_chunks] == ["Eins.", "Zwei.", "Drei.", "Vier."]
    assert tts_backend.spoken_texts == ["Eins. Zwei. Drei.", "Vier."]
    assert tts_backend.synthesized_texts == ["Eins. Zwei. Drei.", "Vier."]
    assert result.tts_metrics is not None
    assert result.tts_metrics.queued_blocks == 2
    assert result.tts_metrics.queued_chars == len("Eins. Zwei. Drei.") + len("Vier.")


def test_pipeline_respects_smaller_live_tts_batches(tmp_path: Path) -> None:
    pipeline = ABRPipeline(ocr_backend=_DummyOCRBackend())
    tts_backend = _RecordingTTSBackend()

    page_inputs = [
        PageInput(page_id="page_1", source_path=tmp_path / "left.jpg", image=None),
    ]
    analyses = [
        _page_analysis(
            page_id="page_1",
            source_path=page_inputs[0].source_path,
            paragraphs=["Eins.", "Zwei.", "Drei.", "Vier."],
            slot="left",
        ),
    ]

    def _fake_process_page(page_input, index: int, language: str) -> PageAnalysis:
        return analyses[index]

    from abr import pipeline as pipeline_module

    original_loader = pipeline_module.load_page_inputs
    original_process_page = pipeline._process_page
    try:
        pipeline_module.load_page_inputs = lambda paths: page_inputs
        pipeline._process_page = _fake_process_page
        result = pipeline.run(["left.jpg"], speak=True, tts_backend=tts_backend, live_tts_max_chars=11)
    finally:
        pipeline_module.load_page_inputs = original_loader
        pipeline._process_page = original_process_page

    assert tts_backend.spoken_texts == ["Eins. Zwei.", "Drei. Vier."]
    assert result.tts_metrics is not None
    assert result.tts_metrics.queued_blocks == 2


def test_pipeline_writes_machine_readable_timings_to_report(tmp_path: Path) -> None:
    pipeline = ABRPipeline(ocr_backend=_DummyOCRBackend())

    page_inputs = [
        PageInput(page_id="page_1", source_path=tmp_path / "left.jpg", image=None),
        PageInput(page_id="page_2", source_path=tmp_path / "right.jpg", image=None),
    ]

    analyses = [
        _page_analysis(
            page_id="page_1",
            source_path=page_inputs[0].source_path,
            paragraphs=["Links."],
            slot="left",
        ),
        _page_analysis(
            page_id="page_2",
            source_path=page_inputs[1].source_path,
            paragraphs=["Rechts."],
            slot="right",
        ),
    ]

    def _fake_process_page(page_input, index: int, language: str) -> PageAnalysis:
        analysis = analyses[index]
        analysis.timings = {
            "preprocessing_sec": 0.1 + index,
            "orientation_sec": 0.2 + index,
            "ocr_sec": 0.15 + index,
            "orientation_ocr_0_sec": 0.07 + index,
            "orientation_ocr_180_sec": 0.08 + index,
            "layout_sec": 0.05 + index,
            "debug_artifacts_sec": 0.01 + index,
        }
        return analysis

    from abr import pipeline as pipeline_module

    original_loader = pipeline_module.load_page_inputs
    original_process_page = pipeline._process_page
    try:
        pipeline_module.load_page_inputs = lambda paths: page_inputs
        pipeline._process_page = _fake_process_page
        result = pipeline.run(["left.jpg", "right.jpg"], output_dir=tmp_path / "out")
    finally:
        pipeline_module.load_page_inputs = original_loader
        pipeline._process_page = original_process_page

    assert result.report_path is not None
    payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert "pipeline_timings" in payload
    assert "text_assembly_sec" in payload["pipeline_timings"]
    assert "input_load_sec" in payload["pipeline_timings"]
    assert "report_write_sec" in payload["pipeline_timings"]
    assert payload["pages"][0]["timings"]["preprocessing_sec"] == 0.1
    assert payload["pages"][1]["timings"]["ocr_sec"] == 1.15
    assert payload["pages"][0]["timings"]["orientation_ocr_0_sec"] == 0.07
    assert payload["pages"][1]["timings"]["debug_artifacts_sec"] == 1.01
    assert payload["tts"] is None
