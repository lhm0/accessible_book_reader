from __future__ import annotations

import sys
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from abr.ocr.factory import create_ocr_backend
from abr.ocr.rapidocr_backend import RapidOCRBackend


def test_factory_creates_rapidocr_backend() -> None:
    backend = create_ocr_backend("rapidocr")
    assert isinstance(backend, RapidOCRBackend)


def test_rapidocr_backend_reports_missing_package() -> None:
    original_import = __import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "rapidocr":
            raise ImportError("missing rapidocr")
        return original_import(name, globals, locals, fromlist, level)

    with patch("builtins.__import__", side_effect=fake_import):
        backend = RapidOCRBackend()
        image = np.zeros((10, 10, 3), dtype=np.uint8)
        try:
            backend.recognize(image, language="de")
        except RuntimeError as exc:
            assert 'pip install -e ".[ocr-rapidocr]"' in str(exc)
            assert "pip install rapidocr onnxruntime" in str(exc)
        else:
            raise AssertionError("Expected RuntimeError for missing rapidocr package")


@dataclass
class FakeRapidOutput:
    boxes: list[list[tuple[int, int]]]
    txts: list[str]
    scores: list[float]


def test_rapidocr_backend_parses_documented_output_dataclass() -> None:
    class FakeEngine:
        def __call__(self, image):
            assert image.shape == (20, 30, 3)
            return FakeRapidOutput(
                boxes=[[(1, 2), (11, 2), (11, 8), (1, 8)]],
                txts=["Hallo RapidOCR"],
                scores=[0.88],
            )

    backend = RapidOCRBackend()
    backend._get_engine = lambda language="de": FakeEngine()  # type: ignore[method-assign]
    image = np.zeros((20, 30, 3), dtype=np.uint8)

    lines = backend.recognize(image, language="de")

    assert len(lines) == 1
    assert lines[0].text == "Hallo RapidOCR"
    assert lines[0].confidence == 0.88
    assert lines[0].bbox == ((1, 2), (11, 2), (11, 8), (1, 8))
    assert lines[0].metadata["ocr_engine"] == "rapidocr"


def test_rapidocr_backend_parses_tuple_wrapped_output() -> None:
    class FakeEngine:
        def __call__(self, _image):
            return (
                [
                    ([(2, 3), (12, 3), (12, 9), (2, 9)], "Tuple Format", 0.67),
                ],
                0.012,
            )

    backend = RapidOCRBackend()
    backend._get_engine = lambda language="de": FakeEngine()  # type: ignore[method-assign]
    image = np.zeros((10, 10, 3), dtype=np.uint8)

    lines = backend.recognize(image, language="de")

    assert len(lines) == 1
    assert lines[0].text == "Tuple Format"
    assert lines[0].confidence == 0.67
    assert lines[0].bbox == ((2, 3), (12, 3), (12, 9), (2, 9))


def test_rapidocr_backend_reuses_constructed_engine() -> None:
    calls: list[str] = []

    class FakeRapidOCR:
        def __call__(self, _image):
            return FakeRapidOutput(
                boxes=[[(1, 1), (2, 1), (2, 2), (1, 2)]],
                txts=["cached"],
                scores=[0.5],
            )

    def fake_ctor():
        calls.append("ctor")
        return FakeRapidOCR()

    original_module = sys.modules.get("rapidocr")
    sys.modules["rapidocr"] = SimpleNamespace(RapidOCR=fake_ctor)
    try:
        backend = RapidOCRBackend()
        image = np.zeros((5, 5, 3), dtype=np.uint8)
        backend.recognize(image)
        backend.recognize(image)
    finally:
        if original_module is None:
            sys.modules.pop("rapidocr", None)
        else:
            sys.modules["rapidocr"] = original_module

    assert calls == ["ctor"]


def test_rapidocr_backend_parses_alternative_output_field_names() -> None:
    @dataclass
    class FakeRapidOCROutput:
        rec_boxes: list[list[tuple[int, int]]]
        rec_txts: list[str]
        rec_scores: list[float]

    class FakeEngine:
        def __call__(self, _image):
            return FakeRapidOCROutput(
                rec_boxes=[[(5, 6), (15, 6), (15, 12), (5, 12)]],
                rec_txts=["Alternative Felder"],
                rec_scores=[0.77],
            )

    backend = RapidOCRBackend()
    backend._get_engine = lambda language="de": FakeEngine()  # type: ignore[method-assign]
    image = np.zeros((10, 10, 3), dtype=np.uint8)

    lines = backend.recognize(image, language="de")

    assert len(lines) == 1
    assert lines[0].text == "Alternative Felder"
    assert lines[0].confidence == 0.77


def test_rapidocr_backend_treats_empty_output_object_as_empty_page() -> None:
    @dataclass
    class FakeRapidOCREmptyOutput:
        boxes: list[list[tuple[int, int]]] | None = None
        txts: list[str] | None = None
        scores: list[float] | None = None

    class FakeEngine:
        def __call__(self, _image):
            return FakeRapidOCREmptyOutput()

    backend = RapidOCRBackend()
    backend._get_engine = lambda language="de": FakeEngine()  # type: ignore[method-assign]
    image = np.zeros((10, 10, 3), dtype=np.uint8)

    lines = backend.recognize(image, language="de")

    assert lines == []


def test_rapidocr_backend_keeps_german_constructor_unchanged() -> None:
    constructor_calls: list[dict[str, object]] = []

    class FakeRapidOCR:
        def __init__(self, **kwargs) -> None:
            constructor_calls.append(kwargs)

        def __call__(self, _image):
            return FakeRapidOutput(boxes=[], txts=[], scores=[])

    original_module = sys.modules.get("rapidocr")
    sys.modules["rapidocr"] = SimpleNamespace(RapidOCR=FakeRapidOCR)
    try:
        RapidOCRBackend().recognize(np.zeros((5, 5, 3), dtype=np.uint8), language="de")
    finally:
        if original_module is None:
            sys.modules.pop("rapidocr", None)
        else:
            sys.modules["rapidocr"] = original_module

    assert constructor_calls == [{}]


def test_rapidocr_backend_selects_english_ppocrv5_mobile_recognition_model() -> None:
    constructor_calls: list[dict[str, object]] = []

    class FakeRapidOCR:
        def __init__(self, **kwargs) -> None:
            constructor_calls.append(kwargs)

        def __call__(self, _image):
            return FakeRapidOutput(
                boxes=[[(1, 1), (2, 1), (2, 2), (1, 2)]],
                txts=["English text"],
                scores=[0.9],
            )

    fake_module = SimpleNamespace(
        RapidOCR=FakeRapidOCR,
        LangRec=SimpleNamespace(EN="en"),
        ModelType=SimpleNamespace(MOBILE="mobile"),
        OCRVersion=SimpleNamespace(PPOCRV5="PP-OCRv5"),
    )
    original_module = sys.modules.get("rapidocr")
    sys.modules["rapidocr"] = fake_module
    try:
        lines = RapidOCRBackend().recognize(
            np.zeros((5, 5, 3), dtype=np.uint8),
            language="en",
        )
    finally:
        if original_module is None:
            sys.modules.pop("rapidocr", None)
        else:
            sys.modules["rapidocr"] = original_module

    assert constructor_calls == [
        {
            "params": {
                "Rec.lang_type": "en",
                "Rec.model_type": "mobile",
                "Rec.ocr_version": "PP-OCRv5",
            }
        }
    ]
    assert lines[0].metadata == {
        "ocr_engine": "rapidocr",
        "ocr_language": "en",
        "ocr_model_profile": "en-ppocrv5-mobile",
    }


def test_rapidocr_backend_caches_german_and_english_engines_separately() -> None:
    backend = RapidOCRBackend()
    backend._engines = {"de": object(), "en": object()}

    assert backend._get_engine("de") is backend._engines["de"]
    assert backend._get_engine("en") is backend._engines["en"]
    assert backend._engines["de"] is not backend._engines["en"]
