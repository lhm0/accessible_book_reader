from __future__ import annotations

from statistics import mean

from abr.models import LayoutBlock, OCRLine
from abr.text_logic import OCRTextPostProcessor


class BasicLayoutAnalyzer:
    def __init__(self, text_post_processor: OCRTextPostProcessor | None = None) -> None:
        self.text_post_processor = text_post_processor or OCRTextPostProcessor()

    def analyze(self, lines: list[OCRLine]) -> tuple[list[LayoutBlock], int | None, list[str]]:
        if not lines:
            return [], None, []

        ordered = sorted(lines, key=lambda line: (line.top, line.left))
        page_number_line = self._detect_page_number(ordered)
        text_lines = [line for line in ordered if line is not page_number_line]

        blocks: list[LayoutBlock] = []
        page_number: int | None = None
        if page_number_line:
            page_number = int(page_number_line.text.strip())
            blocks.append(
                LayoutBlock(
                    kind="page_number",
                    text=page_number_line.text,
                    bbox=page_number_line.bbox,
                    line_indices=[page_number_line.source_index],
                )
            )

        paragraph_groups = self._group_paragraphs(text_lines)
        paragraphs: list[str] = []
        for group in paragraph_groups:
            paragraph_text = self.text_post_processor.build_paragraph_text([line.text for line in group])
            if not paragraph_text:
                continue
            paragraphs.append(paragraph_text)
            kind = "chapter_heading" if self._looks_like_heading(group, paragraph_text) else "paragraph"
            blocks.append(
                LayoutBlock(
                    kind=kind,
                    text=paragraph_text,
                    bbox=self._merge_bbox(group),
                    line_indices=[line.source_index for line in group],
                )
            )

        return blocks, page_number, paragraphs

    def _group_paragraphs(self, lines: list[OCRLine]) -> list[list[OCRLine]]:
        if not lines:
            return []

        metadata_groups = self._group_paragraphs_by_metadata(lines)
        if metadata_groups is not None:
            return metadata_groups

        average_height = mean(line.height for line in lines) if lines else 1
        groups: list[list[OCRLine]] = [[lines[0]]]
        for line in lines[1:]:
            previous = groups[-1][-1]
            vertical_gap = line.top - previous.bottom
            if self._looks_like_heading([previous], previous.text):
                gap_threshold = max(1, previous.height) * 1.2
            else:
                gap_threshold = average_height * 1.4
            if vertical_gap > gap_threshold:
                groups.append([line])
            else:
                groups[-1].append(line)
        return groups

    def _group_paragraphs_by_metadata(self, lines: list[OCRLine]) -> list[list[OCRLine]] | None:
        if not lines or not all(line.metadata.get("ocr_engine") == "tesseract" for line in lines):
            return None

        groups: list[list[OCRLine]] = []
        current_group: list[OCRLine] = []
        current_key: tuple[int | None, int | None] | None = None
        for line in lines:
            paragraph_key = (line.metadata.get("block_num"), line.metadata.get("par_num"))
            if current_group and paragraph_key != current_key:
                groups.append(current_group)
                current_group = [line]
            else:
                current_group.append(line)
            current_key = paragraph_key
        if current_group:
            groups.append(current_group)
        return groups

    def _detect_page_number(self, lines: list[OCRLine]) -> OCRLine | None:
        candidates = [lines[0], lines[-1]] if len(lines) > 1 else [lines[0]]
        for line in candidates:
            normalized = line.text.strip()
            if normalized.isdigit() and len(normalized) <= 4:
                return line
        return None

    def _looks_like_heading(self, lines: list[OCRLine], text: str) -> bool:
        if len(lines) > 2 or len(text) > 80:
            return False
        if text.endswith((".", "!", "?", ",", ";", ":")):
            return False
        title_case_ratio = sum(1 for word in text.split() if word[:1].isupper()) / max(1, len(text.split()))
        return title_case_ratio >= 0.6

    def _merge_bbox(self, lines: list[OCRLine]) -> tuple[tuple[int, int], ...]:
        left = min(line.left for line in lines)
        top = min(line.top for line in lines)
        right = max(line.right for line in lines)
        bottom = max(line.bottom for line in lines)
        return ((left, top), (right, top), (right, bottom), (left, bottom))
