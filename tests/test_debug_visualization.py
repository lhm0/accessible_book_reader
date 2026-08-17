from __future__ import annotations

import numpy as np

from abr.debug.visualization import DebugVisualizer
from abr.models import OCRLine


def test_draw_ocr_overlay_renders_boxes_and_text() -> None:
    visualizer = DebugVisualizer()
    image = np.zeros((80, 220, 3), dtype=np.uint8)
    lines = [
        OCRLine(
            text="Hällo »Welt« – Straße",
            confidence=0.93,
            bbox=((10, 30), (160, 30), (160, 50), (10, 50)),
            source_index=0,
        )
    ]

    overlay = visualizer.draw_ocr_overlay(image, lines)

    assert overlay.shape == image.shape
    assert np.count_nonzero(overlay) > 0


def test_overlay_label_allows_significantly_longer_text_before_ellipsis() -> None:
    line = OCRLine(
        text="Dies ist eine deutlich laengere Unicode-Zeile mit Umlauten äöü und Sonderzeichen »Test« ohne fruehe Kuerzung",
        confidence=0.9,
        bbox=((0, 0), (100, 0), (100, 20), (0, 20)),
        source_index=0,
    )

    label = DebugVisualizer._overlay_label(1, line)

    assert label.startswith("1: Dies ist eine deutlich laengere Unicode-Zeile")
    assert len(label) > 70


def test_fit_label_to_width_adds_ellipsis_when_pixel_width_is_too_small() -> None:
    from PIL import Image, ImageDraw

    visualizer = DebugVisualizer()
    image = Image.new("RGB", (200, 40), "white")
    draw = ImageDraw.Draw(image)
    font = visualizer._load_overlay_font(size=16)

    fitted = visualizer._fit_label_to_width(
        draw,
        "1: Dies ist ein deutlich zu langer Beispieltext fuer eine schmale Box",
        font,
        max_width=120,
    )

    assert fitted.endswith("…")
