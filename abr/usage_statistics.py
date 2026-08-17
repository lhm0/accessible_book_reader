from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any, Iterator
from zoneinfo import ZoneInfo

import fcntl


DEFAULT_TIMEZONE = "Europe/Berlin"
PERIOD_START_HOUR = 4


class UsageStatisticsStore:
    """Persistent per-book counters for reporting days starting at 04:00."""

    def __init__(self, library_root: Path, *, timezone_name: str = DEFAULT_TIMEZONE) -> None:
        self.root = library_root.expanduser().resolve() / "usage_statistics"
        self.state_path = self.root / "current.json"
        self.lock_path = self.root / ".lock"
        self.archive_dir = self.root / "archive"
        self.timezone = ZoneInfo(timezone_name)
        self._thread_lock = Lock()

    def period_key(self, now: datetime | None = None) -> str:
        local_now = self._local_time(now)
        return (local_now - timedelta(hours=PERIOD_START_HOUR)).date().isoformat()

    def record_scanned_pages(
        self,
        tag_id: str,
        page_keys: list[str] | tuple[str, ...],
        *,
        now: datetime | None = None,
    ) -> None:
        normalized_keys = {str(key).strip() for key in page_keys if str(key).strip()}
        if not normalized_keys:
            return

        def update(book: dict[str, Any]) -> None:
            seen = set(str(key) for key in book.get("scanned_page_keys", []))
            new_keys = normalized_keys - seen
            seen.update(normalized_keys)
            book["scanned_page_keys"] = sorted(seen)
            book["pages_scanned"] = int(book.get("pages_scanned", 0)) + len(new_keys)

        self._update_book(tag_id, update, now=now)

    def record_audio_seconds(
        self,
        tag_id: str,
        seconds: float,
        *,
        now: datetime | None = None,
    ) -> None:
        if seconds <= 0:
            return

        def update(book: dict[str, Any]) -> None:
            book["audio_seconds"] = round(float(book.get("audio_seconds", 0.0)) + float(seconds), 3)

        self._update_book(tag_id, update, now=now)

    def record_chapter_summary(self, tag_id: str, *, now: datetime | None = None) -> None:
        self._increment(tag_id, "chapter_summary_uses", now=now)

    def record_book_summary(self, tag_id: str, *, now: datetime | None = None) -> None:
        self._increment(tag_id, "book_summary_uses", now=now)

    def closed_periods(self, *, now: datetime | None = None) -> list[dict[str, Any]]:
        current_key = self.period_key(now)
        with self._locked_state() as state:
            periods = state.get("periods", {})
            existing_keys = sorted(key for key in periods if key < current_key)
            archived_keys = self._archived_period_keys()

            if archived_keys:
                first_key = (datetime.fromisoformat(max(archived_keys)) + timedelta(days=1)).date().isoformat()
            elif existing_keys:
                first_key = existing_keys[0]
            else:
                first_key = (datetime.fromisoformat(current_key) - timedelta(days=1)).date().isoformat()

            result: list[dict[str, Any]] = []
            candidate = datetime.fromisoformat(first_key)
            current = datetime.fromisoformat(current_key)
            while candidate < current:
                key = candidate.date().isoformat()
                if key not in archived_keys:
                    period = periods.get(key)
                    if not isinstance(period, dict):
                        period = self._empty_period(key)
                    result.append(json.loads(json.dumps(period)))
                candidate += timedelta(days=1)
            return result

    def current_period(self, *, now: datetime | None = None) -> dict[str, Any] | None:
        current_key = self.period_key(now)
        with self._locked_state() as state:
            period = state.get("periods", {}).get(current_key)
            if not isinstance(period, dict):
                return None
            return json.loads(json.dumps(period))

    def archive_period(self, period_key: str) -> Path | None:
        with self._locked_state() as state:
            period = state.get("periods", {}).get(period_key)
            if not isinstance(period, dict):
                return None
            return self._archive_period_locked(state, period)

    def archive_reported_period(self, period: dict[str, Any]) -> Path:
        """Archive a successfully mailed period, including a synthetic empty one."""
        with self._locked_state() as state:
            return self._archive_period_locked(state, period)

    def _archive_period_locked(self, state: dict[str, Any], period: dict[str, Any]) -> Path:
        period_key = str(period["period_key"])
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        archive_path = self.archive_dir / f"{period_key}.json"
        temporary = archive_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(period, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temporary, archive_path)
        state.get("periods", {}).pop(period_key, None)
        return archive_path

    def _archived_period_keys(self) -> set[str]:
        if not self.archive_dir.is_dir():
            return set()
        keys: set[str] = set()
        for path in self.archive_dir.glob("*.json"):
            try:
                datetime.fromisoformat(path.stem)
            except ValueError:
                continue
            keys.add(path.stem)
        return keys

    @staticmethod
    def _empty_period(period_key: str) -> dict[str, Any]:
        next_key = (datetime.fromisoformat(period_key) + timedelta(days=1)).date().isoformat()
        return {
            "period_key": period_key,
            "starts_at": f"{period_key}T04:00:00",
            "ends_at": f"{next_key}T04:00:00",
            "books": {},
        }

    def _increment(self, tag_id: str, field: str, *, now: datetime | None) -> None:
        def update(book: dict[str, Any]) -> None:
            book[field] = int(book.get(field, 0)) + 1

        self._update_book(tag_id, update, now=now)

    def _update_book(self, tag_id: str, callback, *, now: datetime | None) -> None:
        normalized_tag = str(tag_id).strip().upper()
        if not normalized_tag:
            return
        key = self.period_key(now)
        with self._locked_state() as state:
            periods = state.setdefault("periods", {})
            period = periods.setdefault(
                key,
                {
                    "period_key": key,
                    "starts_at": f"{key}T04:00:00",
                    "ends_at": f"{(datetime.fromisoformat(key) + timedelta(days=1)).date().isoformat()}T04:00:00",
                    "books": {},
                },
            )
            book = period["books"].setdefault(
                normalized_tag,
                {
                    "tag_id": normalized_tag,
                    "pages_scanned": 0,
                    "audio_seconds": 0.0,
                    "chapter_summary_uses": 0,
                    "book_summary_uses": 0,
                    "scanned_page_keys": [],
                },
            )
            callback(book)

    def _local_time(self, now: datetime | None) -> datetime:
        if now is None:
            return datetime.now(self.timezone)
        if now.tzinfo is None:
            return now.replace(tzinfo=self.timezone)
        return now.astimezone(self.timezone)

    @contextmanager
    def _locked_state(self) -> Iterator[dict[str, Any]]:
        self.root.mkdir(parents=True, exist_ok=True)
        with self._thread_lock:
            with self.lock_path.open("a+", encoding="utf-8") as lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                state = self._read_state()
                try:
                    yield state
                    self._write_state(state)
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _read_state(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return {"version": 1, "periods": {}}
        if not isinstance(payload, dict) or not isinstance(payload.get("periods"), dict):
            return {"version": 1, "periods": {}}
        return payload

    def _write_state(self, state: dict[str, Any]) -> None:
        temporary = self.state_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temporary, self.state_path)
