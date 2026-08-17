from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
import shutil
from tempfile import NamedTemporaryFile
from typing import Any

from abr.book.models import BookRecord, ChapterRecord, PageRecord, ScanRecord, SummaryRecord


class BookStore:
    ISO15693_TAGS_FILENAME = "iso15693_tag_ids.txt"

    def __init__(self, library_root: Path) -> None:
        self.library_root = Path(library_root)
        self.library_root.mkdir(parents=True, exist_ok=True)

    def ensure_book(
        self,
        tag_id: str,
        seen_at: str | None = None,
        *,
        language: str | None = None,
    ) -> BookRecord:
        if language is not None and language not in {"de", "en"}:
            raise ValueError(f"Nicht unterstuetzte Buchsprache: {language!r}")
        normalized_tag_id = normalize_tag_id(tag_id)
        now = seen_at or utc_now()
        record = self.load_book(normalized_tag_id)
        if record is None:
            record = BookRecord(
                tag_id=normalized_tag_id,
                created_at=now,
                last_seen_at=now,
                language=language,
            )
        else:
            effective_language = record.language or "de"
            if language is not None and language != effective_language:
                raise RuntimeError(
                    f"Buch {normalized_tag_id} ist als Sprache {effective_language} gespeichert; "
                    f"aktives Sprachprofil ist {language}. Bitte zuerst die Buchsprache umschalten."
                )
            record = replace(
                record,
                last_seen_at=now,
                language=("de" if language == "de" and record.language is None else record.language),
            )
        self.save_book(record)
        self._ensure_book_layout(normalized_tag_id)
        return record

    def require_book_language(self, tag_id: str, language: str) -> BookRecord:
        if language not in {"de", "en"}:
            raise ValueError(f"Nicht unterstuetzte Buchsprache: {language!r}")
        normalized_tag_id = normalize_tag_id(tag_id)
        record = self.load_book(normalized_tag_id)
        if record is None:
            raise RuntimeError(f"Buch nicht gefunden: {normalized_tag_id}")
        effective_language = record.language or "de"
        if effective_language != language:
            raise RuntimeError(
                f"Buch {normalized_tag_id} ist als Sprache {effective_language} gespeichert; "
                f"aktives Sprachprofil ist {language}. Bitte zuerst die Buchsprache umschalten."
            )
        return record

    def book_dir(self, tag_id: str) -> Path:
        return self.library_root / normalize_tag_id(tag_id)

    def load_book(self, tag_id: str) -> BookRecord | None:
        path = self.book_dir(tag_id) / "book.json"
        if not path.exists():
            return None
        return BookRecord.from_dict(_read_json(path))

    def save_book(self, record: BookRecord) -> Path:
        book_dir = self.book_dir(record.tag_id)
        self._ensure_book_layout(record.tag_id)
        path = book_dir / "book.json"
        _write_json(path, record.to_dict())
        return path

    def save_scan(self, tag_id: str, record: ScanRecord) -> Path:
        scan_dir = self.book_dir(tag_id) / "scans" / record.scan_id
        scan_dir.mkdir(parents=True, exist_ok=True)
        path = scan_dir / "manifest.json"
        _write_json(path, record.to_dict())
        return path

    def load_scan(self, tag_id: str, scan_id: str) -> ScanRecord | None:
        path = self.book_dir(tag_id) / "scans" / scan_id / "manifest.json"
        if not path.exists():
            return None
        return ScanRecord.from_dict(_read_json(path))

    def save_page(self, tag_id: str, record: PageRecord) -> Path:
        pages_dir = self.book_dir(tag_id) / "pages"
        pages_dir.mkdir(parents=True, exist_ok=True)
        path = pages_dir / f"{page_storage_key(record)}.json"
        _write_json(path, record.to_dict())
        return path

    def load_page(self, tag_id: str, page_key: int | str) -> PageRecord | None:
        path = self.book_dir(tag_id) / "pages" / f"{page_lookup_key(page_key)}.json"
        if not path.exists():
            return None
        return PageRecord.from_dict(_read_json(path))

    def list_pages(self, tag_id: str) -> list[PageRecord]:
        pages_dir = self.book_dir(tag_id) / "pages"
        if not pages_dir.exists():
            return []
        records = [PageRecord.from_dict(_read_json(path)) for path in sorted(pages_dir.glob("*.json"))]
        return sorted(records, key=lambda record: ((record.page_number is None), record.page_number or 0, record.page_id))

    def save_chapter(self, tag_id: str, record: ChapterRecord, text: str | None = None) -> Path:
        chapter_dir = self.book_dir(tag_id) / "chapters" / record.chapter_id
        chapter_dir.mkdir(parents=True, exist_ok=True)
        if text is not None:
            text_path = chapter_dir / "text.txt"
            _write_text(text_path, text + ("\n" if text else ""))
            record = replace(record, text_path=text_path)
        path = chapter_dir / "chapter.json"
        _write_json(path, record.to_dict())
        return path

    def load_chapter(self, tag_id: str, chapter_id: str) -> ChapterRecord | None:
        path = self.book_dir(tag_id) / "chapters" / chapter_id / "chapter.json"
        if not path.exists():
            return None
        return ChapterRecord.from_dict(_read_json(path))

    def list_chapters(self, tag_id: str) -> list[ChapterRecord]:
        chapters_dir = self.book_dir(tag_id) / "chapters"
        if not chapters_dir.exists():
            return []
        records = [
            ChapterRecord.from_dict(_read_json(path))
            for path in sorted(chapters_dir.glob("*/chapter.json"))
        ]
        return sorted(
            records,
            key=lambda record: (
                (record.start_page is None),
                record.start_page or 0,
                record.chapter_id,
            ),
        )

    def save_summary(self, tag_id: str, filename: str, record: SummaryRecord) -> Path:
        summary_path = self.book_dir(tag_id) / "summaries" / filename
        if summary_path.suffix != ".json":
            raise ValueError("Summary-Dateien muessen auf .json enden.")
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        _write_json(summary_path, record.to_dict())
        return summary_path

    def load_summary(self, tag_id: str, filename: str) -> SummaryRecord | None:
        path = self.book_dir(tag_id) / "summaries" / filename
        if not path.exists():
            return None
        return SummaryRecord.from_dict(_read_json(path))

    def save_runtime_state(self, tag_id: str, filename: str, payload: dict[str, Any]) -> Path:
        path = self.book_dir(tag_id) / "state" / filename
        if path.suffix != ".json":
            raise ValueError("Runtime-State-Dateien muessen auf .json enden.")
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_json(path, payload)
        return path

    def load_runtime_state(self, tag_id: str, filename: str) -> dict[str, Any] | None:
        path = self.book_dir(tag_id) / "state" / filename
        if not path.exists():
            return None
        payload = _read_json(path)
        if not isinstance(payload, dict):
            raise RuntimeError(f"Ungueltiger Runtime-State in {path}")
        return payload

    def delete_book(self, tag_id: str) -> bool:
        book_dir = self.book_dir(tag_id)
        if not book_dir.exists():
            return False
        shutil.rmtree(book_dir)
        return True

    def associate_iso15693_tag(self, tag_id: str, iso15693_tag_id: str) -> Path:
        primary = normalize_tag_id(tag_id)
        secondary = normalize_tag_id(iso15693_tag_id)
        path = self.book_dir(primary) / self.ISO15693_TAGS_FILENAME
        existing = self.load_iso15693_tag_ids(primary)
        if secondary not in existing:
            existing.append(secondary)
            _write_text(path, "".join(f"{value}\n" for value in existing))
        return path

    def load_iso15693_tag_ids(self, tag_id: str) -> list[str]:
        path = self.book_dir(tag_id) / self.ISO15693_TAGS_FILENAME
        if not path.exists():
            return []
        return [
            normalize_tag_id(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def find_book_by_iso15693_tag(self, iso15693_tag_id: str) -> str | None:
        wanted = normalize_tag_id(iso15693_tag_id)
        if not self.library_root.exists():
            return None
        for book_json in sorted(self.library_root.glob("*/book.json")):
            tag_id = book_json.parent.name
            if wanted in self.load_iso15693_tag_ids(tag_id):
                return normalize_tag_id(tag_id)
        return None

    def _ensure_book_layout(self, tag_id: str) -> None:
        book_dir = self.book_dir(tag_id)
        for relative_dir in ("state", "scans", "pages", "chapters", "summaries"):
            (book_dir / relative_dir).mkdir(parents=True, exist_ok=True)


def page_storage_key(record: PageRecord) -> str:
    if record.page_number is not None:
        return f"{record.page_number:04d}"
    return sanitize_storage_key(record.page_id)


def page_lookup_key(page_key: int | str) -> str:
    if isinstance(page_key, int):
        return f"{page_key:04d}"
    text = str(page_key).strip()
    if text.isdigit():
        return f"{int(text):04d}"
    return sanitize_storage_key(text)


def normalize_tag_id(tag_id: str) -> str:
    normalized = str(tag_id).strip().upper()
    if not normalized:
        raise ValueError("Die Tag-ID darf nicht leer sein.")
    return sanitize_storage_key(normalized)


def sanitize_storage_key(value: str) -> str:
    if not value:
        raise ValueError("Storage-Key darf nicht leer sein.")
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-")
    if any(character not in allowed for character in value):
        raise ValueError(f"Ungueltiger Storage-Key: {value!r}")
    if value in {".", ".."}:
        raise ValueError(f"Ungueltiger Storage-Key: {value!r}")
    return value


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    _write_text(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        temp_path = Path(handle.name)
    temp_path.replace(path)
