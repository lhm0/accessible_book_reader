from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path

from abr.book.models import ChapterRecord, PageChapterMarker, PageRecord
from abr.book.store import BookStore, normalize_tag_id, utc_now


_STATE_FILENAME = "chapter_assembler_state.json"
_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n", re.MULTILINE)
_SENTENCE_END_RE = re.compile(r"[.!?…](?:[\"'»”)\]]+)?\s*$")
_LAST_SENTENCE_END_RE = re.compile(r"[.!?…](?:[\"'»”)\]]+)?")


def _require_consistent_book_pages(
    store: BookStore,
    tag_id: str,
    pages: list[PageRecord],
) -> str:
    book = store.load_book(tag_id)
    if book is None:
        raise RuntimeError(f"Buch nicht gefunden: {tag_id}")
    book_language = book.language or "de"
    for page in pages:
        raw_page_language = page.metadata.get("language")
        page_language = raw_page_language if isinstance(raw_page_language, str) else "de"
        if page_language != book_language:
            raise RuntimeError(
                f"Gemischte Buchdaten fuer {tag_id}: Seite {page.page_id} hat Sprache "
                f"{page_language}, das Buch ist als {book_language} gespeichert."
            )
    return book_language


@dataclass(frozen=True, slots=True)
class ChapterAssemblerConfig:
    min_pages: int = 10
    max_pages: int = 20
    state_filename: str = _STATE_FILENAME

    def __post_init__(self) -> None:
        if self.min_pages <= 0:
            raise ValueError("min_pages muss > 0 sein.")
        if self.max_pages < self.min_pages:
            raise ValueError("max_pages muss >= min_pages sein.")


@dataclass(frozen=True, slots=True)
class ChapterBoundary:
    page_id: str
    offset: int = 0
    page_number: int | None = None
    side: str | None = None
    scan_id: str | None = None

    @classmethod
    def from_page(cls, page: PageRecord, offset: int = 0) -> ChapterBoundary:
        return cls(
            page_id=page.page_id,
            offset=max(offset, 0),
            page_number=page.page_number,
            side=page.side,
            scan_id=page.scan_id,
        )

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> ChapterBoundary:
        return cls(
            page_id=str(payload["page_id"]),
            offset=int(payload.get("offset", 0)),
            page_number=_optional_int(payload.get("page_number")),
            side=_optional_str(payload.get("side")),
            scan_id=_optional_str(payload.get("scan_id")),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "page_id": self.page_id,
            "offset": self.offset,
            "page_number": self.page_number,
            "side": self.side,
            "scan_id": self.scan_id,
        }


@dataclass(frozen=True, slots=True)
class ChapterAssemblyResult:
    tag_id: str
    created_chapters: tuple[ChapterRecord, ...]


@dataclass(frozen=True, slots=True)
class PendingChapterContent:
    tag_id: str
    text: str
    page_ids: tuple[str, ...]
    page_numbers: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class _AssemblerState:
    current_start: ChapterBoundary
    next_sequence: int

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> _AssemblerState:
        current_start = payload.get("current_start")
        if not isinstance(current_start, dict):
            raise RuntimeError("Ungueltiger ChapterAssembler-State: current_start fehlt.")
        return cls(
            current_start=ChapterBoundary.from_dict(current_start),
            next_sequence=int(payload.get("next_sequence", 1)),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "current_start": self.current_start.to_dict(),
            "next_sequence": self.next_sequence,
        }


@dataclass(frozen=True, slots=True)
class _ResolvedBoundary:
    boundary: ChapterBoundary
    page_index: int
    page: PageRecord
    offset: int


@dataclass(frozen=True, slots=True)
class _BoundaryCandidate:
    boundary: ChapterBoundary
    next_start: ChapterBoundary
    boundary_kind: str
    page_index: int
    metadata: dict[str, object]


class ChapterAssembler:
    def __init__(self, store: BookStore, config: ChapterAssemblerConfig = ChapterAssemblerConfig()) -> None:
        self.store = store
        self.config = config

    def assemble_available_chapters(self, tag_id: str) -> ChapterAssemblyResult:
        normalized_tag_id = normalize_tag_id(tag_id)
        pages = _sort_pages_for_assembly(self.store.list_pages(normalized_tag_id))
        book_language = _require_consistent_book_pages(self.store, normalized_tag_id, pages)
        if not pages:
            return ChapterAssemblyResult(tag_id=normalized_tag_id, created_chapters=())

        state = self._load_or_initialize_state(normalized_tag_id, pages)
        created: list[ChapterRecord] = []
        while True:
            pages = _sort_pages_for_assembly(self.store.list_pages(normalized_tag_id))
            if not pages:
                break
            resolved_start = _resolve_boundary(state.current_start, pages)
            state = self._refresh_resolved_start(normalized_tag_id, state, resolved_start)
            candidate = self._find_next_boundary(resolved_start, pages)
            if candidate is None:
                break
            chapter = self._persist_completed_chapter(
                normalized_tag_id,
                pages=pages,
                resolved_start=resolved_start,
                candidate=candidate,
                sequence=state.next_sequence,
                language=book_language,
            )
            created.append(chapter)
            state = _AssemblerState(current_start=candidate.next_start, next_sequence=state.next_sequence + 1)
            self._save_state(normalized_tag_id, state)
        return ChapterAssemblyResult(tag_id=normalized_tag_id, created_chapters=tuple(created))

    def collect_pending_content(self, tag_id: str) -> PendingChapterContent:
        """Return text from the persisted open-section boundary without storing a chapter."""
        normalized_tag_id = normalize_tag_id(tag_id)
        pages = _sort_pages_for_assembly(self.store.list_pages(normalized_tag_id))
        _require_consistent_book_pages(self.store, normalized_tag_id, pages)
        if not pages:
            return PendingChapterContent(
                tag_id=normalized_tag_id,
                text="",
                page_ids=(),
                page_numbers=(),
            )
        state = self._load_or_initialize_state(normalized_tag_id, pages)
        resolved_start = _resolve_boundary(state.current_start, pages)
        self._refresh_resolved_start(normalized_tag_id, state, resolved_start)
        terminal_page_index = len(pages) - 1
        terminal_page = pages[terminal_page_index]
        segments = _collect_chapter_segments(
            pages,
            start=resolved_start,
            end_page_index=terminal_page_index,
            end_boundary=ChapterBoundary.from_page(terminal_page, offset=len(terminal_page.clean_text)),
        )
        included_pages = [page for page, _text in segments]
        return PendingChapterContent(
            tag_id=normalized_tag_id,
            text="\n\n".join(text for _page, text in segments).strip(),
            page_ids=tuple(page.page_id for page in included_pages),
            page_numbers=tuple(
                page.page_number for page in included_pages if page.page_number is not None
            ),
        )

    def _persist_completed_chapter(
        self,
        tag_id: str,
        *,
        pages: list[PageRecord],
        resolved_start: _ResolvedBoundary,
        candidate: _BoundaryCandidate,
        sequence: int,
        language: str,
    ) -> ChapterRecord:
        segments = _collect_chapter_segments(
            pages,
            start=resolved_start,
            end_page_index=candidate.page_index,
            end_boundary=candidate.boundary,
        )
        text = "\n\n".join(segment for _page, segment in segments).strip()
        included_pages = [page for page, _segment in segments]
        page_ids = [page.page_id for page in included_pages]
        page_numbers = [page.page_number for page in included_pages if page.page_number is not None]
        terminal_page = included_pages[-1] if included_pages else resolved_start.page
        start_marker = _marker_at_boundary(resolved_start.page, resolved_start.offset)
        created_at = utc_now()
        chapter = ChapterRecord(
            chapter_id=f"chapter_{sequence:04d}",
            created_at=created_at,
            completed_at=created_at,
            text_path=Path("text.txt"),
            page_ids=page_ids,
            page_numbers=page_numbers,
            chapter_number=start_marker.chapter_number if start_marker is not None else None,
            chapter_heading=start_marker.chapter_heading if start_marker is not None else None,
            start_page=page_numbers[0] if page_numbers else resolved_start.page.page_number,
            end_page=page_numbers[-1] if page_numbers else terminal_page.page_number,
            metadata={
                "start_boundary": resolved_start.boundary.to_dict(),
                "end_boundary": candidate.boundary.to_dict(),
                "next_start_boundary": candidate.next_start.to_dict(),
                "boundary_kind": candidate.boundary_kind,
                "boundary_metadata": candidate.metadata,
                "page_span": candidate.page_index - resolved_start.page_index + 1,
                "content_page_count": len(included_pages),
                "language": language,
            },
        )
        self.store.save_chapter(tag_id, chapter, text=text)
        return self.store.load_chapter(tag_id, chapter.chapter_id) or chapter

    def _find_next_boundary(
        self,
        start: _ResolvedBoundary,
        pages: list[PageRecord],
    ) -> _BoundaryCandidate | None:
        max_page_index = min(len(pages) - 1, start.page_index + self.config.max_pages - 1)
        for page_index in range(start.page_index, max_page_index + 1):
            page_span = page_index - start.page_index + 1
            if page_span < self.config.min_pages:
                continue
            page = pages[page_index]
            for marker in page.chapter_markers:
                marker_boundary = _marker_boundary(page, marker)
                if marker_boundary.offset <= 0 and page_index == start.page_index and start.offset >= marker_boundary.offset:
                    continue
                if page_index == start.page_index and marker_boundary.offset <= start.offset:
                    continue
                return _BoundaryCandidate(
                    boundary=marker_boundary,
                    next_start=marker_boundary,
                    boundary_kind="chapter_marker",
                    page_index=page_index,
                    metadata={
                        "chapter_number": marker.chapter_number,
                        "chapter_heading": marker.chapter_heading,
                        "detection_kind": marker.detection_kind,
                        "line_index": marker.line_index,
                    },
                )

        if len(pages) - start.page_index < self.config.max_pages:
            return None

        fallback_page_index = start.page_index + self.config.max_pages - 1
        fallback_page = pages[fallback_page_index]
        fallback_offset = _fallback_boundary_offset(fallback_page.clean_text)
        fallback_boundary = ChapterBoundary.from_page(fallback_page, offset=fallback_offset)
        next_start = ChapterBoundary.from_page(fallback_page, offset=_skip_leading_whitespace(fallback_page.clean_text, fallback_offset))
        return _BoundaryCandidate(
            boundary=fallback_boundary,
            next_start=next_start,
            boundary_kind="fallback_last_complete_paragraph",
            page_index=fallback_page_index,
            metadata={
                "page_id": fallback_page.page_id,
                "page_number": fallback_page.page_number,
                "offset": fallback_offset,
            },
        )

    def _load_or_initialize_state(self, tag_id: str, pages: list[PageRecord]) -> _AssemblerState:
        payload = self.store.load_runtime_state(tag_id, self.config.state_filename)
        if payload is not None:
            return _AssemblerState.from_dict(payload)
        chapters = self.store.list_chapters(tag_id)
        if chapters:
            latest = chapters[-1]
            next_start = latest.metadata.get("next_start_boundary") if isinstance(latest.metadata, dict) else None
            if isinstance(next_start, dict):
                state = _AssemblerState(
                    current_start=ChapterBoundary.from_dict(next_start),
                    next_sequence=_next_sequence_from_chapters(chapters),
                )
                self._save_state(tag_id, state)
                return state
        state = _AssemblerState(
            current_start=ChapterBoundary.from_page(pages[0]),
            next_sequence=_next_sequence_from_chapters(chapters),
        )
        self._save_state(tag_id, state)
        return state

    def _save_state(self, tag_id: str, state: _AssemblerState) -> None:
        self.store.save_runtime_state(tag_id, self.config.state_filename, state.to_dict())

    def _refresh_resolved_start(
        self,
        tag_id: str,
        state: _AssemblerState,
        resolved_start: _ResolvedBoundary,
    ) -> _AssemblerState:
        """Persist the canonical page identity after resolving a replaced placeholder."""
        if state.current_start == resolved_start.boundary:
            return state
        refreshed = _AssemblerState(
            current_start=resolved_start.boundary,
            next_sequence=state.next_sequence,
        )
        self._save_state(tag_id, refreshed)
        return refreshed


def _build_chapter_text(
    pages: list[PageRecord],
    *,
    start: _ResolvedBoundary,
    end_page_index: int,
    end_boundary: ChapterBoundary,
) -> str:
    parts = _collect_chapter_segments(
        pages,
        start=start,
        end_page_index=end_page_index,
        end_boundary=end_boundary,
    )
    return "\n\n".join(segment for _page, segment in parts).strip()


def _collect_chapter_segments(
    pages: list[PageRecord],
    *,
    start: _ResolvedBoundary,
    end_page_index: int,
    end_boundary: ChapterBoundary,
) -> list[tuple[PageRecord, str]]:
    parts: list[tuple[PageRecord, str]] = []
    for page_index in range(start.page_index, end_page_index + 1):
        page = pages[page_index]
        raw_text = page.clean_text
        start_offset = start.offset if page_index == start.page_index else 0
        end_offset = _safe_offset(raw_text, end_boundary.offset) if page_index == end_page_index else len(raw_text)
        if end_offset < start_offset:
            continue
        snippet = raw_text[start_offset:end_offset].strip()
        if snippet:
            parts.append((page, snippet))
    return parts


def _sort_pages_for_assembly(pages: list[PageRecord]) -> list[PageRecord]:
    return sorted(
        pages,
        key=lambda page: (
            page.created_at,
            page.scan_id,
            _page_side_rank(page.side),
            (page.page_number is None),
            page.page_number or 0,
            page.page_id,
        ),
    )


def _page_side_rank(side: str) -> int:
    if side == "left":
        return 0
    if side == "right":
        return 1
    return 2


def _resolve_boundary(boundary: ChapterBoundary, pages: list[PageRecord]) -> _ResolvedBoundary:
    for index, page in enumerate(pages):
        if boundary.page_number is not None and page.page_number == boundary.page_number:
            return _ResolvedBoundary(boundary=ChapterBoundary.from_page(page, offset=boundary.offset), page_index=index, page=page, offset=_safe_offset(page.clean_text, boundary.offset))
    for index, page in enumerate(pages):
        if page.page_id == boundary.page_id:
            return _ResolvedBoundary(boundary=ChapterBoundary.from_page(page, offset=boundary.offset), page_index=index, page=page, offset=_safe_offset(page.clean_text, boundary.offset))
    for index, page in enumerate(pages):
        if boundary.scan_id and boundary.side and page.scan_id == boundary.scan_id and page.side == boundary.side:
            return _ResolvedBoundary(boundary=ChapterBoundary.from_page(page, offset=boundary.offset), page_index=index, page=page, offset=_safe_offset(page.clean_text, boundary.offset))
    for index, page in enumerate(pages):
        if page.metadata.get("report_page_id") == boundary.page_id:
            return _ResolvedBoundary(boundary=ChapterBoundary.from_page(page, offset=boundary.offset), page_index=index, page=page, offset=_safe_offset(page.clean_text, boundary.offset))
    raise RuntimeError(f"ChapterAssembler konnte Startgrenze nicht aufloesen: {boundary.page_id}")


def _marker_boundary(page: PageRecord, marker: PageChapterMarker) -> ChapterBoundary:
    lines = page.clean_text.splitlines()
    offset = 0
    for index, line in enumerate(lines):
        if index >= marker.line_index:
            break
        offset += len(line) + 1
    return ChapterBoundary.from_page(page, offset=offset)


def _marker_at_boundary(page: PageRecord, offset: int) -> PageChapterMarker | None:
    for marker in page.chapter_markers:
        boundary = _marker_boundary(page, marker)
        if boundary.offset == offset:
            return marker
    return None


def _fallback_boundary_offset(text: str) -> int:
    stripped = text.strip()
    if not stripped:
        return len(text)

    for match in reversed(list(_PARAGRAPH_SPLIT_RE.finditer(text))):
        paragraph = text[: match.start()].rstrip()
        tail = paragraph.split("\n\n")[-1].strip()
        if tail and _SENTENCE_END_RE.search(tail):
            return len(paragraph)

    last_sentence_end = None
    for match in _LAST_SENTENCE_END_RE.finditer(text):
        last_sentence_end = match.end()
    if last_sentence_end is not None:
        return last_sentence_end
    return len(text)


def _skip_leading_whitespace(text: str, offset: int) -> int:
    safe_offset = _safe_offset(text, offset)
    while safe_offset < len(text) and text[safe_offset].isspace():
        safe_offset += 1
    return safe_offset


def _safe_offset(text: str, offset: int) -> int:
    if offset < 0:
        return 0
    if offset > len(text):
        return len(text)
    return offset


def _next_sequence_from_chapters(chapters: list[ChapterRecord]) -> int:
    highest = 0
    for chapter in chapters:
        suffix = chapter.chapter_id.rsplit("_", 1)[-1]
        if suffix.isdigit():
            highest = max(highest, int(suffix))
    return highest + 1 if highest else len(chapters) + 1


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
