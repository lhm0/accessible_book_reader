from __future__ import annotations

from abr.ocr.base import OCRBackend
from abr.ocr.paddle_backend import PaddleOCRBackend
from abr.ocr.rapidocr_backend import RapidOCRBackend
from abr.ocr.tesseract_backend import TesseractOCRBackend


def create_ocr_backend(name: str, *, tesseract_preset: str = "default") -> OCRBackend:
    normalized = name.strip().lower()
    if normalized == "paddle":
        return PaddleOCRBackend()
    if normalized in {"rapidocr", "rapid"}:
        return RapidOCRBackend()
    if normalized == "tesseract":
        return TesseractOCRBackend(preset=tesseract_preset)
    raise ValueError(f"Unsupported OCR backend: {name}")
