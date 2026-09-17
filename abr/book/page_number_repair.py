"""Resolve an earlier unnumbered spread and its persisted book references."""
from __future__ import annotations

from dataclasses import replace

from abr.book.models import PageRecord
from abr.book.store import BookStore, _read_json, _write_json


def repair_previous_spread(
    store: BookStore, tag_id: str, current: tuple[PageRecord, ...],
) -> tuple[PageRecord, ...]:
    if len(current) != 2 or {page.side for page in current} != {"left", "right"}:
        return ()
    left = next(page for page in current if page.side == "left")
    right = next(page for page in current if page.side == "right")
    if (left.page_number is None or left.page_number < 3
            or right.page_number != left.page_number + 1 or left.scan_id != right.scan_id):
        return ()
    old = tuple(store.load_page(tag_id, key) for key in ("page_1", "page_2"))
    if any(page is None or page.page_number is not None for page in old):
        return ()
    first, second = old
    assert first is not None and second is not None
    if (first.page_id != "page_1" or second.page_id != "page_2"
            or first.side != "left" or second.side != "right"
            or first.scan_id != second.scan_id or first.scan_id == left.scan_id
            or first.created_at > left.created_at or second.created_at > left.created_at):
        return ()
    numbers = (left.page_number - 2, left.page_number - 1)
    root = store.book_dir(tag_id)
    targets = [root / "pages" / f"{number:04d}.json" for number in numbers]
    existing = store.list_pages(tag_id)
    if any(path.exists() for path in targets) or any(
        page.page_number in numbers or page.page_id in {f"page_{n:04d}" for n in numbers}
        for page in existing
    ):
        return ()
    repaired = tuple(replace(
        page, page_id=f"page_{number:04d}", page_number=number,
        metadata={**page.metadata, "page_number_inferred": True,
                  "page_number_inference": "following_spread",
                  "page_number_inference_scan_id": left.scan_id},
    ) for page, number in zip((first, second), numbers))
    mapping = dict(zip(("page_1", "page_2"), repaired))
    by_id = {page.page_id: page for page in (*existing, *repaired)}

    def update(value, inherited_scan=None):
        if isinstance(value, list):
            return [update(item, inherited_scan) for item in value]
        if not isinstance(value, dict):
            return value
        scan = value.get("scan_id", inherited_scan)
        result = {key: update(item, scan) for key, item in value.items()}
        if scan is not None and scan != first.scan_id:
            return result
        # Only semantic reference fields, never prose or report-local page IDs.
        for key in ("page_id", "left_page_id", "right_page_id"):
            replacement = mapping.get(value.get(key))
            if replacement is not None:
                result[key] = replacement.page_id
                if key == "page_id":
                    result["page_number"] = replacement.page_number
        for key, number_key in (("page_ids", "page_numbers"),
                                ("pending_page_ids", "pending_page_numbers")):
            ids = value.get(key)
            if isinstance(ids, list) and any(item in mapping for item in ids):
                new_ids = [mapping[item].page_id if item in mapping else item for item in ids]
                result[key] = new_ids
                if all(item in by_id for item in new_ids):
                    result[number_key] = [by_id[item].page_number for item in new_ids
                                          if by_id[item].page_number is not None]
                    if key == "page_ids" and result[number_key]:
                        result["start_page"] = result[number_key][0]
                        result["end_page"] = result[number_key][-1]
        return result

    paths = [*root.glob("scans/*/manifest.json"), *root.glob("chapters/*/chapter.json"),
             *root.glob("state/*.json"), *root.glob("summaries/*.json")]
    originals = {path: _read_json(path) for path in paths}
    updates = {path: update(data) for path, data in originals.items()}
    chapters = {data["chapter_id"]: data for path, data in updates.items()
                if path.name == "chapter.json" and data != originals[path]}
    for path, data in updates.items():
        if path.parent.name == "summaries":
            metadata = data.get("metadata", {})
            chapter = chapters.get(metadata.get("chapter_id"))
            if chapter is not None:
                for key in ("start_page", "end_page"):
                    metadata[key] = chapter.get(key)
    changes = {path: data for path, data in updates.items() if data != originals[path]}
    sources = [root / "pages" / f"{page.page_id}.json" for page in (first, second)]
    # Keep originals for rollback; each individual replacement is atomic.
    backups = {path: path.read_bytes() for path in (*sources, *changes)}
    try:
        for path, page in zip(targets, repaired):
            _write_json(path, page.to_dict())
        for path, data in changes.items():
            _write_json(path, data)
        for path in sources:
            path.unlink()
    except Exception:
        for path, contents in backups.items():
            path.write_bytes(contents)
        for path in targets:
            path.unlink(missing_ok=True)
        raise
    return repaired
