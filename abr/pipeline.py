from __future__ import annotations

import tempfile
import time
from queue import Queue
from threading import Thread
from pathlib import Path
from typing import Callable, Sequence

from abr.debug import DebugArtifactWriter
from abr.debug.visualization import DebugVisualizer
from abr.input import load_page_inputs
from abr.layout import BasicLayoutAnalyzer
from abr.models import PageAnalysis, PipelineResult, PreprocessArtifacts, TTSMetrics
from abr.ocr.base import OCRBackend
from abr.orientation import OCRBasedOrientationDetector
from abr.reporting import ResultWriter
from abr.text_logic import ReadingStreamBuilder
from abr.tts.base import TTSBackend


class ABRPipeline:
    def __init__(
        self,
        ocr_backend: OCRBackend,
        debug_writer: DebugArtifactWriter | None = None,
    ) -> None:
        self.ocr_backend = ocr_backend
        self.orientation_detector = OCRBasedOrientationDetector(ocr_backend)
        self.layout_analyzer = BasicLayoutAnalyzer()
        self.debug_writer = debug_writer or DebugArtifactWriter(None)
        self.debug_visualizer = DebugVisualizer()
        self.result_writer = ResultWriter()

    def run(
        self,
        image_paths: Sequence[str | Path],
        language: str = "de",
        speak: bool = False,
        tts_backend: TTSBackend | None = None,
        output_dir: Path | None = None,
        audio_output_path: Path | None = None,
        status_callback: Callable[[str], None] | None = None,
        live_tts_max_chars: int = 4000,
    ) -> PipelineResult:
        pipeline_started = time.monotonic()
        load_started = time.monotonic()
        page_inputs = load_page_inputs(Path(path) for path in image_paths)
        pipeline_timings: dict[str, float] = {
            "input_load_sec": time.monotonic() - load_started,
        }
        stream_builder = ReadingStreamBuilder()
        self._emit_status(status_callback, f"{len(page_inputs)} Seite(n) geladen.")
        speaker = _AsyncSpeaker(tts_backend, max_batch_chars=live_tts_max_chars, status_callback=status_callback) if speak else None
        if speaker:
            self._emit_status(status_callback, "Live-TTS gestartet.")
            speaker.start()

        page_analyses = []
        ordered_pages = []
        reading_chunks = []
        try:
            for index, page_input in enumerate(page_inputs):
                slot = self._slot_name(index)
                self._emit_status(status_callback, f"Starte Analyse von {slot} ({page_input.source_path.name}).")
                page_started = time.monotonic()
                page_analysis = self._process_page(page_input, index, language)
                page_analysis.timings["page_total_sec"] = time.monotonic() - page_started
                page_analyses.append(page_analysis)
                ordered_pages.append(page_analysis)
                self._emit_status(
                    status_callback,
                    f"Analyse von {slot} abgeschlossen: {len(page_analysis.lines)} OCR-Zeilen, {len(page_analysis.paragraphs)} Absatz/Absaetze.",
                )

                page_chunks = stream_builder.consume_page(page_analysis.page_id, page_analysis.paragraphs)
                reading_chunks.extend(page_chunks)
                complete_chunks = [chunk for chunk in page_chunks if chunk.complete]
                if complete_chunks:
                    ready_text = " ".join(chunk.text for chunk in complete_chunks)
                    self._emit_status(
                        status_callback,
                        f"{slot}: {len(complete_chunks)} vollstaendige(s) Segment(e) fuer TTS bereit ({len(ready_text)} Zeichen).",
                    )
                if speaker:
                    speaker.enqueue(page_chunks)

            pending = stream_builder.flush()
            if pending:
                reading_chunks.append(pending)
                self._emit_status(status_callback, "Offenes Satzfragment bleibt ungeprochen im kombinierten Text erhalten.")
        finally:
            if speaker:
                self._emit_status(status_callback, "Warte auf Abschluss von TTS-Download und Wiedergabe.")
                speaker.finish()

        text_assembly_started = time.monotonic()
        combined_text = "\n".join(chunk.text for chunk in reading_chunks)
        speakable_text = "\n".join(chunk.text for chunk in reading_chunks if chunk.complete)
        pipeline_timings["text_assembly_sec"] = time.monotonic() - text_assembly_started

        file_synthesis_sec: float | None = None
        if audio_output_path:
            if tts_backend is None:
                raise RuntimeError("TTS requested but no backend was provided.")
            if audio_output_path:
                self._emit_status(status_callback, f"Erzeuge Audiodatei: {audio_output_path.name}")
                file_synthesis_started = time.monotonic()
                tts_backend.synthesize_to_file(speakable_text or combined_text, audio_output_path)
                file_synthesis_sec = time.monotonic() - file_synthesis_started
                self._emit_status(status_callback, f"Audiodatei geschrieben: {audio_output_path.name}")

        pipeline_timings["page_processing_sec"] = sum(page.timings.get("page_total_sec", 0.0) for page in page_analyses)
        pipeline_timings["total_pipeline_sec"] = time.monotonic() - pipeline_started
        tts_metrics = speaker.metrics if speaker else None
        if tts_metrics and file_synthesis_sec is not None:
            tts_metrics.file_synthesis_sec = file_synthesis_sec
        elif file_synthesis_sec is not None:
            tts_metrics = TTSMetrics(file_synthesis_sec=file_synthesis_sec)

        result = PipelineResult(
            pages=page_analyses,
            ordered_pages=ordered_pages,
            reading_chunks=reading_chunks,
            combined_text=combined_text,
            timings=pipeline_timings,
            tts_metrics=tts_metrics,
            output_dir=output_dir,
            audio_path=audio_output_path,
        )
        if output_dir:
            report_started = time.monotonic()
            _, report_path = self.result_writer.write(result, output_dir)
            result.timings["report_write_sec"] = time.monotonic() - report_started
            result.timings["total_pipeline_sec"] = time.monotonic() - pipeline_started
            _, report_path = self.result_writer.write(result, output_dir)
            result.report_path = report_path
            self._emit_status(status_callback, f"Report geschrieben: {report_path}")
        return result

    @staticmethod
    def _emit_status(status_callback: Callable[[str], None] | None, message: str) -> None:
        if status_callback is not None:
            status_callback(message)

    def _process_page(self, page_input, index: int, language: str) -> PageAnalysis:
        slot = self._slot_name(index)
        page_timings: dict[str, float] = {}
        preprocessing = _build_passthrough_preprocessing(page_input.image)
        page_timings["preprocessing_sec"] = 0.0
        debug_paths: dict[str, Path] = {}

        orientation_started = time.monotonic()
        orientation_result = self.orientation_detector.detect(preprocessing.ocr_input, language=language)
        page_timings["orientation_sec"] = time.monotonic() - orientation_started
        page_timings["ocr_sec"] = orientation_result.timings["ocr_total_sec"]
        page_timings["orientation_overhead_sec"] = max(0.0, page_timings["orientation_sec"] - page_timings["ocr_sec"])
        page_timings["orientation_rotate_total_sec"] = orientation_result.timings.get("rotate_total_sec", 0.0)
        page_timings["orientation_ocr_0_sec"] = orientation_result.timings.get("ocr_0_sec", 0.0)
        page_timings["orientation_ocr_180_sec"] = orientation_result.timings.get("ocr_180_sec", 0.0)
        page_timings["orientation_rotate_0_sec"] = orientation_result.timings.get("rotate_0_sec", 0.0)
        page_timings["orientation_rotate_180_sec"] = orientation_result.timings.get("rotate_180_sec", 0.0)
        page_timings["orientation_total_internal_sec"] = orientation_result.timings.get("total_sec", 0.0)
        orientation = orientation_result.candidate
        rotated_image = orientation_result.rotated_image
        self._maybe_store(debug_paths, page_input.page_id, "05_oriented", rotated_image)

        lines = orientation.lines
        layout_started = time.monotonic()
        blocks, page_number, paragraphs = self.layout_analyzer.analyze(lines)
        page_timings["layout_sec"] = time.monotonic() - layout_started
        if self.debug_writer.enabled:
            debug_started = time.monotonic()
            overlay_started = time.monotonic()
            ocr_overlay = self.debug_visualizer.draw_ocr_overlay(rotated_image, lines)
            page_timings["debug_ocr_overlay_sec"] = time.monotonic() - overlay_started
            self._maybe_store(debug_paths, page_input.page_id, "06_ocr_overlay", ocr_overlay)
            lines_started = time.monotonic()
            lines_overlay = self.debug_visualizer.draw_lines(rotated_image, lines)
            page_timings["debug_lines_overlay_sec"] = time.monotonic() - lines_started
            self._maybe_store(debug_paths, page_input.page_id, "07_ocr_lines", lines_overlay)
            layout_started = time.monotonic()
            layout_overlay = self.debug_visualizer.draw_layout(rotated_image, blocks)
            page_timings["debug_layout_overlay_sec"] = time.monotonic() - layout_started
            self._maybe_store(debug_paths, page_input.page_id, "08_layout", layout_overlay)
            page_timings["debug_artifacts_sec"] = time.monotonic() - debug_started
        else:
            page_timings["debug_artifacts_sec"] = 0.0
        text = "\n\n".join(paragraphs)
        return PageAnalysis(
            page_id=page_input.page_id,
            source_path=page_input.source_path,
            slot=slot,
            rotated_image=rotated_image,
            preprocessing=preprocessing,
            orientation=orientation,
            lines=lines,
            layout_blocks=blocks,
            paragraphs=paragraphs,
            text=text,
            page_number=page_number,
            debug_paths=debug_paths,
            timings=page_timings,
        )

    def _maybe_store(self, debug_paths: dict[str, Path], page_id: str, stage: str, image) -> None:
        path = self.debug_writer.write_image(page_id, stage, image)
        if path:
            debug_paths[stage] = path

    @staticmethod
    def _slot_name(index: int) -> str:
        if index == 0:
            return "left"
        if index == 1:
            return "right"
        return f"slot_{index + 1}"


def _build_passthrough_preprocessing(image) -> PreprocessArtifacts:
    return PreprocessArtifacts(
        gray=None,
        enhanced=None,
        sharpened=None,
        binary=None,
        ocr_input=image.copy(),
    )


class _AsyncSpeaker:
    def __init__(
        self,
        tts_backend: TTSBackend | None,
        max_batch_chars: int = 4000,
        status_callback: Callable[[str], None] | None = None,
    ) -> None:
        if tts_backend is None:
            raise RuntimeError("TTS playback requested but no backend was provided.")
        if not tts_backend.supports_file_playback():
            raise RuntimeError("This TTS backend does not support parallel live playback.")
        self.tts_backend = tts_backend
        self.max_batch_chars = max_batch_chars
        self.status_callback = status_callback
        self.text_queue: Queue[str | None] = Queue()
        self.audio_queue: Queue[Path | None] = Queue()
        self.error: BaseException | None = None
        self.started_at: float | None = None
        self.metrics = TTSMetrics()
        self.synth_worker = Thread(target=self._synthesize_loop, name="abr-tts-synth", daemon=True)
        self.play_worker = Thread(target=self._play_loop, name="abr-tts-play", daemon=True)

    def start(self) -> None:
        self.started_at = time.monotonic()
        self.synth_worker.start()
        self.play_worker.start()

    def enqueue(self, chunks) -> None:
        self._raise_if_failed()
        complete_texts = [chunk.text for chunk in chunks if chunk.complete]
        for batch in self._batch_texts(complete_texts):
            self._emit_status(f"TTS-Block eingereiht ({len(batch)} Zeichen).")
            self.metrics.queued_blocks += 1
            self.metrics.queued_chars += len(batch)
            self.text_queue.put(batch)

    def finish(self) -> None:
        self.text_queue.put(None)
        self.synth_worker.join()
        self.play_worker.join()
        if self.started_at is not None:
            self.metrics.total_live_tts_sec = time.monotonic() - self.started_at
        self._raise_if_failed()

    def _synthesize_loop(self) -> None:
        try:
            while True:
                text = self.text_queue.get()
                if text is None:
                    self.audio_queue.put(None)
                    return
                self._emit_status(f"Sende TTS-Block an Server ({len(text)} Zeichen).")
                with tempfile.NamedTemporaryFile(
                    suffix=self.tts_backend.live_audio_suffix(),
                    delete=False,
                ) as handle:
                    output_path = Path(handle.name)
                synth_started = time.monotonic()
                self.tts_backend.synthesize_to_file(text, output_path)
                synth_duration = time.monotonic() - synth_started
                self.metrics.synthesized_blocks += 1
                self.metrics.synthesized_chars += len(text)
                self.metrics.synth_time_sec += synth_duration
                if self.metrics.time_to_first_audio_sec is None and self.started_at is not None:
                    self.metrics.time_to_first_audio_sec = time.monotonic() - self.started_at
                self._emit_status(f"Audio empfangen: {output_path.name}")
                self.audio_queue.put(output_path)
        except BaseException as exc:  # pragma: no cover - defensive thread propagation
            self.error = exc
            self.audio_queue.put(None)

    def _play_loop(self) -> None:
        try:
            while True:
                audio_path = self.audio_queue.get()
                if audio_path is None:
                    return
                try:
                    play_started = time.monotonic()
                    if self.metrics.time_to_first_playback_sec is None and self.started_at is not None:
                        self.metrics.time_to_first_playback_sec = play_started - self.started_at
                    self._emit_status(f"Starte Wiedergabe: {audio_path.name}")
                    self.tts_backend.play_file(audio_path)
                    self.metrics.played_blocks += 1
                    self.metrics.playback_time_sec += time.monotonic() - play_started
                    self._emit_status(f"Wiedergabe abgeschlossen: {audio_path.name}")
                finally:
                    audio_path.unlink(missing_ok=True)
        except BaseException as exc:  # pragma: no cover - defensive thread propagation
            self.error = exc

    def _raise_if_failed(self) -> None:
        if self.error is not None:
            raise RuntimeError("Background TTS playback failed.") from self.error

    def _batch_texts(self, texts: list[str]) -> list[str]:
        batches: list[str] = []
        current: list[str] = []
        current_length = 0

        for text in texts:
            text = text.strip()
            if not text:
                continue

            extra_length = len(text) if not current else len(text) + 1
            if current and current_length + extra_length > self.max_batch_chars:
                batches.append(" ".join(current))
                current = [text]
                current_length = len(text)
                continue

            current.append(text)
            current_length += extra_length

        if current:
            batches.append(" ".join(current))
        return batches

    def _emit_status(self, message: str) -> None:
        if self.status_callback is not None:
            self.status_callback(message)
