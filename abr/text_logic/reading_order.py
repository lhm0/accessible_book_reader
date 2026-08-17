from __future__ import annotations

from abr.models import PageAnalysis


class ReadingOrderResolver:
    def resolve(self, pages: list[PageAnalysis]) -> list[PageAnalysis]:
        pages_with_numbers = [page for page in pages if page.page_number is not None]
        if len(pages_with_numbers) == len(pages) and len(pages) > 1:
            return sorted(pages, key=lambda page: page.page_number or 0)

        slot_priority = {"left": 0, "right": 1}
        return sorted(pages, key=lambda page: (slot_priority.get(page.slot, 99), page.page_id))
