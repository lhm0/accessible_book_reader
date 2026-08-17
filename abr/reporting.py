from __future__ import annotations

import json
from pathlib import Path

from abr.models import PipelineResult


class ResultWriter:
    def write(self, result: PipelineResult, output_dir: Path) -> tuple[Path, Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        text_path = output_dir / "combined_text.txt"
        text_path.write_text(result.combined_text + ("\n" if result.combined_text else ""), encoding="utf-8")

        report_path = output_dir / "report.json"
        report = {
            "pages": [
                {
                    "page_id": page.page_id,
                    "slot": page.slot,
                    "source_path": str(page.source_path),
                    "rotation_deg": page.orientation.rotation_deg,
                    "orientation_score": page.orientation.score,
                    "orientation_reason": page.orientation.reason,
                    "page_number": page.page_number,
                    "ocr_line_count": len(page.lines),
                    "avg_confidence": _avg_confidence(page.lines),
                    "paragraphs": page.paragraphs,
                    "layout_blocks": [
                        {
                            "kind": block.kind,
                            "text": block.text,
                            "line_indices": block.line_indices,
                            "bbox": block.bbox,
                        }
                        for block in page.layout_blocks
                    ],
                    "ocr_lines": [
                        {
                            "text": line.text,
                            "confidence": line.confidence,
                            "bbox": line.bbox,
                        }
                        for line in page.lines
                    ],
                    "debug_paths": {stage: str(path) for stage, path in page.debug_paths.items()},
                    "timings": page.timings,
                }
                for page in result.pages
            ],
            "reading_chunks": [
                {
                    "text": chunk.text,
                    "complete": chunk.complete,
                    "source_pages": chunk.source_pages,
                }
                for chunk in result.reading_chunks
            ],
            "combined_text": result.combined_text,
            "pipeline_timings": result.timings,
            "tts": _serialize_tts_metrics(result),
            "audio_path": str(result.audio_path) if result.audio_path else None,
        }
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        return text_path, report_path


def _avg_confidence(lines) -> float:
    return sum(line.confidence for line in lines) / max(1, len(lines))


def _serialize_tts_metrics(result: PipelineResult) -> dict[str, float | int | None] | None:
    if result.tts_metrics is None:
        return None

    metrics = result.tts_metrics
    return {
        "queued_blocks": metrics.queued_blocks,
        "queued_chars": metrics.queued_chars,
        "synthesized_blocks": metrics.synthesized_blocks,
        "synthesized_chars": metrics.synthesized_chars,
        "played_blocks": metrics.played_blocks,
        "synth_time_sec": metrics.synth_time_sec,
        "playback_time_sec": metrics.playback_time_sec,
        "time_to_first_audio_sec": metrics.time_to_first_audio_sec,
        "time_to_first_playback_sec": metrics.time_to_first_playback_sec,
        "total_live_tts_sec": metrics.total_live_tts_sec,
        "file_synthesis_sec": metrics.file_synthesis_sec,
    }
