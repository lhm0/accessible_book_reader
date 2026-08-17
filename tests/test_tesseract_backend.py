from __future__ import annotations

import sys
from types import SimpleNamespace

import numpy as np

from abr.ocr.factory import create_ocr_backend
from abr.ocr.tesseract_backend import TESSERACT_PRESET_CONFIGS, TesseractOCRBackend, normalize_tesseract_preset


def test_normalize_tesseract_preset_accepts_known_value() -> None:
    assert normalize_tesseract_preset("single-column") == "single-column"


def test_normalize_tesseract_preset_rejects_unknown_value() -> None:
    try:
        normalize_tesseract_preset("invalid")
    except ValueError as exc:
        assert "Unsupported Tesseract preset" in str(exc)
    else:
        raise AssertionError("Expected ValueError for invalid Tesseract preset")


def test_factory_passes_tesseract_preset_to_backend() -> None:
    backend = create_ocr_backend("tesseract", tesseract_preset="single-block")

    assert isinstance(backend, TesseractOCRBackend)
    assert backend.preset == "single-block"


def test_tesseract_backend_forwards_config_for_selected_preset() -> None:
    captured: dict[str, object] = {}

    def fake_image_to_data(image, **kwargs):
        captured["image_shape"] = image.shape
        captured["kwargs"] = kwargs
        return {"text": [], "conf": []}

    fake_module = SimpleNamespace(
        Output=SimpleNamespace(DICT="DICT"),
        image_to_data=fake_image_to_data,
    )
    original_module = sys.modules.get("pytesseract")
    sys.modules["pytesseract"] = fake_module
    try:
        backend = TesseractOCRBackend(preset="single-column")
        image = np.zeros((20, 30, 3), dtype=np.uint8)
        lines = backend.recognize(image, language="de")
    finally:
        if original_module is None:
            sys.modules.pop("pytesseract", None)
        else:
            sys.modules["pytesseract"] = original_module

    assert lines == []
    assert captured["image_shape"] == (20, 30, 3)
    kwargs = captured["kwargs"]
    assert kwargs["lang"] == "deu"
    assert kwargs["output_type"] == "DICT"
    assert kwargs["config"] == TESSERACT_PRESET_CONFIGS["single-column"]


def test_tesseract_backend_omits_config_for_default_preset() -> None:
    captured: dict[str, object] = {}

    def fake_image_to_data(_image, **kwargs):
        captured["kwargs"] = kwargs
        return {"text": [], "conf": []}

    fake_module = SimpleNamespace(
        Output=SimpleNamespace(DICT="DICT"),
        image_to_data=fake_image_to_data,
    )
    original_module = sys.modules.get("pytesseract")
    sys.modules["pytesseract"] = fake_module
    try:
        backend = TesseractOCRBackend(preset="default")
        image = np.zeros((10, 10, 3), dtype=np.uint8)
        backend.recognize(image, language="en")
    finally:
        if original_module is None:
            sys.modules.pop("pytesseract", None)
        else:
            sys.modules["pytesseract"] = original_module

    kwargs = captured["kwargs"]
    assert kwargs["lang"] == "eng"
    assert "config" not in kwargs
