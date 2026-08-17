from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import numpy as np
except ImportError:  # pragma: no cover - fallback for lightweight environments
    np = None

Point = tuple[int, int]
BBox = tuple[Point, Point, Point, Point]
ImageArray = Any if np is None else np.ndarray


@dataclass(slots=True)
class OCRLine:
    text: str
    confidence: float
    bbox: BBox
    source_index: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def top(self) -> int:
        return min(point[1] for point in self.bbox)

    @property
    def bottom(self) -> int:
        return max(point[1] for point in self.bbox)

    @property
    def left(self) -> int:
        return min(point[0] for point in self.bbox)

    @property
    def right(self) -> int:
        return max(point[0] for point in self.bbox)

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


@dataclass(slots=True)
class LayoutBlock:
    kind: str
    text: str
    bbox: BBox
    line_indices: list[int]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PageInput:
    page_id: str
    source_path: Path
    image: ImageArray


@dataclass(slots=True)
class PreprocessArtifacts:
    gray: ImageArray
    enhanced: ImageArray
    sharpened: ImageArray
    binary: ImageArray
    ocr_input: ImageArray


@dataclass(slots=True)
class OrientationCandidate:
    rotation_deg: int
    score: float
    lines: list[OCRLine]
    reason: str


@dataclass(slots=True)
class PageAnalysis:
    page_id: str
    source_path: Path
    slot: str
    rotated_image: ImageArray
    preprocessing: PreprocessArtifacts
    orientation: OrientationCandidate
    lines: list[OCRLine]
    layout_blocks: list[LayoutBlock]
    paragraphs: list[str]
    text: str
    page_number: int | None = None
    debug_paths: dict[str, Path] = field(default_factory=dict)
    timings: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class ReadingChunk:
    text: str
    complete: bool
    source_pages: list[str]


@dataclass(slots=True)
class TTSMetrics:
    queued_blocks: int = 0
    queued_chars: int = 0
    synthesized_blocks: int = 0
    synthesized_chars: int = 0
    played_blocks: int = 0
    synth_time_sec: float = 0.0
    playback_time_sec: float = 0.0
    time_to_first_audio_sec: float | None = None
    time_to_first_playback_sec: float | None = None
    total_live_tts_sec: float | None = None
    file_synthesis_sec: float | None = None


@dataclass(slots=True)
class PipelineResult:
    pages: list[PageAnalysis]
    ordered_pages: list[PageAnalysis]
    reading_chunks: list[ReadingChunk]
    combined_text: str
    timings: dict[str, float] = field(default_factory=dict)
    tts_metrics: TTSMetrics | None = None
    output_dir: Path | None = None
    report_path: Path | None = None
    audio_path: Path | None = None
