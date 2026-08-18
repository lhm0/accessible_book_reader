from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Thread
from typing import Any, Callable

from abr.book.models import PageChapterMarker, PageRecord, ScanRecord
from abr.book.store import BookStore, normalize_tag_id, page_lookup_key, utc_now
from abr.language_config import LanguageProfile, get_language_profile
from abr.text_logic import OCRTextPostProcessor


_PAGE_NUMBER_RE = re.compile(r"^[\[(]?\s*(\d{1,4})\s*[\])]?$")
_CHAPTER_LINE_RE = re.compile(
    r"^(?:(?:kapitel|chapter)\s+)?(?P<number>\d{1,3}|[ivxlcdm]+)(?:\s*[:.-]\s*(?P<heading>.+))?$",
    re.IGNORECASE,
)
_ISOLATED_CHAPTER_NUMBER_RE = re.compile(r"^(?P<number>\d{1,3}|[ivxlcdm]+)$", re.IGNORECASE)
_ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
_SENTENCE_END_RE = re.compile(r"[.!?…](?:[\"'»”)\]]+)?(?=\s|$)")
_CHAPTER_HEADING_BLOCKLIST = {"inhalt", "inhaltsverzeichnis", "prolog", "epilog"}
_PAGE_NUMBER_ARTIFACT_CHARS = set("0123456789IiLlOoSsZzBbGgQq")
_EXPLICIT_CHAPTER_LABEL_RE = re.compile(r"^(kapitel|chapter)\b", re.IGNORECASE)
_TRAILING_HYPHENATED_WORD_RE = re.compile(r"(?P<word>[^\s-]+-)\s*$")
_BRACKETED_TAIL_ARTIFACT_RE = re.compile(r"^[\[(][^\])]{1,14}[\])]$")
_TEXT_POST_PROCESSOR = OCRTextPostProcessor()
_PENDING_RIGHT_TAIL_STATE_FILENAME = "pending_right_tail_fragment.json"


@dataclass(frozen=True)
class PageIngestRequest:
    tag_id: str
    report_path: Path
    scan_id: str | None = None
    session_dir: Path | None = None
    capture_metadata_path: Path | None = None
    created_at: str | None = None
    playback_sides: tuple[str, ...] | None = None


@dataclass(frozen=True)
class PageIngestResult:
    tag_id: str
    scan_record: ScanRecord
    pages: tuple[PageRecord, ...]
    scan_manifest_path: Path
    saved_page_paths: tuple[Path, ...]


@dataclass
class _PageDraft:
    page_payload: dict[str, Any]
    scan_id: str
    created_at: str
    source_report_path: Path
    side: str
    line_entries: list[dict[str, Any]]
    page_number_index: int | None
    page_number: int | None
    inferred_page_number: bool = False
    footer_artifact_index: int | None = None


class PageIngestor:
    def __init__(self, store: BookStore, *, language_code: str = "de") -> None:
        self.store = store
        self.language_profile = get_language_profile(language_code)

    def ingest_report(
        self,
        tag_id: str,
        report_path: Path,
        *,
        scan_id: str | None = None,
        session_dir: Path | None = None,
        capture_metadata_path: Path | None = None,
        created_at: str | None = None,
    ) -> PageIngestResult:
        normalized_tag_id = normalize_tag_id(tag_id)
        resolved_report_path = report_path.expanduser().resolve()
        payload = _read_json(resolved_report_path)
        if not isinstance(payload, dict):
            raise RuntimeError(f"Ungueltiger OCR-Report: {resolved_report_path}")
        report_language = payload.get("ocr_language")
        if isinstance(report_language, str) and report_language != self.language_profile.ocr_language:
            raise RuntimeError(
                f"OCR-Report hat Sprache {report_language}, aktives Buchprofil ist "
                f"{self.language_profile.code}. Gemischte Buchdaten werden nicht gespeichert."
            )

        capture_metadata = _load_optional_json(capture_metadata_path)
        derived_session_dir = _resolve_session_dir(session_dir, capture_metadata, resolved_report_path)
        derived_scan_id = _derive_scan_id(scan_id, derived_session_dir, resolved_report_path)
        created_at_value = created_at or _derive_created_at(capture_metadata) or utc_now()
        resolved_capture_metadata_path = (
            capture_metadata_path.expanduser().resolve() if capture_metadata_path is not None else None
        )
        resolved_ocr_dir = _resolve_optional_path(payload.get("ocr_dir"))

        self.store.ensure_book(
            normalized_tag_id,
            seen_at=created_at_value,
            language=self.language_profile.code,
        )

        drafts = [
            _build_page_draft(
                page_payload=page_payload,
                scan_id=derived_scan_id,
                created_at=created_at_value,
                source_report_path=resolved_report_path,
            )
            for page_payload in _iter_report_pages(payload)
        ]
        if not drafts:
            raise RuntimeError(f"OCR-Report enthaelt keine Seiten: {resolved_report_path}")
        _resolve_spread_page_numbers(drafts)
        pages = tuple(
            _finalize_page_record(draft, language_profile=self.language_profile)
            for draft in drafts
        )
        pages = _normalize_right_page_tail_fragments_for_readout(pages)
        pages = _normalize_single_page_tail_fragment_for_readout(pages)
        pages = _apply_cross_page_tail_fragments(self.store, normalized_tag_id, pages)
        pages = _apply_spread_tail_fragment_carryover(pages)
        pages = _apply_spread_hyphenated_word_carryover(pages)

        scan_record = ScanRecord(
            scan_id=derived_scan_id,
            created_at=created_at_value,
            session_dir=derived_session_dir,
            capture_dir=_resolve_optional_path(capture_metadata.get("case_dir")) if capture_metadata else None,
            ocr_dir=resolved_ocr_dir,
            report_path=resolved_report_path,
            left_page_id=pages[0].page_id if len(pages) >= 1 else None,
            right_page_id=pages[1].page_id if len(pages) >= 2 else None,
            metadata={
                "capture_metadata_path": str(resolved_capture_metadata_path) if resolved_capture_metadata_path else None,
                "pipeline_timings": payload.get("pipeline_timings"),
                "orientation_mode": payload.get("orientation_mode"),
                "ocr_language": payload.get("ocr_language"),
            },
        )
        scan_manifest_path = self.store.save_scan(normalized_tag_id, scan_record)
        superseded_placeholder_paths = _find_superseded_page_placeholders(
            self.store,
            normalized_tag_id,
            pages,
        )
        saved_page_paths = tuple(self.store.save_page(normalized_tag_id, page) for page in pages)
        for placeholder_path in superseded_placeholder_paths:
            if placeholder_path not in saved_page_paths:
                placeholder_path.unlink(missing_ok=True)
        _persist_pending_right_tail_fragment(self.store, normalized_tag_id, pages)
        return PageIngestResult(
            tag_id=normalized_tag_id,
            scan_record=scan_record,
            pages=pages,
            scan_manifest_path=scan_manifest_path,
            saved_page_paths=saved_page_paths,
        )


def _find_superseded_page_placeholders(
    store: BookStore,
    tag_id: str,
    pages: tuple[PageRecord, ...],
) -> tuple[Path, ...]:
    """Find unnumbered versions of pages resolved later in the same scan."""
    pages_dir = store.book_dir(tag_id) / "pages"
    placeholders: list[Path] = []
    for page in pages:
        if page.page_number is None:
            continue
        report_page_id = page.metadata.get("report_page_id")
        if not isinstance(report_page_id, str) or not report_page_id.strip():
            continue
        placeholder = store.load_page(tag_id, report_page_id)
        if placeholder is None or placeholder.page_number is not None:
            continue
        if (
            placeholder.scan_id != page.scan_id
            or placeholder.side != page.side
            or placeholder.metadata.get("report_page_id") != report_page_id
        ):
            continue
        placeholders.append(pages_dir / f"{page_lookup_key(report_page_id)}.json")
    return tuple(placeholders)


class PageIngestService:
    def __init__(
        self,
        ingestor: PageIngestor,
        *,
        status_callback: Callable[[str], None] | None = None,
        result_callback: Callable[[PageIngestRequest, PageIngestResult], None] | None = None,
        failure_callback: Callable[[PageIngestRequest, BaseException], None] | None = None,
        success_callback: Callable[[PageIngestRequest, PageIngestResult], list[Path] | None] | None = None,
    ) -> None:
        self.ingestor = ingestor
        self.status_callback = status_callback
        self.result_callback = result_callback
        self.failure_callback = failure_callback
        self.success_callback = success_callback
        self._queue: Queue[tuple[PageIngestRequest, Event]] = Queue()
        self._stop_event = Event()
        self._thread = Thread(target=self._run, name="abr-page-ingest", daemon=True)
        self._thread.start()

    def submit(self, request: PageIngestRequest) -> Event:
        completion_event = Event()
        self._queue.put((request, completion_event))
        self._emit_status(
            f"page-ingest eingeplant: Buch {normalize_tag_id(request.tag_id)}, Report {request.report_path}."
        )
        return completion_event

    def shutdown(self, join_timeout_s: float = 1.0) -> None:
        self._stop_event.set()
        self._thread.join(timeout=join_timeout_s)

    def set_result_callback(self, callback: Callable[[PageIngestRequest, PageIngestResult], None] | None) -> None:
        self.result_callback = callback

    def set_failure_callback(self, callback: Callable[[PageIngestRequest, BaseException], None] | None) -> None:
        self.failure_callback = callback

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                request, completion_event = self._queue.get(timeout=0.1)
            except Empty:
                continue
            try:
                self._emit_status(f"page-ingest startet: {request.report_path}.")
                result = self.ingestor.ingest_report(
                    request.tag_id,
                    request.report_path,
                    scan_id=request.scan_id,
                    session_dir=request.session_dir,
                    capture_metadata_path=request.capture_metadata_path,
                    created_at=request.created_at,
                )
                page_labels = ", ".join(_format_page_label(page) for page in result.pages)
                self._emit_status(
                    f"page-ingest abgeschlossen: {result.scan_record.scan_id} -> {len(result.pages)} Seiten gespeichert ({page_labels})."
                )
                if self.result_callback is not None:
                    self.result_callback(request, result)
                if self.success_callback is not None:
                    removed_paths = self.success_callback(request, result) or []
                    if removed_paths:
                        removed_text = ", ".join(str(path) for path in removed_paths)
                        self._emit_status(f"artefakte bereinigt: {removed_text}.")
            except BaseException as exc:  # pragma: no cover - defensive runtime propagation
                self._emit_status(f"page-ingest fehlgeschlagen: {exc}")
                if self.failure_callback is not None:
                    self.failure_callback(request, exc)
            finally:
                completion_event.set()
                self._queue.task_done()

    def _emit_status(self, message: str) -> None:
        if self.status_callback is not None:
            self.status_callback(message)


def _iter_report_pages(payload: dict[str, Any]) -> list[dict[str, Any]]:
    pages = payload.get("pages", [])
    if not isinstance(pages, list):
        raise RuntimeError("OCR-Report enthaelt kein gueltiges pages-Array.")
    normalized_pages: list[dict[str, Any]] = []
    for page_payload in pages:
        if not isinstance(page_payload, dict):
            raise RuntimeError("OCR-Report enthaelt einen ungueltigen Seiten-Eintrag.")
        normalized_pages.append(page_payload)
    return normalized_pages


def _build_page_draft(
    *,
    page_payload: dict[str, Any],
    scan_id: str,
    created_at: str,
    source_report_path: Path,
) -> _PageDraft:
    side = str(page_payload.get("slot") or page_payload.get("side") or "").strip().lower()
    if side not in {"left", "right"}:
        raise RuntimeError(f"Ungueltige Seitenkennung im OCR-Report: {page_payload.get('slot')!r}")

    line_entries = _extract_text_lines(page_payload)
    page_number_index, page_number = _detect_page_number(line_entries, page_payload)
    return _PageDraft(
        page_payload=page_payload,
        scan_id=scan_id,
        created_at=created_at,
        source_report_path=source_report_path,
        side=side,
        line_entries=line_entries,
        page_number_index=page_number_index,
        page_number=page_number,
    )


def _finalize_page_record(
    draft: _PageDraft,
    *,
    language_profile: LanguageProfile,
) -> PageRecord:
    ignored_indices = {index for index in (draft.page_number_index, draft.footer_artifact_index) if index is not None}
    indexed_cleaned_entries = [
        (index, entry)
        for index, entry in enumerate(draft.line_entries)
        if index not in ignored_indices
    ]
    cleaned_entries = [entry for _original_index, entry in indexed_cleaned_entries]
    layout_to_cleaned_index = {
        entry.get("_layout_line_index", original_index): cleaned_index
        for cleaned_index, (original_index, entry) in enumerate(indexed_cleaned_entries)
    }
    paragraph_end_indices = {
        layout_to_cleaned_index[layout_line_index]
        for layout_line_index in _paragraph_end_line_indices(draft.page_payload)
        if layout_line_index in layout_to_cleaned_index
    }
    chapter_markers = _detect_chapter_markers(cleaned_entries)
    first_marker = chapter_markers[0] if chapter_markers else None
    chapter_number = first_marker.chapter_number if first_marker is not None else None
    chapter_heading = first_marker.chapter_heading if first_marker is not None else None
    clean_text = _join_clean_lines([entry["text"] for entry in cleaned_entries])
    tail_analysis = _analyze_tail_fragment(clean_text, chapter_markers=chapter_markers)
    tail_fragment = tail_analysis["fragment"]
    speak_text = _build_speak_text(
        cleaned_entries,
        chapter_markers,
        paragraph_end_indices=paragraph_end_indices,
        language_profile=language_profile,
    )
    _debug_page_ingestor(
        "tail-check",
        side=draft.side,
        report_page_id=draft.page_payload.get("page_id"),
        page_number=draft.page_number,
        chapter_marker_count=len(chapter_markers),
        detection_reason=tail_analysis["reason"],
        tail_fragment=tail_fragment,
        speak_tail_fragment=_extract_trailing_incomplete_fragment(speak_text.strip()),
        speak_tail_matches_clean_tail=bool(tail_fragment and speak_text.strip().endswith(tail_fragment)),
    )
    original_speak_text = speak_text
    speak_text = _strip_tail_fragment_from_speak_text(speak_text, tail_fragment=tail_fragment)
    _debug_page_ingestor(
        "tail-strip-result",
        side=draft.side,
        report_page_id=draft.page_payload.get("page_id"),
        page_number=draft.page_number,
        tail_fragment=tail_fragment,
        strip_status=_classify_tail_strip_result(original_speak_text, tail_fragment, speak_text),
        changed=speak_text != original_speak_text,
    )

    page_id = _derive_page_id(
        draft.page_payload,
        scan_id=draft.scan_id,
        page_number=draft.page_number,
        side=draft.side,
    )
    return PageRecord(
        page_id=page_id,
        scan_id=draft.scan_id,
        created_at=draft.created_at,
        side=draft.side,
        clean_text=clean_text,
        speak_text=speak_text,
        page_number=draft.page_number,
        chapter_number=chapter_number,
        chapter_heading=chapter_heading,
        chapter_markers=chapter_markers,
        tail_fragment=tail_fragment,
        source_report_path=draft.source_report_path,
        metadata={
            "slot": draft.side,
            "report_page_id": draft.page_payload.get("page_id"),
            "rotation_deg": draft.page_payload.get("rotation_deg"),
            "orientation_reason": draft.page_payload.get("orientation_reason"),
            "avg_confidence": draft.page_payload.get("avg_confidence"),
            "ocr_line_count": draft.page_payload.get("ocr_line_count"),
            "language": language_profile.code,
            "page_number_line_index": draft.page_number_index,
            "page_number_inferred": draft.inferred_page_number,
            "footer_artifact_index": draft.footer_artifact_index,
        },
    )


def _apply_cross_page_tail_fragments(store: BookStore, tag_id: str, pages: tuple[PageRecord, ...]) -> tuple[PageRecord, ...]:
    if not pages:
        return pages

    updated_pages = list(pages)
    target_index = _find_tail_fragment_target_index(updated_pages)
    if target_index is None:
        _debug_page_ingestor("cross-tail-skip", reason="no_target_page")
        return pages

    target_page = updated_pages[target_index]
    if target_page.page_number is None:
        pending_fragment = _load_pending_right_tail_fragment(store, tag_id)
        _debug_page_ingestor(
            "cross-tail-pending-check",
            target_page_id=target_page.page_id,
            target_side=target_page.side,
            target_page_number=target_page.page_number,
            pending_fragment= pending_fragment,
        )
        if pending_fragment:
            updated_target_page = replace(
                target_page,
                speak_text=_prepend_tail_fragment(pending_fragment, target_page.speak_text),
            )
            _debug_page_ingestor(
                "cross-tail-pending-apply",
                target_page_id=target_page.page_id,
                target_side=target_page.side,
                target_page_number=target_page.page_number,
                fragment=pending_fragment,
            )
            updated_pages[target_index] = updated_target_page
            return tuple(updated_pages)
        _debug_page_ingestor(
            "cross-tail-skip",
            reason="missing_page_number_and_no_pending_fragment",
            target_page_id=target_page.page_id,
            target_side=target_page.side,
            target_page_number=target_page.page_number,
        )
        return pages
    if target_page.page_number <= 1:
        _debug_page_ingestor(
            "cross-tail-skip",
            reason="first_page_number",
            target_page_id=target_page.page_id,
            target_side=target_page.side,
            target_page_number=target_page.page_number,
        )
        return pages

    previous_page = store.load_page(tag_id, target_page.page_number - 1)
    _debug_page_ingestor(
        "cross-tail-check",
        target_page_id=target_page.page_id,
        target_side=target_page.side,
        target_page_number=target_page.page_number,
        previous_lookup_page_number=target_page.page_number - 1,
        previous_page_id=previous_page.page_id if previous_page is not None else None,
        previous_page_side=previous_page.side if previous_page is not None else None,
        previous_page_tail_fragment=previous_page.tail_fragment if previous_page is not None else None,
    )
    if previous_page is None or previous_page.side != "right" or not previous_page.tail_fragment:
        _debug_page_ingestor(
            "cross-tail-skip",
            reason=(
                "previous_page_missing"
                if previous_page is None
                else "previous_page_not_right"
                if previous_page.side != "right"
                else "previous_page_has_no_tail_fragment"
            ),
            target_page_id=target_page.page_id,
            target_page_number=target_page.page_number,
            previous_page_id=previous_page.page_id if previous_page is not None else None,
            previous_page_side=previous_page.side if previous_page is not None else None,
            previous_page_tail_fragment=previous_page.tail_fragment if previous_page is not None else None,
        )
        return pages

    updated_target_page = replace(
        target_page,
        speak_text=_prepend_tail_fragment(previous_page.tail_fragment, target_page.speak_text),
    )
    _debug_page_ingestor(
        "cross-tail-apply",
        target_page_id=target_page.page_id,
        target_page_number=target_page.page_number,
        previous_page_id=previous_page.page_id,
        previous_page_number=previous_page.page_number,
        fragment=previous_page.tail_fragment,
    )
    updated_pages[target_index] = updated_target_page
    return tuple(updated_pages)


def _normalize_single_page_tail_fragment_for_readout(pages: tuple[PageRecord, ...]) -> tuple[PageRecord, ...]:
    if len(pages) != 1:
        return pages

    page = pages[0]
    if page.side != "left":
        return pages

    normalized_page = _normalize_page_tail_fragment_for_readout(page, event="single-page-tail-normalize")
    if normalized_page == page:
        return pages
    return (normalized_page,)


def _normalize_right_page_tail_fragments_for_readout(pages: tuple[PageRecord, ...]) -> tuple[PageRecord, ...]:
    updated_pages: list[PageRecord] = []
    changed = False
    for page in pages:
        if page.side != "right" or not page.tail_fragment:
            updated_pages.append(page)
            continue

        normalized_page = _normalize_page_tail_fragment_for_readout(page, event="right-page-tail-normalize")
        updated_pages.append(normalized_page)
        if normalized_page != page:
            changed = True

    if not changed:
        return pages
    return tuple(updated_pages)


def _normalize_page_tail_fragment_for_readout(page: PageRecord, *, event: str) -> PageRecord:
    effective_tail_fragment = page.tail_fragment.strip() if page.tail_fragment else None
    stripped_speak_text = page.speak_text.strip()
    fragment_source = "page_tail_fragment"
    if not effective_tail_fragment or not stripped_speak_text.endswith(effective_tail_fragment):
        fragment_source = "speak_text_fallback"
        effective_tail_fragment = _extract_trailing_incomplete_fragment(stripped_speak_text) or effective_tail_fragment
    if not effective_tail_fragment:
        _debug_page_ingestor(
            f"{event}-skip",
            page_id=page.page_id,
            side=page.side,
            reason="no_effective_tail_fragment",
            original_tail_fragment=page.tail_fragment,
        )
        return page

    updated_speak_text = _strip_tail_fragment_from_speak_text(
        page.speak_text,
        tail_fragment=effective_tail_fragment,
    )
    _debug_page_ingestor(
        event,
        page_id=page.page_id,
        side=page.side,
        page_number=page.page_number,
        original_tail_fragment=page.tail_fragment,
        fragment_source=fragment_source,
        effective_tail_fragment=effective_tail_fragment,
        strip_status=_classify_tail_strip_result(page.speak_text, effective_tail_fragment, updated_speak_text),
        changed=updated_speak_text != page.speak_text,
    )
    if updated_speak_text == page.speak_text and page.tail_fragment == effective_tail_fragment:
        return page
    return replace(
        page,
        tail_fragment=effective_tail_fragment,
        speak_text=updated_speak_text,
    )


def _apply_spread_hyphenated_word_carryover(pages: tuple[PageRecord, ...]) -> tuple[PageRecord, ...]:
    if len(pages) < 2:
        return pages
    left_index = next((index for index, page in enumerate(pages) if page.side == "left"), None)
    right_index = next((index for index, page in enumerate(pages) if page.side == "right"), None)
    if left_index is None or right_index is None:
        return pages

    left_page = pages[left_index]
    right_page = pages[right_index]
    updated_left_speak_text, updated_right_speak_text = _bridge_hyphenated_word_between_pages(
        left_page.speak_text,
        right_page.speak_text,
    )
    if (
        updated_left_speak_text == left_page.speak_text
        and updated_right_speak_text == right_page.speak_text
    ):
        return pages

    updated_pages = list(pages)
    updated_pages[left_index] = replace(left_page, speak_text=updated_left_speak_text)
    updated_pages[right_index] = replace(right_page, speak_text=updated_right_speak_text)
    return tuple(updated_pages)


def _apply_spread_tail_fragment_carryover(pages: tuple[PageRecord, ...]) -> tuple[PageRecord, ...]:
    if len(pages) < 2:
        return pages
    left_index = next((index for index, page in enumerate(pages) if page.side == "left"), None)
    right_index = next((index for index, page in enumerate(pages) if page.side == "right"), None)
    if left_index is None or right_index is None:
        return pages

    left_page = pages[left_index]
    right_page = pages[right_index]
    if not right_page.speak_text.strip():
        _debug_page_ingestor(
            "spread-tail-skip",
            reason="right_page_empty_speak_text",
            left_page_id=left_page.page_id,
            right_page_id=right_page.page_id,
        )
        return pages
    if _is_chapter_marker_block_only(left_page.clean_text.strip(), left_page.chapter_markers):
        _debug_page_ingestor(
            "spread-tail-skip",
            reason="left_page_is_chapter_marker_block_only",
            left_page_id=left_page.page_id,
            right_page_id=right_page.page_id,
        )
        return pages
    if _is_heading_only_text(right_page.clean_text.strip(), right_page.chapter_markers):
        _debug_page_ingestor(
            "spread-tail-skip",
            reason="right_page_is_heading_only",
            left_page_id=left_page.page_id,
            right_page_id=right_page.page_id,
        )
        return pages

    fragment = _extract_trailing_incomplete_fragment(left_page.speak_text) or left_page.tail_fragment
    fragment_source = (
        "left_speak_text"
        if _extract_trailing_incomplete_fragment(left_page.speak_text)
        else "left_page_tail_fragment"
    )
    _debug_page_ingestor(
        "spread-tail-check",
        left_page_id=left_page.page_id,
        right_page_id=right_page.page_id,
        left_page_number=left_page.page_number,
        right_page_number=right_page.page_number,
        fragment_source=fragment_source,
        fragment=fragment,
    )
    if not fragment:
        _debug_page_ingestor(
            "spread-tail-skip",
            reason="no_fragment_detected",
            left_page_id=left_page.page_id,
            right_page_id=right_page.page_id,
        )
        return pages

    updated_left_speak_text = _strip_tail_fragment_from_speak_text(left_page.speak_text, tail_fragment=fragment)
    updated_right_speak_text = _prepend_tail_fragment(fragment, right_page.speak_text)
    _debug_page_ingestor(
        "spread-tail-apply",
        left_page_id=left_page.page_id,
        right_page_id=right_page.page_id,
        fragment=fragment,
        left_strip_status=_classify_tail_strip_result(left_page.speak_text, fragment, updated_left_speak_text),
        left_changed=updated_left_speak_text != left_page.speak_text,
        right_changed=updated_right_speak_text != right_page.speak_text,
    )
    if (
        updated_left_speak_text == left_page.speak_text
        and updated_right_speak_text == right_page.speak_text
    ):
        _debug_page_ingestor(
            "spread-tail-skip",
            reason="no_effect_after_apply",
            left_page_id=left_page.page_id,
            right_page_id=right_page.page_id,
            fragment=fragment,
        )
        return pages

    updated_pages = list(pages)
    updated_pages[left_index] = replace(left_page, speak_text=updated_left_speak_text)
    updated_pages[right_index] = replace(right_page, speak_text=updated_right_speak_text)
    return tuple(updated_pages)


def _find_tail_fragment_target_index(pages: list[PageRecord]) -> int | None:
    left_candidates = [
        (index, page)
        for index, page in enumerate(pages)
        if page.side == "left" and page.page_number is not None
    ]
    if left_candidates:
        return min(left_candidates, key=lambda item: item[1].page_number)[0]

    numbered_pages = [
        (index, page)
        for index, page in enumerate(pages)
        if page.page_number is not None
    ]
    if numbered_pages:
        return min(numbered_pages, key=lambda item: item[1].page_number)[0]
    return 0 if pages else None


def _persist_pending_right_tail_fragment(store: BookStore, tag_id: str, pages: tuple[PageRecord, ...]) -> None:
    right_page = next((page for page in pages if page.side == "right"), None)
    if right_page is None:
        return

    payload = {
        "page_id": right_page.page_id,
        "page_number": right_page.page_number,
        "tail_fragment": right_page.tail_fragment,
    }
    store.save_runtime_state(tag_id, _PENDING_RIGHT_TAIL_STATE_FILENAME, payload)
    _debug_page_ingestor(
        "pending-tail-store",
        page_id=right_page.page_id,
        page_number=right_page.page_number,
        tail_fragment=right_page.tail_fragment,
        state="set" if right_page.tail_fragment else "cleared",
    )


def _load_pending_right_tail_fragment(store: BookStore, tag_id: str) -> str | None:
    payload = store.load_runtime_state(tag_id, _PENDING_RIGHT_TAIL_STATE_FILENAME)
    if payload is None:
        return None
    fragment = payload.get("tail_fragment")
    if fragment is None:
        return None
    normalized = str(fragment).strip()
    return normalized or None


def _extract_text_lines(page_payload: dict[str, Any]) -> list[dict[str, Any]]:
    lines = page_payload.get("ocr_lines")
    if isinstance(lines, list) and lines:
        extracted: list[dict[str, Any]] = []
        for line_index, entry in enumerate(lines):
            if not isinstance(entry, dict):
                continue
            text = _normalize_text(entry.get("text"))
            if not text:
                continue
            extracted.append(
                {
                    "text": text,
                    "bbox": entry.get("bbox"),
                    "confidence": entry.get("confidence"),
                    "_layout_line_index": line_index,
                }
            )
        if extracted:
            return extracted

    text_path = _resolve_optional_path(page_payload.get("text_path"))
    if text_path is not None and text_path.exists():
        return [{"text": _normalize_text(line)} for line in text_path.read_text(encoding="utf-8").splitlines() if _normalize_text(line)]

    paragraphs = page_payload.get("paragraphs")
    if isinstance(paragraphs, list):
        normalized = [{"text": _normalize_text(value)} for value in paragraphs if _normalize_text(value)]
        if normalized:
            return normalized
    raise RuntimeError("Seite enthaelt weder OCR-Zeilen noch lesbaren Text.")


def _detect_page_number(line_entries: list[dict[str, Any]], page_payload: dict[str, Any]) -> tuple[int | None, int | None]:
    explicit_page_number = page_payload.get("page_number")
    if explicit_page_number is not None:
        try:
            page_number_value = int(explicit_page_number)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"Ungueltige page_number im OCR-Report: {explicit_page_number!r}") from exc
        for index, entry in enumerate(line_entries):
            if entry["text"] == str(page_number_value):
                return index, page_number_value
        return None, page_number_value

    best_index: int | None = None
    best_page_number: int | None = None
    best_score: tuple[float, int] | None = None
    max_y = 0.0
    for entry in line_entries:
        max_y = max(max_y, _bbox_bottom(entry.get("bbox")))

    for index, entry in enumerate(line_entries):
        match = _PAGE_NUMBER_RE.match(entry["text"])
        if match is None:
            continue
        page_number = int(match.group(1))
        y_center = _bbox_center_y(entry.get("bbox"))
        score = (y_center / max(1.0, max_y), page_number)
        if best_score is None or score > best_score:
            best_index = index
            best_page_number = page_number
            best_score = score
    return best_index, best_page_number


def _detect_chapter_markers(line_entries: list[dict[str, Any]]) -> list[PageChapterMarker]:
    markers: list[PageChapterMarker] = []
    explicit_consumed: set[int] = set()
    lines = [entry["text"] for entry in line_entries]

    for index, line in enumerate(lines):
        match = _CHAPTER_LINE_RE.match(line)
        if match is None:
            continue
        number = _parse_chapter_number(match.group("number"))
        heading = _normalize_text(match.group("heading")) or None
        consumed_line_count = 1
        detection_kind = "number_only"
        if _EXPLICIT_CHAPTER_LABEL_RE.match(line):
            detection_kind = "explicit_label"
        if heading:
            detection_kind = "explicit_inline_heading"
        elif _EXPLICIT_CHAPTER_LABEL_RE.match(line) and index + 1 < len(lines):
            next_line = lines[index + 1]
            if _looks_like_heading_line(next_line):
                heading = next_line
                consumed_line_count = 2
                detection_kind = "explicit_following_heading"
        markers.append(
            PageChapterMarker(
                line_index=index,
                chapter_number=number,
                chapter_heading=heading,
                consumed_line_count=consumed_line_count,
                detection_kind=detection_kind,
            )
        )
        explicit_consumed.add(index)
        if consumed_line_count == 2:
            explicit_consumed.add(index + 1)

    for index, chapter_number in _detect_isolated_chapter_numbers(line_entries, blocked_indices=explicit_consumed):
        markers.append(
            PageChapterMarker(
                line_index=index,
                chapter_number=chapter_number,
                chapter_heading=None,
                consumed_line_count=1,
                detection_kind="isolated_number",
            )
        )

    heading_only_marker = _detect_heading_only_marker(line_entries, blocked_indices=explicit_consumed)
    if heading_only_marker is not None:
        markers.append(heading_only_marker)

    deduped: dict[tuple[int, int | None, str | None], PageChapterMarker] = {}
    for marker in markers:
        key = (marker.line_index, marker.chapter_number, marker.chapter_heading)
        deduped[key] = marker
    return sorted(deduped.values(), key=lambda marker: marker.line_index)


def _extract_tail_fragment(
    clean_text: str,
    chapter_markers: list[PageChapterMarker],
) -> str | None:
    stripped = clean_text.strip()
    if not stripped:
        return None
    if _is_heading_only_text(stripped, chapter_markers):
        return None
    if _is_chapter_marker_block_only(stripped, chapter_markers):
        return None
    return _extract_trailing_incomplete_fragment(stripped)


def _extract_trailing_incomplete_fragment(text: str) -> str | None:
    stripped = text.strip()
    if not stripped:
        return None
    if _SENTENCE_END_RE.search(stripped[-4:]) is not None:
        return None
    matches = list(_SENTENCE_END_RE.finditer(stripped))
    if matches:
        fragment = stripped[matches[-1].end():].strip()
        return fragment or None
    return stripped


def _join_clean_lines(lines: list[str]) -> str:
    return "\n".join(line for line in lines if line).strip()


def _spell_german_cardinal(number: int) -> str:
    if number < 0:
        return str(number)

    units = {
        0: "null",
        1: "eins",
        2: "zwei",
        3: "drei",
        4: "vier",
        5: "fuenf",
        6: "sechs",
        7: "sieben",
        8: "acht",
        9: "neun",
        10: "zehn",
        11: "elf",
        12: "zwoelf",
        13: "dreizehn",
        14: "vierzehn",
        15: "fuenfzehn",
        16: "sechzehn",
        17: "siebzehn",
        18: "achtzehn",
        19: "neunzehn",
    }
    tens = {
        20: "zwanzig",
        30: "dreissig",
        40: "vierzig",
        50: "fuenfzig",
        60: "sechzig",
        70: "siebzig",
        80: "achtzig",
        90: "neunzig",
    }

    if number in units:
        return units[number]
    if number in tens:
        return tens[number]
    if number < 100:
        ones = number % 10
        ten_value = number - ones
        ones_prefix = "ein" if ones == 1 else units[ones]
        return f"{ones_prefix}und{tens[ten_value]}"
    if number < 1000:
        hundreds = number // 100
        remainder = number % 100
        hundreds_prefix = "ein" if hundreds == 1 else units[hundreds]
        if remainder == 0:
            return f"{hundreds_prefix}hundert"
        return f"{hundreds_prefix}hundert{_spell_german_cardinal(remainder)}"
    return str(number)


def _spell_english_cardinal(number: int) -> str:
    if number < 0:
        return str(number)
    units = {
        0: "zero",
        1: "one",
        2: "two",
        3: "three",
        4: "four",
        5: "five",
        6: "six",
        7: "seven",
        8: "eight",
        9: "nine",
        10: "ten",
        11: "eleven",
        12: "twelve",
        13: "thirteen",
        14: "fourteen",
        15: "fifteen",
        16: "sixteen",
        17: "seventeen",
        18: "eighteen",
        19: "nineteen",
    }
    tens = {
        20: "twenty",
        30: "thirty",
        40: "forty",
        50: "fifty",
        60: "sixty",
        70: "seventy",
        80: "eighty",
        90: "ninety",
    }
    if number in units:
        return units[number]
    if number in tens:
        return tens[number]
    if number < 100:
        ones = number % 10
        return f"{tens[number - ones]}-{units[ones]}"
    if number < 1000:
        hundreds = number // 100
        remainder = number % 100
        prefix = f"{units[hundreds]} hundred"
        return prefix if remainder == 0 else f"{prefix} {_spell_english_cardinal(remainder)}"
    return str(number)


def _spell_chapter_cardinal(number: int, language_profile: LanguageProfile) -> str:
    if language_profile.code == "en":
        return _spell_english_cardinal(number)
    return _spell_german_cardinal(number)


def _build_speak_text(
    line_entries: list[dict[str, Any]],
    chapter_markers: list[PageChapterMarker],
    *,
    paragraph_end_indices: set[int] | None = None,
    language_profile: LanguageProfile,
) -> str:
    marker_by_line_index = {marker.line_index: marker for marker in chapter_markers}
    effective_paragraph_end_indices = paragraph_end_indices or set()
    rendered_lines: list[str] = []
    for index, entry in enumerate(line_entries):
        marker = marker_by_line_index.get(index)
        if marker is not None and marker.detection_kind == "number_only" and marker.chapter_number is not None:
            if rendered_lines and rendered_lines[-1] != "":
                rendered_lines.append("")
            rendered_lines.append(
                f"{language_profile.chapter_label} "
                f"{_spell_chapter_cardinal(marker.chapter_number, language_profile)}."
            )
            rendered_lines.append("")
            continue
        is_uppercase_heading = _TEXT_POST_PROCESSOR.is_uppercase_heading(entry["text"])
        rendered_lines.append(_TEXT_POST_PROCESSOR.normalize_uppercase_heading(entry["text"]))
        if (
            (is_uppercase_heading or index in effective_paragraph_end_indices)
            and index < len(line_entries) - 1
        ):
            rendered_lines.append("")
    merged_lines = _merge_speak_text_hyphenation(rendered_lines)
    speak_text = "\n".join(merged_lines).strip()
    speak_text = _TEXT_POST_PROCESSOR.collapse_spaced_letter_sequences(speak_text)
    if language_profile.code == "de":
        speak_text = _TEXT_POST_PROCESSOR.normalize_german_spoken_text(speak_text)
    return speak_text


def _paragraph_end_line_indices(page_payload: dict[str, Any]) -> set[int]:
    layout_blocks = page_payload.get("layout_blocks")
    if not isinstance(layout_blocks, list):
        return set()

    paragraph_ends: set[int] = set()
    for block in layout_blocks:
        if not isinstance(block, dict) or block.get("kind") not in {
            "paragraph",
            "chapter_heading",
        }:
            continue
        line_indices = block.get("line_indices")
        if not isinstance(line_indices, list):
            continue
        valid_indices = [
            line_index
            for line_index in line_indices
            if isinstance(line_index, int) and not isinstance(line_index, bool)
        ]
        if valid_indices:
            paragraph_ends.add(max(valid_indices))
    return paragraph_ends


def _strip_tail_fragment_from_speak_text(speak_text: str, *, tail_fragment: str | None) -> str:
    if not tail_fragment:
        return speak_text
    stripped = speak_text.strip()
    if not stripped:
        return stripped
    if stripped == tail_fragment:
        return ""
    if stripped.endswith(tail_fragment):
        prefix = stripped[: -len(tail_fragment)].rstrip()
        return prefix
    return stripped


def _debug_page_ingestor(event: str, **payload: object) -> None:
    del event, payload
    return

def _classify_tail_strip_result(original_speak_text: str, tail_fragment: str | None, updated_speak_text: str) -> str:
    if not tail_fragment:
        return "no_tail_fragment"
    stripped = original_speak_text.strip()
    if not stripped:
        return "empty_speak_text"
    if stripped == tail_fragment:
        return "full_match_removed"
    if stripped.endswith(tail_fragment):
        return "suffix_match_removed"
    if updated_speak_text == stripped:
        return "no_suffix_match"
    return "changed_without_suffix_match"


def _analyze_tail_fragment(
    clean_text: str,
    *,
    chapter_markers: list[PageChapterMarker],
) -> dict[str, str | None]:
    stripped = clean_text.strip()
    if not stripped:
        return {"reason": "empty_clean_text", "fragment": None}
    if _is_heading_only_text(stripped, chapter_markers):
        return {"reason": "heading_only_text", "fragment": None}
    if _is_chapter_marker_block_only(stripped, chapter_markers):
        return {"reason": "chapter_marker_block_only", "fragment": None}
    if _SENTENCE_END_RE.search(stripped[-4:]) is not None:
        return {"reason": "ends_with_sentence_terminator", "fragment": None}
    matches = list(_SENTENCE_END_RE.finditer(stripped))
    if matches:
        fragment = stripped[matches[-1].end():].strip() or None
        if fragment is not None and _looks_like_tail_artifact(fragment):
            fragment = None
        return {"reason": "fragment_after_last_sentence_terminator", "fragment": fragment}
    if _looks_like_tail_artifact(stripped):
        return {"reason": "ocr_tail_artifact", "fragment": None}
    return {"reason": "no_sentence_terminator_found", "fragment": stripped}




def _prepend_tail_fragment(tail_fragment: str, speak_text: str) -> str:
    fragment = tail_fragment.strip()
    current = speak_text.strip()
    if not fragment or _looks_like_tail_artifact(fragment):
        return current
    if not current:
        return fragment
    if fragment.endswith("-") and _TEXT_POST_PROCESSOR._starts_with_lowercase_letter(current.lstrip()):
        return f"{fragment[:-1]}{current.lstrip()}"
    return f"{fragment} {current}"


def _looks_like_tail_artifact(text: str) -> bool:
    stripped = text.strip()
    return bool(
        _BRACKETED_TAIL_ARTIFACT_RE.fullmatch(stripped)
        and any(character.isdigit() for character in stripped)
    )


def _bridge_hyphenated_word_between_pages(left_speak_text: str, right_speak_text: str) -> tuple[str, str]:
    stripped_left = left_speak_text.strip()
    stripped_right = right_speak_text.strip()
    if not stripped_right or not _TEXT_POST_PROCESSOR._starts_with_lowercase_letter(stripped_right.lstrip()):
        return stripped_left, stripped_right

    match = _TRAILING_HYPHENATED_WORD_RE.search(stripped_left)
    if match is None:
        return stripped_left, stripped_right

    fragment = match.group("word")
    updated_left = stripped_left[: match.start()].rstrip()
    updated_right = f"{fragment[:-1]}{stripped_right.lstrip()}"
    return updated_left, updated_right


def _merge_speak_text_hyphenation(lines: list[str]) -> list[str]:
    merged_lines: list[str] = []
    for line in lines:
        if (
            merged_lines
            and merged_lines[-1]
            and line
            and merged_lines[-1].rstrip().endswith("-")
            and _TEXT_POST_PROCESSOR._starts_with_lowercase_letter(line.lstrip())
        ):
            merged_lines[-1] = merged_lines[-1].rstrip()[:-1] + line.lstrip()
            continue
        merged_lines.append(line)
    return merged_lines


def _resolve_spread_page_numbers(drafts: list[_PageDraft]) -> None:
    if len(drafts) != 2:
        return
    numbered = [draft for draft in drafts if draft.page_number is not None]
    unnumbered = [draft for draft in drafts if draft.page_number is None]
    if len(numbered) != 1 or len(unnumbered) != 1:
        return

    detected = numbered[0]
    inferred = unnumbered[0]
    if detected.side == "right" and inferred.side == "left":
        inferred_number = detected.page_number - 1
    elif detected.side == "left" and inferred.side == "right":
        inferred_number = detected.page_number + 1
    else:
        return

    # Seite 1 besitzt keinen gueltigen Vorgaenger. In diesem unplausiblen Fall
    # bleibt die andere Seite lieber unnummeriert, statt als 0000 gespeichert zu werden.
    if inferred_number < 1:
        return
    inferred.page_number = inferred_number
    inferred.inferred_page_number = True
    inferred.footer_artifact_index = _detect_footer_artifact_index(inferred.line_entries)


def _detect_footer_artifact_index(line_entries: list[dict[str, Any]]) -> int | None:
    if not line_entries:
        return None
    max_y = max(_bbox_bottom(entry.get("bbox")) for entry in line_entries)
    for index in range(len(line_entries) - 1, -1, -1):
        text = line_entries[index]["text"]
        if not text or " " in text or len(text) > 4:
            continue
        bottom_ratio = _bbox_bottom(line_entries[index].get("bbox")) / max(1.0, max_y)
        if bottom_ratio < 0.93:
            continue
        if all(character in _PAGE_NUMBER_ARTIFACT_CHARS for character in text):
            return index
    return None


def _detect_isolated_chapter_numbers(
    line_entries: list[dict[str, Any]],
    *,
    blocked_indices: set[int],
) -> list[tuple[int, int]]:
    if len(line_entries) < 2:
        return []
    detected: list[tuple[int, int]] = []
    max_y = max(_bbox_bottom(entry.get("bbox")) for entry in line_entries)
    for index, entry in enumerate(line_entries):
        if index in blocked_indices:
            continue
        match = _ISOLATED_CHAPTER_NUMBER_RE.match(entry["text"])
        if match is None:
            continue
        chapter_number = _parse_chapter_number(match.group("number"))
        if chapter_number is None:
            continue
        y_ratio = _bbox_center_y(entry.get("bbox")) / max(1.0, max_y)
        if y_ratio >= 0.82:
            continue
        current_height = max(1.0, _bbox_height(entry.get("bbox")))
        prev_gap = _line_gap(line_entries, index - 1, index)
        next_gap = _line_gap(line_entries, index, index + 1)
        if prev_gap >= current_height * 0.8 and next_gap >= current_height * 0.8:
            detected.append((index, chapter_number))
    return detected


def _detect_heading_only_marker(
    line_entries: list[dict[str, Any]],
    *,
    blocked_indices: set[int],
) -> PageChapterMarker | None:
    visible_entries = [
        (index, entry)
        for index, entry in enumerate(line_entries)
        if index not in blocked_indices and entry["text"]
    ]
    if len(visible_entries) != 1:
        return None
    index, entry = visible_entries[0]
    text = entry["text"]
    if not _looks_like_heading_line(text):
        return None
    if not _looks_like_heading_shape(text):
        return None
    return PageChapterMarker(
        line_index=index,
        chapter_number=None,
        chapter_heading=text,
        consumed_line_count=1,
        detection_kind="heading_only_page",
    )


def _derive_page_id(page_payload: dict[str, Any], *, scan_id: str, page_number: int | None, side: str) -> str:
    if page_number is not None:
        return f"page_{page_number:04d}"
    report_page_id = _normalize_text(page_payload.get("page_id"))
    if report_page_id:
        return report_page_id
    return f"{scan_id}_{side}"


def _derive_scan_id(scan_id: str | None, session_dir: Path, report_path: Path) -> str:
    if scan_id:
        return scan_id
    if session_dir.name:
        return session_dir.name
    return report_path.parent.name or f"scan_{utc_now().replace(':', '').replace('-', '')}"


def _resolve_session_dir(
    session_dir: Path | None,
    capture_metadata: dict[str, Any] | None,
    report_path: Path,
) -> Path:
    if session_dir is not None:
        return session_dir.expanduser().resolve()
    if capture_metadata:
        value = capture_metadata.get("session_dir")
        if value:
            return Path(str(value)).expanduser().resolve()
    return report_path.parent


def _derive_created_at(capture_metadata: dict[str, Any] | None) -> str | None:
    if not capture_metadata:
        return None
    value = capture_metadata.get("created_at")
    if value is None:
        return None
    return str(value)


def _load_optional_json(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    resolved_path = path.expanduser().resolve()
    payload = _read_json(resolved_path)
    if not isinstance(payload, dict):
        raise RuntimeError(f"Ungueltiges JSON-Dokument: {resolved_path}")
    return payload


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_optional_path(value: object) -> Path | None:
    if value is None:
        return None
    return Path(str(value)).expanduser().resolve()


def _normalize_text(value: object) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split()).strip()


def _bbox_center_y(bbox: object) -> float:
    if not isinstance(bbox, list) or not bbox:
        return 0.0
    values: list[float] = []
    for point in bbox:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        try:
            values.append(float(point[1]))
        except (TypeError, ValueError):
            continue
    if not values:
        return 0.0
    return sum(values) / len(values)


def _bbox_bottom(bbox: object) -> float:
    if not isinstance(bbox, list) or not bbox:
        return 0.0
    values: list[float] = []
    for point in bbox:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        try:
            values.append(float(point[1]))
        except (TypeError, ValueError):
            continue
    if not values:
        return 0.0
    return max(values)


def _bbox_top(bbox: object) -> float:
    if not isinstance(bbox, list) or not bbox:
        return 0.0
    values: list[float] = []
    for point in bbox:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        try:
            values.append(float(point[1]))
        except (TypeError, ValueError):
            continue
    if not values:
        return 0.0
    return min(values)


def _bbox_height(bbox: object) -> float:
    return max(0.0, _bbox_bottom(bbox) - _bbox_top(bbox))


def _line_gap(line_entries: list[dict[str, Any]], upper_index: int, lower_index: int) -> float:
    if upper_index < 0 or lower_index >= len(line_entries):
        return 0.0
    upper_bottom = _bbox_bottom(line_entries[upper_index].get("bbox"))
    lower_top = _bbox_top(line_entries[lower_index].get("bbox"))
    return max(0.0, lower_top - upper_bottom)


def _parse_chapter_number(value: str | None) -> int | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    roman = text.upper()
    total = 0
    previous = 0
    for character in reversed(roman):
        current = _ROMAN_VALUES.get(character)
        if current is None:
            return None
        if current < previous:
            total -= current
        else:
            total += current
            previous = current
    return total or None


def _looks_like_heading_line(value: str) -> bool:
    normalized = _normalize_text(value)
    if not normalized:
        return False
    if len(normalized) > 80:
        return False
    if normalized.lower() in _CHAPTER_HEADING_BLOCKLIST:
        return False
    if normalized.endswith((".", "!", "?", "…", ":", ";")):
        return False
    if normalized.count(" ") >= 10:
        return False
    if len(normalized.split()) > 8:
        return False
    return True


def _looks_like_heading_shape(value: str) -> bool:
    normalized = _normalize_text(value)
    if not normalized:
        return False
    letters = [character for character in normalized if character.isalpha()]
    if not letters:
        return False
    uppercase_ratio = sum(1 for character in letters if character.isupper()) / len(letters)
    if uppercase_ratio >= 0.8:
        return True
    words = normalized.split()
    if len(words) <= 5 and all(word[:1].isupper() for word in words if word):
        return True
    return False


def _is_heading_only_text(text: str, chapter_markers: list[PageChapterMarker]) -> bool:
    if len(chapter_markers) != 1:
        return False
    marker = chapter_markers[0]
    if marker.chapter_heading is None:
        return False
    if marker.chapter_number is not None:
        return False
    return _normalize_text(text) == _normalize_text(marker.chapter_heading)


def _is_chapter_marker_block_only(text: str, chapter_markers: list[PageChapterMarker]) -> bool:
    if len(chapter_markers) != 1:
        return False
    marker = chapter_markers[0]
    if marker.line_index != 0:
        return False
    normalized_lines = [_normalize_text(line) for line in text.splitlines() if _normalize_text(line)]
    if not normalized_lines:
        return False
    if len(normalized_lines) > marker.consumed_line_count:
        return False
    return marker.detection_kind in {
        "explicit_label",
        "explicit_inline_heading",
        "explicit_following_heading",
        "heading_only_page",
    }


def _format_page_label(page: PageRecord) -> str:
    if page.page_number is not None:
        return f"{page.side}:{page.page_number}"
    return f"{page.side}:{page.page_id}"
