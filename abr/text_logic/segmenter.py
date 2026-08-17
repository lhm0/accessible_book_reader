from __future__ import annotations

from abr.models import ReadingChunk


class SentenceSegmenter:
    TERMINATORS = {".", "!", "?"}
    TRAILING_CLOSERS = {'"', "'", "»", "«", "”", "“", ")"}

    def split(self, text: str) -> list[str]:
        normalized = " ".join(text.split())
        if not normalized:
            return []

        chunks: list[str] = []
        start = 0
        index = 0
        while index < len(normalized):
            char = normalized[index]
            if char in self.TERMINATORS:
                end = index + 1
                while end < len(normalized) and normalized[end] in self.TRAILING_CLOSERS:
                    end += 1
                chunks.append(normalized[start:end].strip())
                start = end
            index += 1

        tail = normalized[start:].strip()
        if tail:
            chunks.append(tail)
        return chunks

    def is_complete(self, text: str) -> bool:
        stripped = text.rstrip()
        while stripped and stripped[-1] in self.TRAILING_CLOSERS:
            stripped = stripped[:-1].rstrip()
        return bool(stripped) and stripped[-1] in self.TERMINATORS


class ReadingStreamBuilder:
    def __init__(self, segmenter: SentenceSegmenter | None = None) -> None:
        self.segmenter = segmenter or SentenceSegmenter()
        self._pending_fragment = ""
        self._pending_pages: list[str] = []

    def consume_page(self, page_id: str, paragraphs: list[str]) -> list[ReadingChunk]:
        chunks: list[ReadingChunk] = []
        for paragraph in paragraphs:
            merged = self._merge_with_pending(page_id, paragraph)
            sentences = self.segmenter.split(merged)
            for sentence in sentences:
                if not sentence:
                    continue
                if self.segmenter.is_complete(sentence):
                    page_ids = self._pending_pages or [page_id]
                    chunks.append(ReadingChunk(text=sentence, complete=True, source_pages=page_ids.copy()))
                    self._pending_fragment = ""
                    self._pending_pages = []
                else:
                    self._pending_fragment = sentence
                    if page_id not in self._pending_pages:
                        self._pending_pages.append(page_id)
        return chunks

    def flush(self) -> ReadingChunk | None:
        if not self._pending_fragment:
            return None
        fragment = ReadingChunk(text=self._pending_fragment, complete=False, source_pages=self._pending_pages.copy())
        self._pending_fragment = ""
        self._pending_pages = []
        return fragment

    def _merge_with_pending(self, page_id: str, paragraph: str) -> str:
        if not self._pending_fragment:
            return paragraph
        if page_id not in self._pending_pages:
            self._pending_pages.append(page_id)
        merged = f"{self._pending_fragment} {paragraph}".strip()
        self._pending_fragment = ""
        return merged
