from __future__ import annotations

from pathlib import Path

from abr.book.models import BookSession
from abr.book.store import BookStore


class BookSessionResolver:
    def __init__(self, library_root: Path, store: BookStore | None = None) -> None:
        self.store = store or BookStore(library_root)

    def resolve(self, tag_id: str, seen_at: str | None = None) -> BookSession:
        record = self.store.ensure_book(tag_id, seen_at=seen_at)
        return BookSession(
            tag_id=record.tag_id,
            root_dir=self.store.book_dir(record.tag_id),
            record=record,
        )
