from __future__ import annotations

import json
import time
from pathlib import Path
import pytest

from abr.book import BookStore, PageIngestRequest, PageIngestService, PageIngestor


def test_page_ingestor_persists_scan_and_page_records(tmp_path: Path) -> None:
    session_dir = tmp_path / "captures" / "scan_20260702_153500"
    stable_dir = session_dir / "ocr_text"
    stable_dir.mkdir(parents=True)
    report_path = stable_dir / "report.json"
    capture_metadata_path = session_dir / "metadata.json"

    report_path.write_text(
        json.dumps(
            {
                "ocr_dir": str(session_dir / "ocr"),
                "orientation_mode": "off",
                "pages": [
                    {
                        "page_id": "page_1",
                        "slot": "left",
                        "rotation_deg": 0,
                        "ocr_line_count": 3,
                        "ocr_lines": [
                            {"text": "Kapitel 7", "bbox": [[100, 40], [240, 40], [240, 70], [100, 70]]},
                            {"text": "Der geheime Garten", "bbox": [[100, 90], [420, 90], [420, 120], [100, 120]]},
                            {"text": "12", "bbox": [[300, 970], [340, 970], [340, 1000], [300, 1000]]},
                        ],
                    },
                    {
                        "page_id": "page_2",
                        "slot": "right",
                        "rotation_deg": 0,
                        "ocr_line_count": 3,
                        "ocr_lines": [
                            {"text": "Sie trat an das Fenster.", "bbox": [[90, 60], [520, 60], [520, 90], [90, 90]]},
                            {"text": "Dann hoerte sie Schritte", "bbox": [[90, 110], [520, 110], [520, 140], [90, 140]]},
                            {"text": "13", "bbox": [[300, 970], [340, 970], [340, 1000], [300, 1000]]},
                        ],
                    },
                ],
                "pipeline_timings": {"total_sec": 1.2},
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    capture_metadata_path.write_text(
        json.dumps(
            {
                "created_at": "2026-07-02T15:35:00Z",
                "session_dir": str(session_dir),
                "case_dir": str(session_dir / "case"),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    store = BookStore(tmp_path / "library")
    ingestor = PageIngestor(store)
    result = ingestor.ingest_report(
        "book42",
        report_path,
        capture_metadata_path=capture_metadata_path,
    )

    assert result.tag_id == "BOOK42"
    assert result.scan_record.scan_id == "scan_20260702_153500"
    assert result.scan_record.session_dir == session_dir.resolve()
    assert result.scan_record.left_page_id == "page_0012"
    assert result.scan_record.right_page_id == "page_0013"

    left_page = store.load_page("BOOK42", 12)
    assert left_page is not None
    assert left_page.chapter_number == 7
    assert left_page.chapter_heading == "Der geheime Garten"
    assert left_page.clean_text == "Kapitel 7\nDer geheime Garten"
    assert left_page.speak_text == "Kapitel 7\nDer geheime Garten"
    assert left_page.tail_fragment is None

    right_page = store.load_page("BOOK42", 13)
    assert right_page is not None
    assert right_page.tail_fragment == "Dann hoerte sie Schritte"
    assert right_page.speak_text == "Sie trat an das Fenster."
    assert right_page.clean_text == "Sie trat an das Fenster.\nDann hoerte sie Schritte"


def test_page_ingestor_binds_new_book_to_language_and_rejects_mixed_scan(tmp_path: Path) -> None:
    report_path = tmp_path / "report.json"
    report_path.write_text(
        json.dumps(
            {
                "ocr_language": "en",
                "pages": [
                    {
                        "page_id": "page_1",
                        "slot": "left",
                        "page_number": 1,
                        "ocr_lines": [{"text": "An English page."}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    store = BookStore(tmp_path / "library")

    PageIngestor(store, language_code="en").ingest_report("protected", report_path)

    assert store.load_book("protected").language == "en"  # type: ignore[union-attr]
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["ocr_language"] = "de"
    report_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RuntimeError, match="als Sprache en gespeichert"):
        PageIngestor(store, language_code="de").ingest_report("protected", report_path)
    assert len(store.list_pages("protected")) == 1


def test_page_ingestor_preserves_layout_block_paragraphs_in_speak_text(tmp_path: Path) -> None:
    report_path = tmp_path / "captures" / "scan_paragraphs" / "ocr_text" / "report.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page_id": "page_1",
                        "slot": "left",
                        "page_number": 10,
                        "ocr_lines": [
                            {"text": "Der erste Satz", "bbox": [[90, 100], [500, 100], [500, 130], [90, 130]]},
                            {"text": "geht hier weiter.", "bbox": [[90, 140], [500, 140], [500, 170], [90, 170]]},
                            {"text": "Der zweite Absatz.", "bbox": [[120, 210], [520, 210], [520, 240], [120, 240]]},
                        ],
                        "layout_blocks": [
                            {"kind": "paragraph", "line_indices": [0, 1]},
                            {"kind": "paragraph", "line_indices": [2]},
                        ],
                    }
                ]
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = PageIngestor(BookStore(tmp_path / "library")).ingest_report("book42", report_path)

    assert result.pages[0].speak_text == (
        "Der erste Satz\ngeht hier weiter.\n\nDer zweite Absatz."
    )


def test_page_ingestor_separates_layout_heading_from_following_prose(tmp_path: Path) -> None:
    report_path = tmp_path / "captures" / "scan_heading" / "ocr_text" / "report.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page_id": "page_1",
                        "slot": "left",
                        "page_number": 10,
                        "ocr_lines": [
                            {
                                "text": "Die geheime Kammer",
                                "bbox": [[120, 100], [480, 100], [480, 130], [120, 130]],
                            },
                            {
                                "text": "Am naechsten Morgen wachte Paul frueh auf.",
                                "bbox": [[90, 210], [700, 210], [700, 240], [90, 240]],
                            },
                        ],
                        "layout_blocks": [
                            {"kind": "chapter_heading", "line_indices": [0]},
                            {"kind": "paragraph", "line_indices": [1]},
                        ],
                    }
                ]
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = PageIngestor(BookStore(tmp_path / "library")).ingest_report("book42", report_path)
    page = result.pages[0]

    assert page.clean_text == (
        "Die geheime Kammer\nAm naechsten Morgen wachte Paul frueh auf."
    )
    assert page.speak_text == (
        "Die geheime Kammer\n\nAm naechsten Morgen wachte Paul frueh auf."
    )
    assert page.chapter_markers == []


def test_page_ingestor_collapses_spaced_letters_in_speak_text(tmp_path: Path) -> None:
    report_path = tmp_path / "captures" / "scan_letter_spacing" / "ocr_text" / "report.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page_id": "page_1",
                        "slot": "left",
                        "page_number": 10,
                        "ocr_lines": [
                            {
                                "text": "Die Ü B E R S C H R I F T. Danach folgt der Text.",
                                "bbox": [[90, 100], [600, 100], [600, 130], [90, 130]],
                            }
                        ],
                    }
                ]
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = PageIngestor(BookStore(tmp_path / "library")).ingest_report("book42", report_path)

    assert result.pages[0].speak_text == "Die ÜBERSCHRIFT. Danach folgt der Text."


def test_page_ingestor_normalizes_uppercase_heading_only_in_speak_text(tmp_path: Path) -> None:
    report_path = tmp_path / "captures" / "scan_uppercase_heading" / "ocr_text" / "report.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page_id": "page_1",
                        "slot": "left",
                        "page_number": 24,
                        "ocr_lines": [
                            {"text": "ERLEBNIS IN DER KNABENZEIT", "bbox": [[90, 80], [600, 80], [600, 110], [90, 110]]},
                            {"text": "Der Schlosser Mohr ging nach Hause.", "bbox": [[90, 140], [700, 140], [700, 170], [90, 170]]},
                        ],
                    }
                ]
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = PageIngestor(BookStore(tmp_path / "library")).ingest_report("book42", report_path)

    assert result.pages[0].clean_text == "ERLEBNIS IN DER KNABENZEIT\nDer Schlosser Mohr ging nach Hause."
    assert result.pages[0].speak_text == "Erlebnis In Der Knabenzeit\n\nDer Schlosser Mohr ging nach Hause."


def test_page_ingestor_applies_german_pronunciation_substitutions_only_in_speak_text(tmp_path: Path) -> None:
    report_path = tmp_path / "captures" / "scan_doctor" / "ocr_text" / "report.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page_id": "page_1",
                        "slot": "left",
                        "page_number": 25,
                        "ocr_lines": [
                            {
                                "text": "Dr. Müller ging zur Notre-Dame.",
                                "bbox": [[90, 140], [700, 140], [700, 170], [90, 170]],
                            }
                        ],
                    }
                ]
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = PageIngestor(BookStore(tmp_path / "library")).ingest_report("book42", report_path)

    assert result.pages[0].clean_text == "Dr. Müller ging zur Notre-Dame."
    assert result.pages[0].speak_text == "Doktor Müller ging zur Notre Damm."


def test_page_ingestor_does_not_prepend_bracketed_ocr_tail_artifact(tmp_path: Path) -> None:
    store = BookStore(tmp_path / "library")
    store.ensure_book("book42")
    from abr.book.models import PageRecord

    store.save_page(
        "book42",
        PageRecord(
            page_id="page_0023",
            scan_id="previous",
            created_at="2026-08-01T18:20:00+00:00",
            side="right",
            clean_text="(r9or)",
            speak_text="",
            page_number=23,
            tail_fragment="(r9or)",
        ),
    )
    report_path = tmp_path / "captures" / "scan_artifact" / "ocr_text" / "report.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page_id": "page_1",
                        "slot": "left",
                        "page_number": 24,
                        "ocr_lines": [
                            {"text": "ERLEBNIS IN DER KNABENZEIT", "bbox": [[90, 80], [600, 80], [600, 110], [90, 110]]},
                            {"text": "Der Schlosser Mohr ging nach Hause.", "bbox": [[90, 140], [700, 140], [700, 170], [90, 170]]},
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = PageIngestor(store).ingest_report("book42", report_path)

    assert result.pages[0].speak_text.startswith("Erlebnis In Der Knabenzeit\n\n")
    assert "r9or" not in result.pages[0].speak_text


def test_page_ingestor_infers_missing_right_page_number_and_removes_footer_artifact(tmp_path: Path) -> None:
    session_dir = tmp_path / "captures" / "scan_20260702_155750"
    stable_dir = session_dir / "ocr_text"
    stable_dir.mkdir(parents=True)
    report_path = stable_dir / "report.json"

    report_path.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page_id": "page_1",
                        "slot": "left",
                        "ocr_lines": [
                            {"text": "Und dann kam der Sonntag.", "bbox": [[80, 600], [500, 600], [500, 640], [80, 640]]},
                            {"text": "18", "bbox": [[300, 720], [340, 720], [340, 760], [300, 760]]},
                            {"text": "Am Sonntag will die Große ...", "bbox": [[80, 840], [820, 840], [820, 880], [80, 880]]},
                            {"text": "106", "bbox": [[300, 1760], [360, 1760], [360, 1790], [300, 1790]]},
                        ],
                    },
                    {
                        "page_id": "page_2",
                        "slot": "right",
                        "ocr_lines": [
                            {"text": "Die Mutter die Adresse notiert hat ...", "bbox": [[80, 120], [900, 120], [900, 160], [80, 160]]},
                            {"text": "LoI", "bbox": [[300, 1760], [340, 1760], [340, 1790], [300, 1790]]},
                        ],
                    },
                ]
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    store = BookStore(tmp_path / "library")
    ingestor = PageIngestor(store)
    result = ingestor.ingest_report("book42", report_path)

    left_page = result.pages[0]
    right_page = result.pages[1]

    assert left_page.page_number == 106
    assert left_page.chapter_number == 18
    assert left_page.chapter_heading is None
    assert len(left_page.chapter_markers) == 1
    assert left_page.chapter_markers[0].chapter_number == 18
    assert left_page.speak_text == "Und dann kam der Sonntag.\n\nKapitel achtzehn.\n\nAm Sonntag will die Große ..."
    assert right_page.page_number == 107
    assert right_page.page_id == "page_0107"
    assert right_page.metadata["page_number_inferred"] is True
    assert "LoI" not in right_page.clean_text


def test_page_ingestor_keeps_multiple_chapter_markers_on_one_page_and_heading_only_page(tmp_path: Path) -> None:
    session_dir = tmp_path / "captures" / "scan_20260702_164406"
    stable_dir = session_dir / "ocr_text"
    stable_dir.mkdir(parents=True)
    report_path = stable_dir / "report.json"

    report_path.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page_id": "page_1",
                        "slot": "left",
                        "ocr_lines": [
                            {"text": "31", "bbox": [[300, 40], [340, 40], [340, 80], [300, 80]]},
                            {"text": "Sterben tut der Vater erst ein knappes Jahr später, am 2. De-", "bbox": [[90, 160], [920, 160], [920, 200], [90, 200]]},
                            {"text": "32", "bbox": [[300, 840], [340, 840], [340, 880], [300, 880]]},
                            {"text": "Im Jahr 1944 wird in einem Birkenwäldchen ein Heft mit", "bbox": [[90, 960], [920, 960], [920, 1000], [90, 1000]]},
                            {"text": "132", "bbox": [[300, 1760], [360, 1760], [360, 1790], [300, 1790]]},
                        ],
                    },
                    {
                        "page_id": "page_2",
                        "slot": "right",
                        "ocr_lines": [
                            {"text": "INTERMEZZO", "bbox": [[260, 420], [760, 420], [760, 500], [260, 500]]},
                        ],
                    },
                ]
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    store = BookStore(tmp_path / "library")
    ingestor = PageIngestor(store)
    result = ingestor.ingest_report("book99", report_path)

    left_page = result.pages[0]
    right_page = result.pages[1]

    assert left_page.page_number == 132
    assert left_page.chapter_number == 31
    assert left_page.chapter_heading is None
    assert [marker.chapter_number for marker in left_page.chapter_markers] == [31, 32]
    assert [marker.line_index for marker in left_page.chapter_markers] == [0, 2]
    assert left_page.speak_text == (
        "Kapitel einunddreissig.\n\nSterben tut der Vater erst ein knappes Jahr später, am 2. De-\n\n"
        "Kapitel zweiunddreissig.\n\nIm Jahr 1944 wird in einem Birkenwäldchen ein Heft mit"
    )

    assert right_page.page_number == 133
    assert right_page.chapter_number is None
    assert right_page.chapter_heading == "INTERMEZZO"
    assert len(right_page.chapter_markers) == 1
    assert right_page.chapter_markers[0].detection_kind == "heading_only_page"
    assert right_page.tail_fragment is None
    assert right_page.speak_text == "INTERMEZZO"


def test_page_ingestor_spells_inserted_chapter_number_as_cardinal(tmp_path: Path) -> None:
    report_path = tmp_path / "captures" / "scan_2" / "ocr_text" / "report.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page_id": "page_1",
                        "slot": "left",
                        "ocr_lines": [
                            {"text": "2", "bbox": [[300, 40], [340, 40], [340, 80], [300, 80]]},
                            {"text": "Der Anfang des Kapitels.", "bbox": [[90, 160], [920, 160], [920, 200], [90, 200]]},
                            {"text": "44", "bbox": [[300, 1760], [360, 1760], [360, 1790], [300, 1790]]},
                        ],
                    }
                ]
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    store = BookStore(tmp_path / "library")
    ingestor = PageIngestor(store)
    result = ingestor.ingest_report("book45", report_path)

    assert result.pages[0].speak_text == "Kapitel zwei.\n\nDer Anfang des Kapitels."


def test_page_ingestor_merges_hyphenated_line_breaks_only_in_speak_text(tmp_path: Path) -> None:
    session_dir = tmp_path / "captures" / "scan_20260703_113000"
    stable_dir = session_dir / "ocr_text"
    stable_dir.mkdir(parents=True)
    report_path = stable_dir / "report.json"

    report_path.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page_id": "page_1",
                        "slot": "left",
                        "ocr_lines": [
                            {"text": "Das Heft wird in den Dreck fallen, und die Frau wird nicht", "bbox": [[90, 120], [920, 120], [920, 160], [90, 160]]},
                            {"text": "zurückkommen können, um es aufzuheben, das Heft wird ein", "bbox": [[90, 170], [920, 170], [920, 210], [90, 210]]},
                            {"text": "Weilchen dort liegen, bis ein Gewehr-", "bbox": [[90, 220], [920, 220], [920, 260], [90, 260]]},
                            {"text": "kolben vorwärts stößt.", "bbox": [[90, 270], [920, 270], [920, 310], [90, 310]]},
                            {"text": "132", "bbox": [[300, 1760], [360, 1760], [360, 1790], [300, 1790]]},
                        ],
                    }
                ]
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    store = BookStore(tmp_path / "library")
    ingestor = PageIngestor(store)
    result = ingestor.ingest_report("book77", report_path)

    left_page = result.pages[0]

    assert left_page.clean_text == (
        "Das Heft wird in den Dreck fallen, und die Frau wird nicht\n"
        "zurückkommen können, um es aufzuheben, das Heft wird ein\n"
        "Weilchen dort liegen, bis ein Gewehr-\n"
        "kolben vorwärts stößt."
    )
    assert left_page.speak_text == (
        "Das Heft wird in den Dreck fallen, und die Frau wird nicht\n"
        "zurückkommen können, um es aufzuheben, das Heft wird ein\n"
        "Weilchen dort liegen, bis ein Gewehrkolben vorwärts stößt."
    )


def test_page_ingestor_moves_right_tail_fragment_to_next_left_page_speak_text(tmp_path: Path) -> None:
    store = BookStore(tmp_path / "library")
    ingestor = PageIngestor(store)

    first_report = tmp_path / "captures" / "scan_1" / "ocr_text" / "report.json"
    first_report.parent.mkdir(parents=True)
    first_report.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page_id": "page_1",
                        "slot": "left",
                        "ocr_lines": [
                            {"text": "Alles war still.", "bbox": [[90, 120], [920, 120], [920, 160], [90, 160]]},
                            {"text": "12", "bbox": [[300, 1760], [360, 1760], [360, 1790], [300, 1790]]},
                        ],
                    },
                    {
                        "page_id": "page_2",
                        "slot": "right",
                        "ocr_lines": [
                            {"text": "Sie trat an das Fenster.", "bbox": [[90, 120], [920, 120], [920, 160], [90, 160]]},
                            {"text": "Dann hoerte sie Schritte", "bbox": [[90, 170], [920, 170], [920, 210], [90, 210]]},
                            {"text": "13", "bbox": [[300, 1760], [360, 1760], [360, 1790], [300, 1790]]},
                        ],
                    },
                ]
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    first_result = ingestor.ingest_report("book42", first_report)
    assert first_result.pages[1].tail_fragment == "Dann hoerte sie Schritte"
    assert first_result.pages[1].speak_text == "Sie trat an das Fenster."

    second_report = tmp_path / "captures" / "scan_2" / "ocr_text" / "report.json"
    second_report.parent.mkdir(parents=True)
    second_report.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page_id": "page_3",
                        "slot": "left",
                        "ocr_lines": [
                            {"text": "im Flur und oeffnete vorsichtig die Tuer.", "bbox": [[90, 120], [920, 120], [920, 160], [90, 160]]},
                            {"text": "14", "bbox": [[300, 1760], [360, 1760], [360, 1790], [300, 1790]]},
                        ],
                    },
                    {
                        "page_id": "page_4",
                        "slot": "right",
                        "ocr_lines": [
                            {"text": "Niemand war zu sehen.", "bbox": [[90, 120], [920, 120], [920, 160], [90, 160]]},
                            {"text": "15", "bbox": [[300, 1760], [360, 1760], [360, 1790], [300, 1790]]},
                        ],
                    },
                ]
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    second_result = ingestor.ingest_report("book42", second_report)

    assert second_result.pages[0].page_number == 14
    assert second_result.pages[0].speak_text == "Dann hoerte sie Schritte im Flur und oeffnete vorsichtig die Tuer."
    assert second_result.pages[0].tail_fragment is None


def test_page_ingestor_merges_hyphenated_tail_fragment_with_next_left_page(tmp_path: Path) -> None:
    store = BookStore(tmp_path / "library")
    ingestor = PageIngestor(store)

    first_report = tmp_path / "captures" / "scan_h1" / "ocr_text" / "report.json"
    first_report.parent.mkdir(parents=True)
    first_report.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page_id": "page_1",
                        "slot": "left",
                        "ocr_lines": [
                            {"text": "Es war spaet.", "bbox": [[90, 120], [920, 120], [920, 160], [90, 160]]},
                            {"text": "20", "bbox": [[300, 1760], [360, 1760], [360, 1790], [300, 1790]]},
                        ],
                    },
                    {
                        "page_id": "page_2",
                        "slot": "right",
                        "ocr_lines": [
                            {"text": "Sie hob das Gewehr-", "bbox": [[90, 120], [920, 120], [920, 160], [90, 160]]},
                            {"text": "21", "bbox": [[300, 1760], [360, 1760], [360, 1790], [300, 1790]]},
                        ],
                    },
                ]
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    first_result = ingestor.ingest_report("book43", first_report)
    assert first_result.pages[1].tail_fragment == "Sie hob das Gewehr-"
    assert first_result.pages[1].speak_text == ""

    second_report = tmp_path / "captures" / "scan_h2" / "ocr_text" / "report.json"
    second_report.parent.mkdir(parents=True)
    second_report.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page_id": "page_3",
                        "slot": "left",
                        "ocr_lines": [
                            {"text": "kolben und lauschte in die Dunkelheit.", "bbox": [[90, 120], [920, 120], [920, 160], [90, 160]]},
                            {"text": "22", "bbox": [[300, 1760], [360, 1760], [360, 1790], [300, 1790]]},
                        ],
                    }
                ]
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    second_result = ingestor.ingest_report("book43", second_report)

    assert second_result.pages[0].speak_text == "Sie hob das Gewehrkolben und lauschte in die Dunkelheit."


def test_page_ingestor_normalizes_right_tail_fragment_against_speak_text(tmp_path: Path) -> None:
    report_path = tmp_path / "captures" / "scan_right_tail_norm" / "ocr_text" / "report.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page_id": "page_1",
                        "slot": "left",
                        "ocr_lines": [
                            {"text": "Es war ein langer Tag.", "bbox": [[90, 120], [920, 120], [920, 160], [90, 160]]},
                            {"text": "264", "bbox": [[300, 1760], [360, 1760], [360, 1790], [300, 1790]]},
                        ],
                    },
                    {
                        "page_id": "page_2",
                        "slot": "right",
                        "ocr_lines": [
                            {"text": "Am Abend sprach er über den 1.", "bbox": [[90, 120], [920, 120], [920, 160], [90, 160]]},
                            {"text": "Mai rote Nelken fürs Knopfloch, gefälschte Wah-", "bbox": [[90, 170], [920, 170], [920, 210], [90, 210]]},
                            {"text": "en, Greise mit Baskenmütze aus dem Spanischen Bürgerkrieg", "bbox": [[90, 220], [920, 220], [920, 260], [90, 260]]},
                            {"text": "265", "bbox": [[300, 1760], [360, 1760], [360, 1790], [300, 1790]]},
                        ],
                    },
                ]
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    store = BookStore(tmp_path / "library")
    ingestor = PageIngestor(store)
    result = ingestor.ingest_report("book43b", report_path)

    assert result.pages[1].tail_fragment == (
        "Mai rote Nelken fürs Knopfloch, gefälschte Wahen, Greise mit Baskenmütze aus dem Spanischen Bürgerkrieg"
    )
    assert result.pages[1].speak_text == "Am Abend sprach er über den 1."


def test_page_ingestor_carries_left_page_hyphenated_word_to_right_page(tmp_path: Path) -> None:
    report_path = tmp_path / "captures" / "scan_lr" / "ocr_text" / "report.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page_id": "page_1",
                        "slot": "left",
                        "ocr_lines": [
                            {"text": "Er griff nach dem Gewehr-", "bbox": [[90, 120], [920, 120], [920, 160], [90, 160]]},
                            {"text": "30", "bbox": [[300, 1760], [360, 1760], [360, 1790], [300, 1790]]},
                        ],
                    },
                    {
                        "page_id": "page_2",
                        "slot": "right",
                        "ocr_lines": [
                            {"text": "kolben und hob ihn an.", "bbox": [[90, 120], [920, 120], [920, 160], [90, 160]]},
                            {"text": "31", "bbox": [[300, 1760], [360, 1760], [360, 1790], [300, 1790]]},
                        ],
                    },
                ]
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    store = BookStore(tmp_path / "library")
    ingestor = PageIngestor(store)
    result = ingestor.ingest_report("book44", report_path)

    assert result.pages[0].tail_fragment == "Er griff nach dem Gewehr-"
    assert result.pages[0].speak_text == ""
    assert result.pages[1].speak_text == "Er griff nach dem Gewehrkolben und hob ihn an."


def test_page_ingestor_moves_left_tail_fragment_to_right_page_speak_text(tmp_path: Path) -> None:
    report_path = tmp_path / "captures" / "scan_lr_tail" / "ocr_text" / "report.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page_id": "page_1",
                        "slot": "left",
                        "ocr_lines": [
                            {"text": "Es wurde still.", "bbox": [[90, 120], [920, 120], [920, 160], [90, 160]]},
                            {"text": "Sie ging langsam", "bbox": [[90, 170], [920, 170], [920, 210], [90, 210]]},
                            {"text": "40", "bbox": [[300, 1760], [360, 1760], [360, 1790], [300, 1790]]},
                        ],
                    },
                    {
                        "page_id": "page_2",
                        "slot": "right",
                        "ocr_lines": [
                            {"text": "durch den Garten.", "bbox": [[90, 120], [920, 120], [920, 160], [90, 160]]},
                            {"text": "41", "bbox": [[300, 1760], [360, 1760], [360, 1790], [300, 1790]]},
                        ],
                    },
                ]
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    store = BookStore(tmp_path / "library")
    ingestor = PageIngestor(store)
    result = ingestor.ingest_report("book46", report_path)

    assert result.pages[0].tail_fragment == "Sie ging langsam"
    assert result.pages[0].speak_text == "Es wurde still."
    assert result.pages[1].speak_text == "Sie ging langsam durch den Garten."


def test_page_ingestor_strips_left_tail_fragment_from_speak_text_after_chapter_marker_rewrite(tmp_path: Path) -> None:
    report_path = tmp_path / "captures" / "scan_left_chapter_tail" / "ocr_text" / "report.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page_id": "page_1",
                        "slot": "left",
                        "ocr_lines": [
                            {"text": "2", "bbox": [[300, 40], [340, 40], [340, 80], [300, 80]]},
                            {"text": "Sie ging langsam", "bbox": [[90, 170], [920, 170], [920, 210], [90, 210]]},
                            {"text": "40", "bbox": [[300, 1760], [360, 1760], [360, 1790], [300, 1790]]},
                        ],
                    }
                ]
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    store = BookStore(tmp_path / "library")
    ingestor = PageIngestor(store)
    result = ingestor.ingest_report("book47", report_path)

    assert result.pages[0].tail_fragment == "Sie ging langsam"
    assert result.pages[0].speak_text == "Kapitel zwei."


def test_page_ingestor_renders_isolated_chapter_number_in_us_english(tmp_path: Path) -> None:
    report_path = tmp_path / "captures" / "scan_english_chapter" / "ocr_text" / "report.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page_id": "page_1",
                        "slot": "left",
                        "ocr_lines": [
                            {"text": "42", "bbox": [[300, 40], [340, 40], [340, 80], [300, 80]]},
                            {"text": "A new beginning.", "bbox": [[90, 170], [920, 170], [920, 210], [90, 210]]},
                            {"text": "80", "bbox": [[300, 1760], [360, 1760], [360, 1790], [300, 1790]]},
                        ],
                    }
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    result = PageIngestor(BookStore(tmp_path / "library"), language_code="en").ingest_report(
        "english-book", report_path
    )

    assert result.pages[0].speak_text == "Chapter forty-two.\n\nA new beginning."
    assert result.pages[0].metadata["language"] == "en"


def test_page_ingestor_incremental_flow_keeps_left_to_right_tail_carryover(tmp_path: Path) -> None:
    store = BookStore(tmp_path / "library")
    ingestor = PageIngestor(store)

    left_only_report = tmp_path / "captures" / "scan_inc_1" / "ocr_text" / "left_report.json"
    left_only_report.parent.mkdir(parents=True)
    left_only_report.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page_id": "page_1",
                        "slot": "left",
                        "ocr_lines": [
                            {"text": "Es wurde still.", "bbox": [[90, 120], [920, 120], [920, 160], [90, 160]]},
                            {"text": "Sie ging langsam", "bbox": [[90, 170], [920, 170], [920, 210], [90, 210]]},
                            {"text": "40", "bbox": [[300, 1760], [360, 1760], [360, 1790], [300, 1790]]},
                        ],
                    }
                ]
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    combined_report = tmp_path / "captures" / "scan_inc_1" / "ocr_text" / "report.json"
    combined_report.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page_id": "page_1",
                        "slot": "left",
                        "ocr_lines": [
                            {"text": "Es wurde still.", "bbox": [[90, 120], [920, 120], [920, 160], [90, 160]]},
                            {"text": "Sie ging langsam", "bbox": [[90, 170], [920, 170], [920, 210], [90, 210]]},
                            {"text": "40", "bbox": [[300, 1760], [360, 1760], [360, 1790], [300, 1790]]},
                        ],
                    },
                    {
                        "page_id": "page_2",
                        "slot": "right",
                        "ocr_lines": [
                            {"text": "durch den Garten.", "bbox": [[90, 120], [920, 120], [920, 160], [90, 160]]},
                            {"text": "41", "bbox": [[300, 1760], [360, 1760], [360, 1790], [300, 1790]]},
                        ],
                    },
                ]
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    early_result = ingestor.ingest_report("book48", left_only_report)
    assert early_result.pages[0].speak_text == "Es wurde still."

    final_result = ingestor.ingest_report("book48", combined_report)
    assert final_result.pages[0].speak_text == "Es wurde still."
    assert final_result.pages[1].speak_text == "Sie ging langsam durch den Garten."


def test_page_ingestor_replaces_unnumbered_incremental_placeholder_with_numbered_page(
    tmp_path: Path,
) -> None:
    store = BookStore(tmp_path / "library")
    ingestor = PageIngestor(store, language_code="en")
    report_dir = tmp_path / "captures" / "scan_incremental_number" / "ocr_text"
    report_dir.mkdir(parents=True)
    left_page = {
        "page_id": "page_1",
        "slot": "left",
        "ocr_lines": [
            {
                "text": "The story starts here.",
                "bbox": [[90, 120], [920, 120], [920, 160], [90, 160]],
            }
        ],
    }
    left_report = report_dir / "left_report.json"
    left_report.write_text(json.dumps({"pages": [left_page]}), encoding="utf-8")
    combined_report = report_dir / "report.json"
    combined_report.write_text(
        json.dumps(
            {
                "pages": [
                    left_page,
                    {
                        "page_id": "page_2",
                        "slot": "right",
                        "ocr_lines": [
                            {
                                "text": "The story continues.",
                                "bbox": [[90, 120], [920, 120], [920, 160], [90, 160]],
                            },
                            {
                                "text": "7",
                                "bbox": [[300, 1760], [360, 1760], [360, 1790], [300, 1790]],
                            },
                        ],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    early_result = ingestor.ingest_report("book-numbered", left_report)

    assert early_result.pages[0].page_number is None
    assert (store.book_dir("book-numbered") / "pages" / "page_1.json").exists()

    final_result = ingestor.ingest_report("book-numbered", combined_report)

    assert [page.page_number for page in final_result.pages] == [6, 7]
    assert not (store.book_dir("book-numbered") / "pages" / "page_1.json").exists()
    assert (store.book_dir("book-numbered") / "pages" / "0006.json").exists()
    assert (store.book_dir("book-numbered") / "pages" / "0007.json").exists()
    assert [page.page_number for page in store.list_pages("book-numbered")] == [6, 7]


def test_page_ingestor_incremental_flow_keeps_right_to_next_left_tail_carryover(tmp_path: Path) -> None:
    store = BookStore(tmp_path / "library")
    ingestor = PageIngestor(store)

    first_left_only_report = tmp_path / "captures" / "scan_inc_a" / "ocr_text" / "left_report.json"
    first_left_only_report.parent.mkdir(parents=True)
    first_left_only_report.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page_id": "page_1",
                        "slot": "left",
                        "ocr_lines": [
                            {"text": "Alles war still.", "bbox": [[90, 120], [920, 120], [920, 160], [90, 160]]},
                            {"text": "12", "bbox": [[300, 1760], [360, 1760], [360, 1790], [300, 1790]]},
                        ],
                    }
                ]
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    first_combined_report = tmp_path / "captures" / "scan_inc_a" / "ocr_text" / "report.json"
    first_combined_report.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page_id": "page_1",
                        "slot": "left",
                        "ocr_lines": [
                            {"text": "Alles war still.", "bbox": [[90, 120], [920, 120], [920, 160], [90, 160]]},
                            {"text": "12", "bbox": [[300, 1760], [360, 1760], [360, 1790], [300, 1790]]},
                        ],
                    },
                    {
                        "page_id": "page_2",
                        "slot": "right",
                        "ocr_lines": [
                            {"text": "Sie trat an das Fenster.", "bbox": [[90, 120], [920, 120], [920, 160], [90, 160]]},
                            {"text": "Dann hoerte sie Schritte", "bbox": [[90, 170], [920, 170], [920, 210], [90, 210]]},
                            {"text": "13", "bbox": [[300, 1760], [360, 1760], [360, 1790], [300, 1790]]},
                        ],
                    },
                ]
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    second_left_only_report = tmp_path / "captures" / "scan_inc_b" / "ocr_text" / "left_report.json"
    second_left_only_report.parent.mkdir(parents=True)
    second_left_only_report.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page_id": "page_3",
                        "slot": "left",
                        "ocr_lines": [
                            {"text": "im Flur und oeffnete vorsichtig die Tuer.", "bbox": [[90, 120], [920, 120], [920, 160], [90, 160]]},
                            {"text": "14", "bbox": [[300, 1760], [360, 1760], [360, 1790], [300, 1790]]},
                        ],
                    }
                ]
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    ingestor.ingest_report("book49", first_left_only_report)
    ingestor.ingest_report("book49", first_combined_report)
    second_result = ingestor.ingest_report("book49", second_left_only_report)

    assert second_result.pages[0].speak_text == "Dann hoerte sie Schritte im Flur und oeffnete vorsichtig die Tuer."


def test_page_ingestor_uses_pending_right_tail_for_single_left_page_without_page_number(tmp_path: Path) -> None:
    store = BookStore(tmp_path / "library")
    ingestor = PageIngestor(store)

    first_report = tmp_path / "captures" / "scan_hist_1" / "ocr_text" / "report.json"
    first_report.parent.mkdir(parents=True)
    first_report.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page_id": "page_1",
                        "slot": "left",
                        "ocr_lines": [
                            {"text": "Sie wartete am Fenster.", "bbox": [[90, 120], [920, 120], [920, 160], [90, 160]]},
                            {"text": "62", "bbox": [[300, 1760], [360, 1760], [360, 1790], [300, 1790]]},
                        ],
                    },
                    {
                        "page_id": "page_2",
                        "slot": "right",
                        "ocr_lines": [
                            {"text": "Krieg hin oder her, hatten sich innerhalb von Europa doch von jeher die Menschen, über das Festland streifend, vermischt", "bbox": [[90, 120], [920, 120], [920, 160], [90, 160]]},
                            {"text": "63", "bbox": [[300, 1760], [360, 1760], [360, 1790], [300, 1790]]},
                        ],
                    },
                ]
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    first_result = ingestor.ingest_report("book50", first_report)
    assert first_result.pages[1].page_number == 63
    assert first_result.pages[1].tail_fragment == (
        "Krieg hin oder her, hatten sich innerhalb von Europa doch von jeher die Menschen, "
        "über das Festland streifend, vermischt"
    )
    assert store.load_runtime_state("book50", "pending_right_tail_fragment.json") == {
        "page_id": "page_0063",
        "page_number": 63,
        "tail_fragment": (
            "Krieg hin oder her, hatten sich innerhalb von Europa doch von jeher die Menschen, "
            "über das Festland streifend, vermischt"
        ),
    }

    second_left_only_report = tmp_path / "captures" / "scan_hist_2" / "ocr_text" / "left_report.json"
    second_left_only_report.parent.mkdir(parents=True)
    second_left_only_report.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page_id": "page_3",
                        "slot": "left",
                        "ocr_lines": [
                            {"text": "die Völker, die Länder, die Sitten und Gebräuche.", "bbox": [[90, 120], [920, 120], [920, 160], [90, 160]]},
                        ],
                    }
                ]
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    second_result = ingestor.ingest_report("book50", second_left_only_report)

    assert second_result.pages[0].page_number is None
    assert second_result.pages[0].metadata["page_number_inferred"] is False
    assert second_result.pages[0].speak_text == (
        "Krieg hin oder her, hatten sich innerhalb von Europa doch von jeher die Menschen, "
        "über das Festland streifend, vermischt die Völker, die Länder, die Sitten und Gebräuche."
    )


def test_page_ingestor_clears_pending_right_tail_when_right_page_has_no_fragment(tmp_path: Path) -> None:
    store = BookStore(tmp_path / "library")
    ingestor = PageIngestor(store)

    first_report = tmp_path / "captures" / "scan_clear_1" / "ocr_text" / "report.json"
    first_report.parent.mkdir(parents=True)
    first_report.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page_id": "page_1",
                        "slot": "left",
                        "ocr_lines": [
                            {"text": "Die Nacht war still.", "bbox": [[90, 120], [920, 120], [920, 160], [90, 160]]},
                            {"text": "10", "bbox": [[300, 1760], [360, 1760], [360, 1790], [300, 1790]]},
                        ],
                    },
                    {
                        "page_id": "page_2",
                        "slot": "right",
                        "ocr_lines": [
                            {"text": "Dann hörte sie Schritte", "bbox": [[90, 120], [920, 120], [920, 160], [90, 160]]},
                            {"text": "11", "bbox": [[300, 1760], [360, 1760], [360, 1790], [300, 1790]]},
                        ],
                    },
                ]
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    ingestor.ingest_report("book51", first_report)
    assert store.load_runtime_state("book51", "pending_right_tail_fragment.json") == {
        "page_id": "page_0011",
        "page_number": 11,
        "tail_fragment": "Dann hörte sie Schritte",
    }

    second_report = tmp_path / "captures" / "scan_clear_2" / "ocr_text" / "report.json"
    second_report.parent.mkdir(parents=True)
    second_report.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page_id": "page_3",
                        "slot": "left",
                        "ocr_lines": [
                            {"text": "im Hof.", "bbox": [[90, 120], [920, 120], [920, 160], [90, 160]]},
                            {"text": "12", "bbox": [[300, 1760], [360, 1760], [360, 1790], [300, 1790]]},
                        ],
                    },
                    {
                        "page_id": "page_4",
                        "slot": "right",
                        "ocr_lines": [
                            {"text": "Niemand war zu sehen.", "bbox": [[90, 120], [920, 120], [920, 160], [90, 160]]},
                            {"text": "13", "bbox": [[300, 1760], [360, 1760], [360, 1790], [300, 1790]]},
                        ],
                    },
                ]
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    ingestor.ingest_report("book51", second_report)
    assert store.load_runtime_state("book51", "pending_right_tail_fragment.json") == {
        "page_id": "page_0013",
        "page_number": 13,
        "tail_fragment": None,
    }


def test_page_ingest_service_processes_requests_in_background(tmp_path: Path) -> None:
    report_path = tmp_path / "report.json"
    report_path.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page_id": "page_1",
                        "slot": "left",
                        "ocr_lines": [{"text": "8", "bbox": [[0, 900], [20, 900], [20, 920], [0, 920]]}],
                    }
                ]
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    statuses: list[str] = []
    service = PageIngestService(
        PageIngestor(BookStore(tmp_path / "library")),
        status_callback=statuses.append,
    )
    try:
        completion_event = service.submit(PageIngestRequest(tag_id="demo1", report_path=report_path))
        assert completion_event.wait(timeout=1.0)
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            if any("abgeschlossen" in status for status in statuses):
                break
            time.sleep(0.01)
    finally:
        service.shutdown()

    assert any("eingeplant" in status for status in statuses)
    assert any("abgeschlossen" in status for status in statuses)
