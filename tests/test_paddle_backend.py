from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from abr.ocr.paddle_backend import PaddleOCRBackend


def test_paddle_backend_reports_missing_package() -> None:
    original_import = __import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "paddleocr":
            raise ImportError("missing paddleocr")
        return original_import(name, globals, locals, fromlist, level)

    with patch("builtins.__import__", side_effect=fake_import):
        backend = PaddleOCRBackend()
        image = np.zeros((10, 10, 3), dtype=np.uint8)
        try:
            backend.recognize(image, language="de")
        except RuntimeError as exc:
            assert 'pip install -e ".[ocr-paddle]"' in str(exc)
        else:
            raise AssertionError("Expected RuntimeError for missing paddleocr package")


def test_paddle_backend_blocks_linux_arm64_by_default() -> None:
    with patch("abr.ocr.paddle_backend.platform.system", return_value="Linux"):
        with patch("abr.ocr.paddle_backend.platform.machine", return_value="aarch64"):
            backend = PaddleOCRBackend()
            image = np.zeros((10, 10, 3), dtype=np.uint8)
            try:
                backend.recognize(image, language="de")
            except RuntimeError as exc:
                assert "Linux ARM64" in str(exc)
                assert "Segmentation Fault" in str(exc)
                assert "ABR_ALLOW_UNSUPPORTED_PADDLE=1" in str(exc)
            else:
                raise AssertionError("Expected RuntimeError for Linux ARM64 Paddle guard")


def test_paddle_backend_reports_missing_runtime_dependency() -> None:
    class FakePaddleOCR:
        def __init__(self, *args, **kwargs) -> None:
            raise RuntimeError(
                "Engine 'paddle_static' is unavailable because dependency 'paddlepaddle' is not installed."
            )

    original_module = sys.modules.get("paddleocr")
    sys.modules["paddleocr"] = SimpleNamespace(PaddleOCR=FakePaddleOCR)
    try:
        backend = PaddleOCRBackend()
        image = np.zeros((10, 10, 3), dtype=np.uint8)
        try:
            backend.recognize(image, language="de")
        except RuntimeError as exc:
            assert "`paddlepaddle` fehlt" in str(exc)
            assert "`.[ocr-paddle]` installiert nur den OCR-Adapter" in str(exc)
        else:
            raise AssertionError("Expected RuntimeError for missing paddlepaddle runtime")
    finally:
        if original_module is None:
            sys.modules.pop("paddleocr", None)
        else:
            sys.modules["paddleocr"] = original_module


def test_paddle_backend_uses_predict_api_and_parses_modern_result() -> None:
    captured: dict[str, object] = {}

    class FakeEngine:
        def predict(self, image, **kwargs):
            captured["image_shape"] = image.shape
            captured["kwargs"] = kwargs
            return [
                {
                    "rec_texts": ["Hallo Welt"],
                    "rec_scores": [0.91],
                    "dt_polys": [[(10, 20), (50, 20), (50, 40), (10, 40)]],
                }
            ]

    backend = PaddleOCRBackend()
    backend._get_engine = lambda language: FakeEngine()  # type: ignore[method-assign]
    image = np.zeros((20, 30, 3), dtype=np.uint8)

    lines = backend.recognize(image, language="de")

    assert captured["image_shape"] == (20, 30, 3)
    assert captured["kwargs"] == {"use_textline_orientation": True}
    assert len(lines) == 1
    assert lines[0].text == "Hallo Welt"
    assert lines[0].confidence == 0.91
    assert lines[0].bbox == ((10, 20), (50, 20), (50, 40), (10, 40))


def test_paddle_backend_falls_back_to_legacy_ocr_api() -> None:
    class FakeLegacyEngine:
        def ocr(self, _image, cls: bool):
            assert cls is True
            return [
                [
                    (
                        [(1, 2), (11, 2), (11, 8), (1, 8)],
                        ("Alt API", 0.75),
                    )
                ]
            ]

    backend = PaddleOCRBackend()
    backend._get_engine = lambda language: FakeLegacyEngine()  # type: ignore[method-assign]
    image = np.zeros((10, 10, 3), dtype=np.uint8)

    lines = backend.recognize(image, language="de")

    assert len(lines) == 1
    assert lines[0].text == "Alt API"
    assert lines[0].confidence == 0.75
    assert lines[0].bbox == ((1, 2), (11, 2), (11, 8), (1, 8))
