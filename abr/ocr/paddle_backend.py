from __future__ import annotations

import os
import platform
from collections.abc import Iterable, Mapping

from abr.models import OCRLine
from abr.ocr.base import OCRBackend


def _bbox_from_points(points: Iterable[Iterable[float]]) -> tuple[tuple[int, int], ...]:
    return tuple((int(point[0]), int(point[1])) for point in points)


def _coerce_result_mapping(result: object) -> Mapping[str, object] | None:
    if isinstance(result, Mapping):
        return result
    for attr_name in ("res",):
        value = getattr(result, attr_name, None)
        if isinstance(value, Mapping):
            return value
    for method_name in ("to_dict", "as_dict"):
        method = getattr(result, method_name, None)
        if callable(method):
            value = method()
            if isinstance(value, Mapping):
                return value
    return None


def _as_sequence(value: object) -> list[object]:
    if value is None:
        return []
    if isinstance(value, (str, bytes)):
        return [value]
    if isinstance(value, Iterable):
        return list(value)
    return [value]


def _first_present(mapping: Mapping[str, object], keys: tuple[str, ...]) -> object | None:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def _is_linux_arm64() -> bool:
    return platform.system().lower() == "linux" and platform.machine().lower() in {"aarch64", "arm64"}


class PaddleOCRBackend(OCRBackend):
    LANGUAGE_MAP = {
        "de": "german",
        "en": "en",
    }

    def __init__(self, use_angle_cls: bool = True) -> None:
        self.use_angle_cls = use_angle_cls
        self._engines: dict[str, object] = {}

    def _get_engine(self, language: str) -> object:
        if _is_linux_arm64() and os.environ.get("ABR_ALLOW_UNSUPPORTED_PADDLE") != "1":
            raise RuntimeError(
                "PaddleOCR ist im ABR-Projekt auf Linux ARM64 (z. B. Raspberry Pi 5) derzeit deaktiviert. "
                "Der native `paddlepaddle`-Pfad fuehrt dort reproduzierbar zu einem Segmentation Fault. "
                "Bitte fuer den Pi `--ocr-backend tesseract` verwenden. "
                "Nur wenn Du den nativen Paddle-Stack bewusst trotzdem testen willst, "
                "setze vorher `ABR_ALLOW_UNSUPPORTED_PADDLE=1`."
            )

        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise RuntimeError(
                "PaddleOCR is not installed. Install with `pip install -e \".[ocr-paddle]\"`."
            ) from exc

        mapped_language = self.LANGUAGE_MAP.get(language, language)
        if mapped_language not in self._engines:
            try:
                self._engines[mapped_language] = PaddleOCR(
                    use_angle_cls=self.use_angle_cls,
                    lang=mapped_language,
                )
            except RuntimeError as exc:
                if "dependency 'paddlepaddle' is not installed" in str(exc):
                    raise RuntimeError(
                        "PaddleOCR wurde gefunden, aber die Inferenz-Laufzeit `paddlepaddle` fehlt. "
                        "`.[ocr-paddle]` installiert nur den OCR-Adapter. "
                        "Bitte `paddlepaddle` in derselben virtuellen Umgebung separat installieren."
                    ) from exc
                raise
        return self._engines[mapped_language]

    def recognize(self, image, language: str = "de") -> list[OCRLine]:
        engine = self._get_engine(language)
        result = self._run_engine(engine, image)
        result_items = list(result) if isinstance(result, Iterable) and not isinstance(result, (str, bytes, Mapping)) else [result]
        page_result = result_items[0] if result_items else []

        modern_lines = self._parse_modern_result(page_result)
        if modern_lines is not None:
            return modern_lines

        lines: list[OCRLine] = []
        for index, entry in enumerate(page_result):
            if not entry or len(entry) != 2:
                continue
            bbox, payload = entry
            if not payload or len(payload) != 2:
                continue
            text, confidence = payload
            normalized = " ".join(str(text).split())
            if not normalized:
                continue
            lines.append(
                OCRLine(
                    text=normalized,
                    confidence=float(confidence),
                    bbox=_bbox_from_points(bbox),  # type: ignore[arg-type]
                    source_index=index,
                )
            )
        return lines

    def _run_engine(self, engine: object, image: object) -> object:
        predict = getattr(engine, "predict", None)
        if callable(predict):
            return predict(
                image,
                use_textline_orientation=self.use_angle_cls,
            )
        return engine.ocr(image, cls=self.use_angle_cls)

    def _parse_modern_result(self, page_result: object) -> list[OCRLine] | None:
        mapping = _coerce_result_mapping(page_result)
        if mapping is None:
            return None

        texts = _as_sequence(
            _first_present(mapping, ("rec_texts", "texts", "rec_text", "text"))
        )
        if not texts:
            return []

        boxes = _as_sequence(
            _first_present(mapping, ("dt_polys", "rec_polys", "text_boxes", "boxes", "polys"))
        )
        scores = _as_sequence(
            _first_present(mapping, ("rec_scores", "scores", "score", "confidences"))
        )

        lines: list[OCRLine] = []
        for index, raw_text in enumerate(texts):
            normalized = " ".join(str(raw_text).split())
            if not normalized:
                continue
            bbox_source = boxes[index] if index < len(boxes) else ()
            score = scores[index] if index < len(scores) else 0.0
            lines.append(
                OCRLine(
                    text=normalized,
                    confidence=float(score),
                    bbox=_bbox_from_points(bbox_source),  # type: ignore[arg-type]
                    source_index=index,
                )
            )
        return lines
