from abr.layout import BasicLayoutAnalyzer
from abr.models import OCRLine


def _line(text: str, top: int, bottom: int, left: int = 10, right: int = 200, source_index: int = 0) -> OCRLine:
    return OCRLine(
        text=text,
        confidence=0.9,
        bbox=((left, top), (right, top), (right, bottom), (left, bottom)),
        source_index=source_index,
    )


def test_layout_detects_page_number_and_heading() -> None:
    analyzer = BasicLayoutAnalyzer()
    lines = [
        _line("12", top=10, bottom=30, left=90, right=120, source_index=0),
        _line("Kapitel Eins", top=80, bottom=110, source_index=1),
        _line("Es war ein stiller Abend.", top=180, bottom=205, source_index=2),
        _line("Niemand sprach ein Wort.", top=210, bottom=235, source_index=3),
    ]

    blocks, page_number, paragraphs = analyzer.analyze(lines)

    assert page_number == 12
    assert blocks[0].kind == "page_number"
    assert any(block.kind == "chapter_heading" for block in blocks)
    assert paragraphs[0] == "Kapitel Eins"


def test_layout_detects_unnumbered_heading_from_large_vertical_gap() -> None:
    analyzer = BasicLayoutAnalyzer()
    lines = [
        _line("Die geheime Kammer", top=80, bottom=110, source_index=0),
        _line(
            "Am naechsten Morgen wachte Paul frueh auf.",
            top=190,
            bottom=220,
            source_index=1,
        ),
        _line("Er stand sofort auf.", top=230, bottom=260, source_index=2),
    ]

    blocks, _, paragraphs = analyzer.analyze(lines)

    assert [block.kind for block in blocks] == ["chapter_heading", "paragraph"]
    assert paragraphs == [
        "Die geheime Kammer",
        "Am naechsten Morgen wachte Paul frueh auf. Er stand sofort auf.",
    ]


def test_layout_uses_tesseract_paragraph_metadata() -> None:
    analyzer = BasicLayoutAnalyzer()
    lines = [
        OCRLine(
            text="Er oeffnete langsam die Tuer.",
            confidence=0.9,
            bbox=((10, 100), (240, 100), (240, 120), (10, 120)),
            source_index=0,
            metadata={"ocr_engine": "tesseract", "block_num": 1, "par_num": 1},
        ),
        OCRLine(
            text="Dann trat er ein.",
            confidence=0.9,
            bbox=((10, 130), (180, 130), (180, 150), (10, 150)),
            source_index=1,
            metadata={"ocr_engine": "tesseract", "block_num": 1, "par_num": 1},
        ),
        OCRLine(
            text="Kapitel Zwei",
            confidence=0.9,
            bbox=((10, 220), (160, 220), (160, 240), (10, 240)),
            source_index=2,
            metadata={"ocr_engine": "tesseract", "block_num": 1, "par_num": 2},
        ),
    ]

    _, _, paragraphs = analyzer.analyze(lines)

    assert paragraphs == ["Er oeffnete langsam die Tuer. Dann trat er ein.", "Kapitel Zwei"]


def test_layout_applies_ocr_cleanup_rules() -> None:
    analyzer = BasicLayoutAnalyzer()
    lines = [
        _line("Sie sprachen ueber Krieg-", top=100, bottom=120, source_index=0),
        _line("reden und % Frieden.", top=130, bottom=150, source_index=1),
        _line("a", top=160, bottom=180, source_index=2),
        _line("10 % bleiben.", top=190, bottom=210, source_index=3),
    ]

    _, _, paragraphs = analyzer.analyze(lines)

    assert paragraphs == ["Sie sprachen ueber Kriegreden und Frieden. 10 % bleiben."]
