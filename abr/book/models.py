from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


JsonDict = dict[str, Any]


@dataclass(slots=True)
class PageChapterMarker:
    line_index: int
    chapter_number: int | None = None
    chapter_heading: str | None = None
    consumed_line_count: int = 1
    detection_kind: str = "unknown"

    def to_dict(self) -> JsonDict:
        return {
            "line_index": self.line_index,
            "chapter_number": self.chapter_number,
            "chapter_heading": self.chapter_heading,
            "consumed_line_count": self.consumed_line_count,
            "detection_kind": self.detection_kind,
        }

    @classmethod
    def from_dict(cls, payload: JsonDict) -> PageChapterMarker:
        return cls(
            line_index=int(payload["line_index"]),
            chapter_number=_optional_int(payload.get("chapter_number")),
            chapter_heading=_optional_str(payload.get("chapter_heading")),
            consumed_line_count=int(payload.get("consumed_line_count", 1)),
            detection_kind=str(payload.get("detection_kind", "unknown")),
        )


@dataclass(slots=True)
class BookRecord:
    tag_id: str
    created_at: str
    last_seen_at: str
    title: str | None = None
    author: str | None = None
    language: str | None = None

    def to_dict(self) -> JsonDict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: JsonDict) -> BookRecord:
        return cls(
            tag_id=str(payload["tag_id"]),
            created_at=str(payload["created_at"]),
            last_seen_at=str(payload["last_seen_at"]),
            title=_optional_str(payload.get("title")),
            author=_optional_str(payload.get("author")),
            language=_optional_str(payload.get("language")),
        )


@dataclass(slots=True)
class ScanRecord:
    scan_id: str
    created_at: str
    session_dir: Path
    capture_dir: Path | None = None
    ocr_dir: Path | None = None
    report_path: Path | None = None
    left_page_id: str | None = None
    right_page_id: str | None = None
    metadata: JsonDict = field(default_factory=dict)

    def to_dict(self) -> JsonDict:
        return {
            "scan_id": self.scan_id,
            "created_at": self.created_at,
            "session_dir": str(self.session_dir),
            "capture_dir": str(self.capture_dir) if self.capture_dir else None,
            "ocr_dir": str(self.ocr_dir) if self.ocr_dir else None,
            "report_path": str(self.report_path) if self.report_path else None,
            "left_page_id": self.left_page_id,
            "right_page_id": self.right_page_id,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, payload: JsonDict) -> ScanRecord:
        return cls(
            scan_id=str(payload["scan_id"]),
            created_at=str(payload["created_at"]),
            session_dir=Path(str(payload["session_dir"])),
            capture_dir=_optional_path(payload.get("capture_dir")),
            ocr_dir=_optional_path(payload.get("ocr_dir")),
            report_path=_optional_path(payload.get("report_path")),
            left_page_id=_optional_str(payload.get("left_page_id")),
            right_page_id=_optional_str(payload.get("right_page_id")),
            metadata=dict(payload.get("metadata", {})),
        )


@dataclass(slots=True)
class PageRecord:
    page_id: str
    scan_id: str
    created_at: str
    side: str
    clean_text: str
    speak_text: str
    page_number: int | None = None
    chapter_number: int | None = None
    chapter_heading: str | None = None
    chapter_markers: list[PageChapterMarker] = field(default_factory=list)
    tail_fragment: str | None = None
    source_report_path: Path | None = None
    metadata: JsonDict = field(default_factory=dict)

    def to_dict(self) -> JsonDict:
        return {
            "page_id": self.page_id,
            "scan_id": self.scan_id,
            "created_at": self.created_at,
            "side": self.side,
            "clean_text": self.clean_text,
            "speak_text": self.speak_text,
            "page_number": self.page_number,
            "chapter_number": self.chapter_number,
            "chapter_heading": self.chapter_heading,
            "chapter_markers": [marker.to_dict() for marker in self.chapter_markers],
            "tail_fragment": self.tail_fragment,
            "source_report_path": str(self.source_report_path) if self.source_report_path else None,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, payload: JsonDict) -> PageRecord:
        return cls(
            page_id=str(payload["page_id"]),
            scan_id=str(payload["scan_id"]),
            created_at=str(payload["created_at"]),
            side=str(payload["side"]),
            clean_text=str(payload.get("clean_text", "")),
            speak_text=str(payload.get("speak_text", "")),
            page_number=_optional_int(payload.get("page_number")),
            chapter_number=_optional_int(payload.get("chapter_number")),
            chapter_heading=_optional_str(payload.get("chapter_heading")),
            chapter_markers=[
                PageChapterMarker.from_dict(entry)
                for entry in payload.get("chapter_markers", [])
            ],
            tail_fragment=_optional_str(payload.get("tail_fragment")),
            source_report_path=_optional_path(payload.get("source_report_path")),
            metadata=dict(payload.get("metadata", {})),
        )


@dataclass(slots=True)
class ChapterRecord:
    chapter_id: str
    created_at: str
    completed_at: str
    text_path: Path
    page_ids: list[str]
    page_numbers: list[int]
    chapter_number: int | None = None
    chapter_heading: str | None = None
    start_page: int | None = None
    end_page: int | None = None
    summary_path: Path | None = None
    metadata: JsonDict = field(default_factory=dict)

    def to_dict(self) -> JsonDict:
        return {
            "chapter_id": self.chapter_id,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "text_path": str(self.text_path),
            "page_ids": self.page_ids,
            "page_numbers": self.page_numbers,
            "chapter_number": self.chapter_number,
            "chapter_heading": self.chapter_heading,
            "start_page": self.start_page,
            "end_page": self.end_page,
            "summary_path": str(self.summary_path) if self.summary_path else None,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, payload: JsonDict) -> ChapterRecord:
        return cls(
            chapter_id=str(payload["chapter_id"]),
            created_at=str(payload["created_at"]),
            completed_at=str(payload["completed_at"]),
            text_path=Path(str(payload["text_path"])),
            page_ids=[str(page_id) for page_id in payload.get("page_ids", [])],
            page_numbers=[int(number) for number in payload.get("page_numbers", [])],
            chapter_number=_optional_int(payload.get("chapter_number")),
            chapter_heading=_optional_str(payload.get("chapter_heading")),
            start_page=_optional_int(payload.get("start_page")),
            end_page=_optional_int(payload.get("end_page")),
            summary_path=_optional_path(payload.get("summary_path")),
            metadata=dict(payload.get("metadata", {})),
        )


@dataclass(slots=True)
class SummaryRecord:
    summary_id: str
    summary_type: str
    updated_at: str
    text: str
    source_chapter_ids: list[str] = field(default_factory=list)
    model_name: str | None = None
    metadata: JsonDict = field(default_factory=dict)

    def to_dict(self) -> JsonDict:
        return {
            "summary_id": self.summary_id,
            "summary_type": self.summary_type,
            "updated_at": self.updated_at,
            "text": self.text,
            "source_chapter_ids": self.source_chapter_ids,
            "model_name": self.model_name,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, payload: JsonDict) -> SummaryRecord:
        return cls(
            summary_id=str(payload["summary_id"]),
            summary_type=str(payload["summary_type"]),
            updated_at=str(payload["updated_at"]),
            text=str(payload.get("text", "")),
            source_chapter_ids=[str(chapter_id) for chapter_id in payload.get("source_chapter_ids", [])],
            model_name=_optional_str(payload.get("model_name")),
            metadata=dict(payload.get("metadata", {})),
        )


@dataclass(slots=True)
class BookSession:
    tag_id: str
    root_dir: Path
    record: BookRecord


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)


def _optional_path(value: object) -> Path | None:
    if value is None:
        return None
    return Path(str(value))
