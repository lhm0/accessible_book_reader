#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from abr.book import BookStore, PageIngestor


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Offline-Debugpfad: OCR-Report in PageRecords und BookStore ueberfuehren."
    )
    parser.add_argument(
        "--library-root",
        type=Path,
        default=Path("library"),
        help="Zielverzeichnis fuer Buchdaten, Standard: library",
    )
    parser.add_argument(
        "--book-tag-id",
        default="TESTBOOK",
        help="Temporare Buch-ID bis NFC integriert ist, Standard: TESTBOOK",
    )
    parser.add_argument(
        "--capture-root",
        type=Path,
        default=Path("captures"),
        help="Capture-Wurzel mit latest/metadata.json, Standard: captures",
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        help="Optional direkter Pfad auf einen stabilen report.json. Default: aus latest/metadata.json abgeleitet.",
    )
    parser.add_argument(
        "--capture-metadata-path",
        type=Path,
        help="Optional direkter Pfad auf metadata.json. Default: <capture-root>/latest/metadata.json",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    capture_metadata_path = (
        args.capture_metadata_path.expanduser().resolve()
        if args.capture_metadata_path is not None
        else (args.capture_root.expanduser().resolve() / "latest" / "metadata.json")
    )
    if args.report_path is not None:
        report_path = args.report_path.expanduser().resolve()
        session_dir = None
    else:
        if not capture_metadata_path.exists():
            print(f"Fehler: Metadata fehlt: {capture_metadata_path}", file=sys.stderr)
            return 1
        metadata = _read_text(capture_metadata_path)
        session_dir = Path(str(metadata["session_dir"])).expanduser().resolve()
        report_path = session_dir / "ocr_text" / "report.json"

    store = BookStore(args.library_root.expanduser().resolve())
    ingestor = PageIngestor(store)
    result = ingestor.ingest_report(
        args.book_tag_id,
        report_path,
        session_dir=session_dir,
        capture_metadata_path=capture_metadata_path if capture_metadata_path.exists() else None,
    )

    print(f"Buch:     {result.tag_id}")
    print(f"Scan:     {result.scan_record.scan_id}")
    print(f"Manifest: {result.scan_manifest_path}")
    for page in result.pages:
        page_label = page.page_number if page.page_number is not None else page.page_id
        print(f"{page.side}: page={page_label} chapter={page.chapter_number} tail={page.tail_fragment!r}")
    return 0


def _read_text(path: Path) -> dict[str, object]:
    import json

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"Ungueltiges JSON-Dokument: {path}")
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
