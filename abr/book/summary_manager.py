from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from queue import Empty, Queue
from threading import Event, RLock, Thread
import hashlib
import json
import re
import urllib.error
import urllib.request
from typing import Callable

from abr.google_cloud_auth import get_google_access_token, get_google_project_id, get_google_quota_project
from abr.book.models import ChapterRecord, SummaryRecord
from abr.book.store import BookStore, normalize_tag_id, utc_now
from abr.language_config import get_language_profile


@dataclass(frozen=True, slots=True)
class SummaryManagerConfig:
    chapter_summary_suffix: str = "_summary.json"
    book_summary_filename: str = "book_so_far_summary.json"
    chapter_summary_target_pages: float = 1.5
    book_summary_target_pages: float = 1.5
    maximum_output_tokens: int = 2048
    target_page_words: int = 250
    word_limit_tolerance: float = 0.10
    language: str = "de"

    def __post_init__(self) -> None:
        profile = get_language_profile(self.language)
        object.__setattr__(self, "language", profile.code)


_SUMMARY_LENGTH_POLICY_VERSION = 1


@dataclass(frozen=True, slots=True)
class GeminiSummaryConfig:
    model: str = "gemini-3.5-flash"
    project_id: str | None = None
    location: str = "global"
    timeout_s: float = 120.0
    temperature: float = 0.4


class SummaryBackend(ABC):
    @abstractmethod
    def is_available(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def model_name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def generate(self, *, instruction: str, prompt: str, max_output_tokens: int | None = None) -> str:
        raise NotImplementedError


class GeminiSummaryBackend(SummaryBackend):
    def __init__(self, config: GeminiSummaryConfig = GeminiSummaryConfig()) -> None:
        self.config = config

    def is_available(self) -> bool:
        try:
            return self._resolve_project_id() is not None and bool(get_google_access_token()[0])
        except RuntimeError:
            return False

    def model_name(self) -> str:
        return self.config.model

    def generate(self, *, instruction: str, prompt: str, max_output_tokens: int | None = None) -> str:
        project_id = self._resolve_project_id()
        if project_id is None:
            raise RuntimeError(
                "Gemini-Zusammenfassung angefordert, aber kein Google-Cloud-Projekt konnte ermittelt werden. "
                "Setze GOOGLE_CLOUD_PROJECT oder konfiguriere `gcloud config set project ...`."
            )
        payload = self._perform_generate_request(
            project_id=project_id,
            instruction=instruction,
            prompt=prompt,
            max_output_tokens=max_output_tokens,
        )
        extracted = _extract_text_from_generate_content_response(payload)
        if extracted and not _response_was_truncated(payload):
            return _normalize_summary_text(extracted)
        if max_output_tokens is not None and _response_can_be_retried_without_output_limit(payload):
            retry_payload = self._perform_generate_request(
                project_id=project_id,
                instruction=instruction,
                prompt=prompt,
                max_output_tokens=None,
            )
            extracted = _extract_text_from_generate_content_response(retry_payload)
            if extracted and not _response_was_truncated(retry_payload):
                return _normalize_summary_text(extracted)
            payload = retry_payload
        detail = _describe_generate_content_response(payload)
        if max_output_tokens is not None:
            detail = f"{detail}; maxOutputTokens={max_output_tokens}"
        raise RuntimeError(f"Gemini-Antwort enthaelt keinen vollstaendigen verwertbaren Text ({detail}).")

    def _perform_generate_request(
        self,
        *,
        project_id: str,
        instruction: str,
        prompt: str,
        max_output_tokens: int | None,
    ) -> dict[str, object]:
        access_token, _expires_in = get_google_access_token()
        quota_project = get_google_quota_project()
        location = self.config.location.strip() or "global"
        service_endpoint = _gemini_service_endpoint(location)
        request = urllib.request.Request(
            (
                f"https://{service_endpoint}/v1/projects/{project_id}/"
                f"locations/{location}/publishers/google/models/{self.config.model}:generateContent"
            ),
            data=json.dumps(
                {
                    "systemInstruction": {
                        "parts": [{"text": instruction}],
                    },
                    "contents": [
                        {
                            "role": "user",
                            "parts": [{"text": prompt}],
                        }
                    ],
                    "generationConfig": {
                        "temperature": self.config.temperature,
                        **({"maxOutputTokens": max_output_tokens} if max_output_tokens is not None else {}),
                    },
                }
            ).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {access_token}",
                **({"x-goog-user-project": quota_project} if quota_project else {}),
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_s) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"Gemini-Anfrage fehlgeschlagen ({exc.code}): {detail or exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Gemini-Anfrage fehlgeschlagen: {exc.reason}") from exc

    def _resolve_project_id(self) -> str | None:
        configured = self.config.project_id.strip() if self.config.project_id else None
        if configured:
            return configured
        return get_google_project_id()


class SummaryManager:
    def __init__(
        self,
        store: BookStore,
        backend: SummaryBackend,
        config: SummaryManagerConfig = SummaryManagerConfig(),
    ) -> None:
        self.store = store
        self.backend = backend
        self.config = config
        self._lock = RLock()

    def is_available(self) -> bool:
        return self.backend.is_available()

    def has_completed_chapters(self, tag_id: str) -> bool:
        normalized_tag_id = normalize_tag_id(tag_id)
        self.store.require_book_language(normalized_tag_id, self.config.language)
        return bool(self.store.list_chapters(normalized_tag_id))

    def summarize_chapter(self, tag_id: str, chapter_id: str, *, force: bool = False) -> SummaryRecord:
        normalized_tag_id = normalize_tag_id(tag_id)
        self.store.require_book_language(normalized_tag_id, self.config.language)
        with self._lock:
            chapter = self.store.load_chapter(normalized_tag_id, chapter_id)
            if chapter is None:
                raise RuntimeError(f"Kapitel nicht gefunden: {chapter_id}")
            existing = self._load_chapter_summary(chapter)
            target_pages = self.config.chapter_summary_target_pages
            target_words = _target_pages_to_target_words(target_pages, self.config)
            max_output_tokens = self.config.maximum_output_tokens
            if (
                existing is not None
                and not force
                and _summary_uses_language(existing, self.config.language)
                and _summary_uses_target_pages(existing, target_pages)
                and existing.metadata.get("generation_complete") is True
                and _summary_uses_word_length_policy(existing, target_words)
            ):
                return existing
            chapter_text = chapter.text_path.read_text(encoding="utf-8").strip()
            if not chapter_text:
                raise RuntimeError(f"Kapiteltext fehlt oder ist leer: {chapter.chapter_id}")
            summary_text, initial_word_count = self._generate_summary_with_word_limit(
                instruction=_chapter_summary_instruction(self.config.language),
                prompt=_build_chapter_summary_prompt(
                    chapter,
                    chapter_text,
                    target_pages=target_pages,
                    target_words=target_words,
                    language=self.config.language,
                ),
                target_words=target_words,
                max_output_tokens=max_output_tokens,
            )
            record = SummaryRecord(
                summary_id=f"{chapter.chapter_id}_summary",
                summary_type="chapter",
                updated_at=utc_now(),
                text=summary_text,
                source_chapter_ids=[chapter.chapter_id],
                model_name=self.backend.model_name(),
                metadata={
                    "chapter_id": chapter.chapter_id,
                    "start_page": chapter.start_page,
                    "end_page": chapter.end_page,
                    "target_pages": target_pages,
                    "target_words": target_words,
                    "actual_word_count": _count_words(summary_text),
                    "initial_word_count": initial_word_count,
                    "length_policy_version": _SUMMARY_LENGTH_POLICY_VERSION,
                    "max_output_tokens": max_output_tokens,
                    "generation_complete": True,
                    "language": self.config.language,
                },
            )
            filename = f"{chapter.chapter_id}{self.config.chapter_summary_suffix}"
            summary_path = self.store.save_summary(normalized_tag_id, filename, record)
            updated_chapter = replace(chapter, summary_path=summary_path)
            self.store.save_chapter(normalized_tag_id, updated_chapter)
            return record

    def summarize_latest_chapter(self, tag_id: str, *, force: bool = False) -> tuple[ChapterRecord, SummaryRecord]:
        normalized_tag_id = normalize_tag_id(tag_id)
        self.store.require_book_language(normalized_tag_id, self.config.language)
        chapters = _chapters_in_sequence_order(self.store.list_chapters(normalized_tag_id))
        if not chapters:
            raise RuntimeError("Es liegt noch kein abgeschlossener Abschnitt vor.")
        chapter = chapters[-1]
        summary = self.summarize_chapter(normalized_tag_id, chapter.chapter_id, force=force)
        refreshed = self.store.load_chapter(normalized_tag_id, chapter.chapter_id) or chapter
        return refreshed, summary

    def summarize_chapter_progress(
        self,
        tag_id: str,
        pending_text: str,
        *,
        pending_page_ids: tuple[str, ...] = (),
        pending_page_numbers: tuple[int, ...] = (),
    ) -> tuple[ChapterRecord | None, SummaryRecord]:
        """Build a disposable summary from the latest chapter summary and open text."""
        normalized_tag_id = normalize_tag_id(tag_id)
        self.store.require_book_language(normalized_tag_id, self.config.language)
        normalized_pending_text = pending_text.strip()
        if not normalized_pending_text:
            raise RuntimeError("Es liegt kein offener Text fuer eine temporaere Zusammenfassung vor.")
        with self._lock:
            chapters = _chapters_in_sequence_order(self.store.list_chapters(normalized_tag_id))
            latest_chapter = chapters[-1] if chapters else None
            latest_summary = (
                self.summarize_chapter(normalized_tag_id, latest_chapter.chapter_id)
                if latest_chapter is not None
                else None
            )
            target_pages = self.config.chapter_summary_target_pages
            target_words = _target_pages_to_target_words(target_pages, self.config)
            max_output_tokens = self.config.maximum_output_tokens
            summary_text, initial_word_count = self._generate_summary_with_word_limit(
                instruction=_chapter_progress_instruction(self.config.language),
                prompt=_build_chapter_progress_prompt(
                    latest_summary=latest_summary,
                    pending_text=normalized_pending_text,
                    target_pages=target_pages,
                    target_words=target_words,
                    language=self.config.language,
                ),
                target_words=target_words,
                max_output_tokens=max_output_tokens,
            )
            record = SummaryRecord(
                summary_id="temporary_chapter_progress",
                summary_type="temporary_chapter_progress",
                updated_at=utc_now(),
                text=summary_text,
                source_chapter_ids=(
                    [latest_chapter.chapter_id] if latest_chapter is not None else []
                ),
                model_name=self.backend.model_name(),
                metadata={
                    "temporary": True,
                    "pending_page_ids": list(pending_page_ids),
                    "pending_page_numbers": list(pending_page_numbers),
                    "pending_text_characters": len(normalized_pending_text),
                    "target_pages": target_pages,
                    "target_words": target_words,
                    "actual_word_count": _count_words(summary_text),
                    "initial_word_count": initial_word_count,
                    "length_policy_version": _SUMMARY_LENGTH_POLICY_VERSION,
                    "max_output_tokens": max_output_tokens,
                    "generation_complete": True,
                    "language": self.config.language,
                },
            )
            return latest_chapter, record

    def load_chapter_summary(self, tag_id: str, chapter_id: str) -> SummaryRecord | None:
        normalized_tag_id = normalize_tag_id(tag_id)
        self.store.require_book_language(normalized_tag_id, self.config.language)
        chapter = self.store.load_chapter(normalized_tag_id, chapter_id)
        if chapter is None:
            raise RuntimeError(f"Kapitel nicht gefunden: {chapter_id}")
        return self._load_chapter_summary(chapter)

    def load_latest_chapter_summary(self, tag_id: str) -> tuple[ChapterRecord, SummaryRecord] | None:
        normalized_tag_id = normalize_tag_id(tag_id)
        self.store.require_book_language(normalized_tag_id, self.config.language)
        chapters = _chapters_in_sequence_order(self.store.list_chapters(normalized_tag_id))
        for chapter in reversed(chapters):
            summary = self._load_chapter_summary(chapter)
            if summary is None:
                continue
            if summary.summary_type != "chapter":
                continue
            return chapter, summary
        return None

    def summarize_book_so_far(self, tag_id: str, *, force: bool = False) -> SummaryRecord:
        normalized_tag_id = normalize_tag_id(tag_id)
        self.store.require_book_language(normalized_tag_id, self.config.language)
        with self._lock:
            existing = self.store.load_summary(normalized_tag_id, self.config.book_summary_filename)
            chapters = _chapters_in_sequence_order(self.store.list_chapters(normalized_tag_id))
            if not chapters:
                raise RuntimeError("Es liegen noch keine abgeschlossenen Abschnitte vor.")
            source_chapter_ids = [chapter.chapter_id for chapter in chapters]
            target_pages = self.config.book_summary_target_pages
            target_words = _target_pages_to_target_words(target_pages, self.config)
            max_output_tokens = self.config.maximum_output_tokens
            chapter_summaries = [
                self.summarize_chapter(normalized_tag_id, chapter.chapter_id)
                for chapter in chapters
            ]
            chapter_summary_fingerprint = _chapter_summaries_fingerprint(
                chapters,
                chapter_summaries,
            )
            if (
                existing is not None
                and existing.source_chapter_ids == source_chapter_ids
                and not force
                and _summary_uses_language(existing, self.config.language)
                and _summary_uses_target_pages(existing, target_pages)
                and existing.metadata.get("generation_complete") is True
                and _summary_uses_word_length_policy(existing, target_words)
                and existing.metadata.get("chapter_summary_fingerprint")
                == chapter_summary_fingerprint
            ):
                return existing
            summary_text, initial_word_count = self._generate_summary_with_word_limit(
                instruction=_book_summary_instruction(self.config.language),
                prompt=_build_book_summary_prompt(
                    chapters,
                    chapter_summaries,
                    target_pages=target_pages,
                    target_words=target_words,
                    language=self.config.language,
                ),
                target_words=target_words,
                max_output_tokens=max_output_tokens,
            )
            record = SummaryRecord(
                summary_id="book_so_far_summary",
                summary_type="book_so_far",
                updated_at=utc_now(),
                text=summary_text,
                source_chapter_ids=source_chapter_ids,
                model_name=self.backend.model_name(),
                metadata={
                    "chapter_count": len(chapters),
                    "target_pages": target_pages,
                    "target_words": target_words,
                    "actual_word_count": _count_words(summary_text),
                    "initial_word_count": initial_word_count,
                    "length_policy_version": _SUMMARY_LENGTH_POLICY_VERSION,
                    "max_output_tokens": max_output_tokens,
                    "chapter_summary_fingerprint": chapter_summary_fingerprint,
                    "generation_complete": True,
                    "language": self.config.language,
                },
            )
            self.store.save_summary(normalized_tag_id, self.config.book_summary_filename, record)
            return record

    def _generate_summary_with_word_limit(
        self,
        *,
        instruction: str,
        prompt: str,
        target_words: int,
        max_output_tokens: int,
    ) -> tuple[str, int]:
        summary_text = self.backend.generate(
            instruction=instruction,
            prompt=prompt,
            max_output_tokens=max_output_tokens,
        )
        initial_word_count = _count_words(summary_text)
        tolerated_words = round(target_words * (1.0 + max(0.0, self.config.word_limit_tolerance)))
        if initial_word_count <= tolerated_words:
            return summary_text, initial_word_count
        shortened_text = self.backend.generate(
            instruction=_shortening_instruction(self.config.language),
            prompt=_build_shortening_prompt(
                summary_text,
                target_words=target_words,
                language=self.config.language,
            ),
            max_output_tokens=max_output_tokens,
        )
        shortened_word_count = _count_words(shortened_text)
        if shortened_word_count > tolerated_words:
            raise RuntimeError(
                "Gemini hat die geforderte Laengengrenze auch nach dem Kuerzungsdurchlauf "
                f"ueberschritten ({shortened_word_count} statt hoechstens {tolerated_words} Woerter)."
            )
        return shortened_text, initial_word_count

    def _load_chapter_summary(self, chapter: ChapterRecord) -> SummaryRecord | None:
        if chapter.summary_path is None or not chapter.summary_path.exists():
            return None
        return SummaryRecord.from_dict(json.loads(chapter.summary_path.read_text(encoding="utf-8")))


def _chapter_summaries_fingerprint(
    chapters: list[ChapterRecord],
    summaries: list[SummaryRecord],
) -> str:
    digest = hashlib.sha256()
    for chapter, summary in zip(chapters, summaries, strict=True):
        digest.update(chapter.chapter_id.encode("utf-8"))
        digest.update(b"\0")
        digest.update(summary.updated_at.encode("utf-8"))
        digest.update(b"\0")
        digest.update(summary.text.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class _SummaryTask:
    tag_id: str
    chapter_id: str


class SummaryService:
    def __init__(
        self,
        manager: SummaryManager,
        *,
        status_callback: Callable[[str], None] | None = None,
    ) -> None:
        self.manager = manager
        self.status_callback = status_callback
        self._queue: Queue[_SummaryTask | None] = Queue()
        self._pending: set[tuple[str, str]] = set()
        self._pending_lock = RLock()
        self._stop_event = Event()
        self._thread = Thread(target=self._run, name="abr-summary-service", daemon=True)
        self._thread.start()

    def submit_chapter_summary(self, tag_id: str, chapter_id: str) -> None:
        task_key = (normalize_tag_id(tag_id), chapter_id)
        with self._pending_lock:
            if task_key in self._pending:
                return
            self._pending.add(task_key)
        self._queue.put(_SummaryTask(*task_key))
        self._emit_status(f"Kapitelzusammenfassung eingeplant: {chapter_id}.")

    def shutdown(self, join_timeout_s: float = 1.0) -> None:
        self._stop_event.set()
        self._queue.put(None)
        self._thread.join(timeout=join_timeout_s)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                task = self._queue.get(timeout=0.1)
            except Empty:
                continue
            if task is None:
                self._queue.task_done()
                return
            try:
                if not self.manager.is_available():
                    self._emit_status(
                        f"Kapitelzusammenfassung uebersprungen: Gemini ist nicht verfuegbar ({task.chapter_id})."
                    )
                    continue
                self.manager.summarize_chapter(task.tag_id, task.chapter_id)
                self._emit_status(f"Kapitelzusammenfassung gespeichert: {task.chapter_id}.")
            except BaseException as exc:  # pragma: no cover - defensive runtime propagation
                self._emit_status(f"Kapitelzusammenfassung fehlgeschlagen ({task.chapter_id}): {exc}")
            finally:
                with self._pending_lock:
                    self._pending.discard((task.tag_id, task.chapter_id))
                self._queue.task_done()

    def _emit_status(self, message: str) -> None:
        if self.status_callback is not None:
            self.status_callback(message)


def _build_chapter_summary_prompt(
    chapter: ChapterRecord,
    text: str,
    *,
    target_pages: float,
    target_words: int,
    language: str = "de",
) -> str:
    page_text = _format_page_range(chapter.start_page, chapter.end_page, language=language)
    if language == "en":
        return (
            "Summarize the following book section in English for later audio playback. "
            f"The summary should be about {_format_target_pages(target_pages)} pages long "
            f"and must contain no more than {target_words} words. It should be accurate and "
            "clearly identify the important characters, conflicts, plot turns, and unresolved questions.\n\n"
            f"Section: {chapter.chapter_id} ({page_text})\n\n"
            "Source text:\n"
            f"{text}"
        )
    return (
        "Fasse den folgenden Buchabschnitt auf Deutsch fuer spaetere Audioausgabe zusammen. "
        f"Die Zusammenfassung soll ungefaehr {_format_target_pages(target_pages)} Textseiten entsprechen "
        f"und darf hoechstens {target_words} Woerter enthalten. Sie soll "
        "inhaltlich praezise sein und die wichtigen Figuren, Konflikte, Wendungen und "
        "offenen Fragen klar benennen.\n\n"
        f"Abschnitt: {chapter.chapter_id} ({page_text})\n\n"
        "Quelltext:\n"
        f"{text}"
    )


def _build_book_summary_prompt(
    chapters: list[ChapterRecord],
    summaries: list[SummaryRecord],
    *,
    target_pages: float,
    target_words: int,
    language: str = "de",
) -> str:
    parts: list[str] = []
    for chapter, summary in zip(chapters, summaries, strict=False):
        parts.append(
            f"{chapter.chapter_id} ({_format_page_range(chapter.start_page, chapter.end_page, language=language)}):\n{summary.text.strip()}"
        )
    if language == "en":
        return (
            "Create a coherent 'Previously in the book' recap from these summaries. "
            f"It should read naturally aloud, contain no lists, be about {_format_target_pages(target_pages)} "
            f"pages long, and contain no more than {target_words} words. Condense the development "
            "of the story across all available sections.\n\n"
            "Available section summaries:\n\n"
            + "\n\n".join(parts)
        )
    return (
        "Erstelle daraus eine zusammenhaengende Rueckschau im Stil 'Was bisher geschah'. "
        f"Sie soll gut vorlesbar sein, keine Aufzaehlungen enthalten, ungefaehr {_format_target_pages(target_pages)} "
        f"Textseiten umfassen und darf hoechstens {target_words} Woerter enthalten. Sie soll die Entwicklung "
        "der Handlung ueber die vorhandenen Abschnitte hinweg "
        "verdichten.\n\n"
        "Vorliegende Abschnittszusammenfassungen:\n\n"
        + "\n\n".join(parts)
    )


def _build_chapter_progress_prompt(
    *,
    latest_summary: SummaryRecord | None,
    pending_text: str,
    target_pages: float,
    target_words: int,
    language: str = "de",
) -> str:
    previous_text = (
        latest_summary.text.strip()
        if latest_summary is not None
        else (
            "There is no completed and summarized section yet."
            if language == "en"
            else "Es gibt noch keinen abgeschlossenen und zusammengefassten Abschnitt."
        )
    )
    if language == "en":
        return (
            "Create an up-to-date summary of the story so far. Integrate the new, unfinished text "
            "into the narrative; do not merely append it to the previous summary. "
            f"The result should be about {_format_target_pages(target_pages)} pages long and must "
            f"contain no more than {target_words} words.\n\n"
            "Summary of the latest completed section:\n"
            f"{previous_text}\n\n"
            "Text since that section:\n"
            f"{pending_text}"
        )
    return (
        "Erstelle eine aktuelle Zusammenfassung des bisherigen Handlungsstands. "
        "Der neue, noch nicht abgeschlossene Text muss inhaltlich eingearbeitet werden; "
        "haenge ihn nicht nur an die vorherige Zusammenfassung an. "
        f"Die Ausgabe soll ungefaehr {_format_target_pages(target_pages)} Textseiten entsprechen "
        f"und darf hoechstens {target_words} Woerter enthalten.\n\n"
        "Zusammenfassung des letzten abgeschlossenen Abschnitts:\n"
        f"{previous_text}\n\n"
        "Text seit diesem Abschnitt:\n"
        f"{pending_text}"
    )


def _format_target_pages(target_pages: float) -> str:
    normalized = max(0.1, target_pages)
    text = f"{normalized:.1f}"
    if text.endswith(".0"):
        return text[:-2]
    return text


def _target_pages_to_target_words(target_pages: float, config: SummaryManagerConfig) -> int:
    normalized_pages = max(0.1, target_pages)
    return max(25, round(normalized_pages * config.target_page_words))


def _count_words(text: str) -> int:
    return len(re.findall(r"\b\w+(?:[-\u2019']\w+)*\b", text, flags=re.UNICODE))


def _summary_uses_target_pages(summary: SummaryRecord, target_pages: float) -> bool:
    raw_target_pages = summary.metadata.get("target_pages")
    if isinstance(raw_target_pages, bool):
        return False
    if isinstance(raw_target_pages, (int, float)):
        stored_target_pages = float(raw_target_pages)
    elif isinstance(raw_target_pages, str):
        try:
            stored_target_pages = float(raw_target_pages)
        except ValueError:
            return False
    else:
        return False
    return abs(stored_target_pages - max(0.1, target_pages)) < 1e-6


def _summary_uses_word_length_policy(summary: SummaryRecord, target_words: int) -> bool:
    return (
        summary.metadata.get("length_policy_version") == _SUMMARY_LENGTH_POLICY_VERSION
        and summary.metadata.get("target_words") == target_words
    )


def _summary_uses_language(summary: SummaryRecord, language: str) -> bool:
    stored_language = summary.metadata.get("language")
    if stored_language is None:
        # Summary caches created before language profiles were always German.
        return language == "de"
    return stored_language == language


def _gemini_service_endpoint(location: str) -> str:
    normalized = location.strip().lower()
    if normalized == "global":
        return "aiplatform.googleapis.com"
    return f"{normalized}-aiplatform.googleapis.com"


_CHAPTER_SEQUENCE_RE = re.compile(r"^chapter_(\d+)$")


def _chapters_in_sequence_order(chapters: list[ChapterRecord]) -> list[ChapterRecord]:
    return sorted(chapters, key=_chapter_sequence_sort_key)


def _chapter_sequence_sort_key(chapter: ChapterRecord) -> tuple[int, str, str]:
    match = _CHAPTER_SEQUENCE_RE.match(chapter.chapter_id)
    if match is not None:
        return (0, f"{int(match.group(1)):09d}", chapter.chapter_id)
    return (1, chapter.created_at, chapter.chapter_id)


def _format_page_range(
    start_page: int | None,
    end_page: int | None,
    *,
    language: str = "de",
) -> str:
    if language == "en":
        if start_page is None and end_page is None:
            return "without page number"
        if start_page is None:
            return f"through page {end_page}"
        if end_page is None:
            return f"from page {start_page}"
        if start_page == end_page:
            return f"page {start_page}"
        return f"pages {start_page}-{end_page}"
    if start_page is None and end_page is None:
        return "ohne Seitenzahl"
    if start_page is None:
        return f"bis Seite {end_page}"
    if end_page is None:
        return f"ab Seite {start_page}"
    if start_page == end_page:
        return f"Seite {start_page}"
    return f"Seiten {start_page}-{end_page}"


def _chapter_summary_instruction(language: str) -> str:
    if language == "en":
        return (
            "You write English chapter summaries for later text-to-speech playback. Write coherent "
            "prose without lists, meta-commentary, or an introduction such as 'Here is a summary'. "
            "Use natural U.S. English."
        )
    return (
        "Du schreibst deutsche Kapitelzusammenfassungen fuer spaetere TTS-Ausgabe. "
        "Schreibe als zusammenhaengenden Fliesstext ohne Aufzaehlungen, ohne Meta-Kommentare "
        "und ohne Einleitung wie 'Hier ist eine Zusammenfassung'."
    )


def _chapter_progress_instruction(language: str) -> str:
    if language == "en":
        return (
            "You write an up-to-date English book recap for later text-to-speech playback. Combine "
            "the previous story and new text into coherent prose without lists, a heading, or "
            "meta-commentary. Use natural U.S. English."
        )
    return (
        "Du schreibst eine aktuelle deutsche Buchrueckschau fuer spaetere TTS-Ausgabe. "
        "Verbinde den bisherigen Stand und den neuen Text zu einem zusammenhaengenden "
        "Fliesstext ohne Aufzaehlungen, Ueberschrift oder Meta-Kommentar."
    )


def _book_summary_instruction(language: str) -> str:
    if language == "en":
        return (
            "You write an English 'Previously in the book' recap. Write natural, easy-to-narrate "
            "prose without lists, a heading, or meta-commentary. Use natural U.S. English."
        )
    return (
        "Du schreibst eine deutschsprachige 'Was bisher geschah'-Rueckschau fuer ein Buch. "
        "Schreibe als gut vorlesbaren Fliesstext ohne Aufzaehlungen, ohne Ueberschrift "
        "und ohne Meta-Kommentare."
    )


def _shortening_instruction(language: str) -> str:
    if language == "en":
        return (
            "You shorten English book summaries for natural audio playback. Preserve characters, "
            "the central plot, conflicts, turning points, and unresolved questions. Return only "
            "coherent prose without meta-commentary. Use natural U.S. English."
        )
    return (
        "Du kuerzt deutsche Buchzusammenfassungen fuer eine gut vorlesbare Audioausgabe. "
        "Bewahre Figuren, zentrale Handlung, Konflikte, Wendungen und offene Fragen. "
        "Schreibe nur zusammenhaengenden Fliesstext ohne Meta-Kommentar."
    )


def _build_shortening_prompt(summary_text: str, *, target_words: int, language: str) -> str:
    if language == "en":
        return (
            f"Shorten the following summary to no more than {target_words} words. End with a complete "
            "sentence and output only the shortened summary.\n\nSummary:\n"
            f"{summary_text}"
        )
    return (
        f"Kuerze die folgende Zusammenfassung auf hoechstens {target_words} Woerter. "
        "Beende den Text mit einem vollstaendigen Satz. Gib ausschliesslich die gekuerzte "
        f"Zusammenfassung aus.\n\nZusammenfassung:\n{summary_text}"
    )


def _extract_text_from_generate_content_response(payload: dict[str, object]) -> str | None:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        return None
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("content")
        if not isinstance(content, dict):
            continue
        parts = content.get("parts")
        extracted = _extract_text_from_parts(parts)
        if extracted:
            return extracted
    return None


def _extract_text_from_parts(raw_parts: object) -> str | None:
    if not isinstance(raw_parts, list):
        return None
    parts: list[str] = []
    for entry in raw_parts:
        if isinstance(entry, dict):
            text = entry.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
    if not parts:
        return None
    return "\n\n".join(parts)


def _response_can_be_retried_without_output_limit(payload: dict[str, object]) -> bool:
    prompt_feedback = payload.get("promptFeedback")
    if isinstance(prompt_feedback, dict) and prompt_feedback.get("blockReason"):
        return False
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        return True
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        finish_reason = candidate.get("finishReason")
        if isinstance(finish_reason, str) and finish_reason.upper() in {"SAFETY", "RECITATION", "PROHIBITED_CONTENT"}:
            return False
    return True


def _response_was_truncated(payload: dict[str, object]) -> bool:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        return False
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        finish_reason = candidate.get("finishReason")
        if isinstance(finish_reason, str) and finish_reason.upper() == "MAX_TOKENS":
            return True
    return False


def _describe_generate_content_response(payload: dict[str, object]) -> str:
    details: list[str] = []
    prompt_feedback = payload.get("promptFeedback")
    if isinstance(prompt_feedback, dict):
        block_reason = prompt_feedback.get("blockReason")
        if isinstance(block_reason, str) and block_reason:
            details.append(f"promptBlockReason={block_reason}")
    candidates = payload.get("candidates")
    if isinstance(candidates, list) and candidates:
        finish_reasons: list[str] = []
        candidate_count = 0
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            candidate_count += 1
            finish_reason = candidate.get("finishReason")
            if isinstance(finish_reason, str) and finish_reason:
                finish_reasons.append(finish_reason)
        if candidate_count:
            details.append(f"candidates={candidate_count}")
        if finish_reasons:
            details.append("finishReason=" + ",".join(finish_reasons))
    usage_metadata = payload.get("usageMetadata")
    if isinstance(usage_metadata, dict):
        for field_name in (
            "promptTokenCount",
            "candidatesTokenCount",
            "thoughtsTokenCount",
            "totalTokenCount",
        ):
            token_count = usage_metadata.get(field_name)
            if isinstance(token_count, int):
                details.append(f"{field_name}={token_count}")
    return ", ".join(details) if details else "keine Zusatzdetails von Gemini"


def _normalize_summary_text(text: str) -> str:
    lines = [line.rstrip() for line in text.strip().splitlines()]
    normalized: list[str] = []
    blank_run = 0
    for line in lines:
        if not line.strip():
            blank_run += 1
            if blank_run <= 1:
                normalized.append("")
            continue
        blank_run = 0
        normalized.append(line.strip())
    return "\n".join(normalized).strip()
