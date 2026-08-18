from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, is_dataclass
import logging

from abr.models import OCRLine
from abr.ocr.base import OCRBackend


def _bbox_from_points(points: Iterable[Iterable[float]]) -> tuple[tuple[int, int], ...]:
    return tuple((int(point[0]), int(point[1])) for point in points)


def _as_sequence(value: object) -> list[object]:
    if value is None:
        return []
    if isinstance(value, (str, bytes)):
        return [value]
    if isinstance(value, Iterable):
        return list(value)
    return [value]


def _coerce_mapping(value: object) -> Mapping[str, object] | None:
    if isinstance(value, Mapping):
        return value
    if is_dataclass(value):
        result = asdict(value)
        if isinstance(result, Mapping):
            return result
    if hasattr(value, "__dict__"):
        result = vars(value)
        if isinstance(result, Mapping):
            return result
    for method_name in ("to_dict", "asdict", "as_dict"):
        method = getattr(value, method_name, None)
        if callable(method):
            result = method()
            if isinstance(result, Mapping):
                return result
    return None


def _first_present(mapping: Mapping[str, object], keys: tuple[str, ...]) -> object | None:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def _configure_rapidocr_logging() -> None:
    logging.getLogger("RapidOCR").setLevel(logging.WARNING)
    logging.getLogger("rapidocr").setLevel(logging.WARNING)
    logging.getLogger("onnxruntime").setLevel(logging.ERROR)
    try:
        import onnxruntime as ort
    except ImportError:
        return
    try:
        ort.set_default_logger_severity(3)
    except AttributeError:
        return


class RapidOCRBackend(OCRBackend):
    def __init__(self) -> None:
        self._engines: dict[str, object] = {}

    def _get_engine(self, language: str = "de") -> object:
        normalized_language = language.strip().lower()
        if normalized_language not in {"de", "en"}:
            raise ValueError(f"RapidOCR-Sprache wird nicht unterstuetzt: {language!r}")
        if normalized_language in self._engines:
            return self._engines[normalized_language]

        try:
            from rapidocr import RapidOCR
        except ImportError as exc:
            raise RuntimeError(
                "RapidOCR ist nicht installiert. Install mit `pip install -e \".[ocr-rapidocr]\"` "
                "oder direkt mit `pip install rapidocr onnxruntime`."
            ) from exc

        _configure_rapidocr_logging()
        if normalized_language == "de":
            # Preserve the established German model path byte-for-byte. The
            # English model must not silently alter German recognition.
            engine = RapidOCR()
        else:
            try:
                from rapidocr import LangRec, ModelType, OCRVersion
            except ImportError as exc:
                raise RuntimeError(
                    "Englisches RapidOCR benoetigt rapidocr>=3.4 mit LangRec, "
                    "ModelType und OCRVersion. Bitte `pip install -U \"rapidocr>=3.4,<4\"` ausfuehren."
                ) from exc
            engine = RapidOCR(
                params={
                    "Rec.lang_type": LangRec.EN,
                    "Rec.model_type": ModelType.MOBILE,
                    "Rec.ocr_version": OCRVersion.PPOCRV5,
                }
            )
        self._engines[normalized_language] = engine
        return engine

    def recognize(self, image, language: str = "de") -> list[OCRLine]:
        normalized_language = language.strip().lower()
        engine = self._get_engine(normalized_language)
        result = engine(image)
        output = self._normalize_output(result)
        lines = self._build_lines(output)
        model_profile = "default" if normalized_language == "de" else "en-ppocrv5-mobile"
        for line in lines:
            line.metadata["ocr_language"] = normalized_language
            line.metadata["ocr_model_profile"] = model_profile
        return lines

    def classify_text_orientation(
        self,
        images: list[object],
        language: str = "de",
    ) -> list[tuple[str, float]]:
        """Classify cropped text lines as upright (0) or upside down (180)."""
        engine = self._get_engine(language.strip().lower())
        classifications: list[tuple[str, float]] = []
        for image in images:
            result = engine(image, use_det=False, use_cls=True, use_rec=False)
            output = self._normalize_output(result)
            cls_res = getattr(output, "cls_res", None)
            if cls_res is None and isinstance(output, dict):
                cls_res = output.get("cls_res")
            if not cls_res:
                continue
            label, confidence = cls_res[0]
            normalized_label = str(label)
            if normalized_label not in {"0", "180"}:
                continue
            classifications.append((normalized_label, float(confidence)))
        return classifications

    def _normalize_output(self, result: object) -> object:
        if isinstance(result, tuple) and result:
            return result[0]
        return result

    def _build_lines(self, output: object) -> list[OCRLine]:
        parsed = self._parse_dataclass_or_mapping(output)
        if parsed is not None:
            return parsed

        parsed = self._parse_parallel_sequences(output)
        if parsed is not None:
            return parsed

        parsed = self._parse_legacy_sequence(output)
        if parsed is not None:
            return parsed

        raise RuntimeError(
            f"RapidOCR lieferte ein unbekanntes Ergebnisformat: {type(output).__name__}"
        )

    def _parse_dataclass_or_mapping(self, output: object) -> list[OCRLine] | None:
        mapping = _coerce_mapping(output)
        boxes = None
        txts = None
        scores = None
        had_ocr_fields = False

        if mapping is not None:
            had_ocr_fields = any(
                key in mapping
                for key in (
                    "boxes",
                    "dt_boxes",
                    "txts",
                    "texts",
                    "rec_texts",
                    "rec_txts",
                    "scores",
                    "rec_scores",
                )
            )
            boxes = _first_present(mapping, ("boxes", "dt_boxes", "rec_boxes"))
            txts = _first_present(mapping, ("txts", "texts", "rec_texts", "rec_txts"))
            scores = _first_present(mapping, ("scores", "rec_scores", "score_list"))
        else:
            for attribute_name in (
                "boxes",
                "dt_boxes",
                "rec_boxes",
                "txts",
                "texts",
                "rec_texts",
                "rec_txts",
                "scores",
                "rec_scores",
                "score_list",
            ):
                if hasattr(output, attribute_name):
                    had_ocr_fields = True
                    break
            boxes = getattr(output, "boxes", None) or getattr(output, "dt_boxes", None) or getattr(output, "rec_boxes", None)
            txts = (
                getattr(output, "txts", None)
                or getattr(output, "texts", None)
                or getattr(output, "rec_texts", None)
                or getattr(output, "rec_txts", None)
            )
            scores = getattr(output, "scores", None) or getattr(output, "rec_scores", None) or getattr(output, "score_list", None)

        if boxes is None or txts is None:
            if had_ocr_fields:
                return []
            return None

        box_list = _as_sequence(boxes)
        text_list = _as_sequence(txts)
        score_list = _as_sequence(scores)
        lines: list[OCRLine] = []
        for index, raw_text in enumerate(text_list):
            normalized = " ".join(str(raw_text).split())
            if not normalized:
                continue
            bbox_source = box_list[index] if index < len(box_list) else ()
            confidence = float(score_list[index]) if index < len(score_list) else 0.0
            lines.append(
                OCRLine(
                    text=normalized,
                    confidence=confidence,
                    bbox=_bbox_from_points(bbox_source),  # type: ignore[arg-type]
                    source_index=index,
                    metadata={"ocr_engine": "rapidocr"},
                )
            )
        return lines

    def _parse_parallel_sequences(self, output: object) -> list[OCRLine] | None:
        sequence = _as_sequence(output)
        if len(sequence) < 2:
            return None
        box_list = _as_sequence(sequence[0])
        text_list = _as_sequence(sequence[1])
        if not text_list:
            return []
        if not box_list:
            return []
        if not all(isinstance(text, (str, bytes)) for text in text_list):
            return None
        if not all(isinstance(box, Iterable) and not isinstance(box, (str, bytes)) for box in box_list):
            return None
        score_list = _as_sequence(sequence[2]) if len(sequence) > 2 else []
        lines: list[OCRLine] = []
        for index, raw_text in enumerate(text_list):
            normalized = " ".join(str(raw_text).split())
            if not normalized:
                continue
            bbox_source = box_list[index] if index < len(box_list) else ()
            confidence = float(score_list[index]) if index < len(score_list) else 0.0
            lines.append(
                OCRLine(
                    text=normalized,
                    confidence=confidence,
                    bbox=_bbox_from_points(bbox_source),  # type: ignore[arg-type]
                    source_index=index,
                    metadata={"ocr_engine": "rapidocr"},
                )
            )
        return lines

    def _parse_legacy_sequence(self, output: object) -> list[OCRLine] | None:
        sequence = _as_sequence(output)
        if not sequence:
            return []

        first = sequence[0]
        if not isinstance(first, (list, tuple)) or len(first) < 2:
            return None

        lines: list[OCRLine] = []
        for index, entry in enumerate(sequence):
            if not isinstance(entry, (list, tuple)) or len(entry) < 2:
                continue
            bbox_source = entry[0]
            raw_text = entry[1]
            confidence = entry[2] if len(entry) > 2 else 0.0
            normalized = " ".join(str(raw_text).split())
            if not normalized:
                continue
            lines.append(
                OCRLine(
                    text=normalized,
                    confidence=float(confidence),
                    bbox=_bbox_from_points(bbox_source),  # type: ignore[arg-type]
                    source_index=index,
                    metadata={"ocr_engine": "rapidocr"},
                )
            )
        return lines
