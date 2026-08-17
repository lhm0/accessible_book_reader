from __future__ import annotations

from collections import defaultdict

from abr.models import OCRLine
from abr.ocr.base import OCRBackend


TESSERACT_PRESET_CONFIGS: dict[str, str | None] = {
    "default": None,
    "single-column": "--oem 1 --psm 4 -c user_defined_dpi=300 -c preserve_interword_spaces=1",
    "single-block": "--oem 1 --psm 6 -c user_defined_dpi=300 -c preserve_interword_spaces=1",
    "sparse": "--oem 1 --psm 11 -c user_defined_dpi=300",
}


class TesseractOCRBackend(OCRBackend):
    LANGUAGE_MAP = {
        "de": "deu",
        "en": "eng",
    }

    def __init__(self, preset: str = "default") -> None:
        self.preset = normalize_tesseract_preset(preset)

    def recognize(self, image, language: str = "de") -> list[OCRLine]:
        try:
            import pytesseract
        except ImportError as exc:
            raise RuntimeError(
                "pytesseract is not installed. Install with `pip install -e \".[ocr-tesseract]\"`."
            ) from exc

        import cv2

        rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        kwargs = {
            "lang": self.LANGUAGE_MAP.get(language, language),
            "output_type": pytesseract.Output.DICT,
        }
        config = TESSERACT_PRESET_CONFIGS[self.preset]
        if config:
            kwargs["config"] = config
        data = pytesseract.image_to_data(rgb_image, **kwargs)
        return _group_words_into_lines(data)


def normalize_tesseract_preset(preset: str) -> str:
    normalized = preset.strip().lower()
    if normalized not in TESSERACT_PRESET_CONFIGS:
        raise ValueError(f"Unsupported Tesseract preset: {preset}")
    return normalized


def _group_words_into_lines(data: dict[str, list]) -> list[OCRLine]:
    grouped_words: dict[tuple[int, int, int, int], list[dict[str, int | float | str]]] = defaultdict(list)

    for index, raw_text in enumerate(data.get("text", [])):
        normalized = " ".join(str(raw_text).split())
        if not normalized:
            continue

        confidence = _safe_float(data, "conf", index)
        if confidence < 0:
            continue

        word = {
            "text": normalized,
            "conf": confidence / 100.0,
            "left": _safe_int(data, "left", index),
            "top": _safe_int(data, "top", index),
            "width": _safe_int(data, "width", index),
            "height": _safe_int(data, "height", index),
            "word_num": _safe_int(data, "word_num", index),
            "source_index": index,
        }
        line_key = (
            _safe_int(data, "block_num", index),
            _safe_int(data, "par_num", index),
            _safe_int(data, "line_num", index),
            _safe_int(data, "page_num", index, default=0),
        )
        grouped_words[line_key].append(word)

    lines: list[OCRLine] = []
    for source_index, (line_key, words) in enumerate(sorted(grouped_words.items(), key=_sort_key_for_line_group)):
        ordered_words = sorted(words, key=lambda word: (int(word["word_num"]), int(word["left"])))
        text = " ".join(str(word["text"]) for word in ordered_words).strip()
        if not text:
            continue

        left = min(int(word["left"]) for word in ordered_words)
        top = min(int(word["top"]) for word in ordered_words)
        right = max(int(word["left"]) + int(word["width"]) for word in ordered_words)
        bottom = max(int(word["top"]) + int(word["height"]) for word in ordered_words)
        avg_conf = sum(float(word["conf"]) for word in ordered_words) / len(ordered_words)
        block_num, par_num, line_num, page_num = line_key
        bbox = ((left, top), (right, top), (right, bottom), (left, bottom))
        lines.append(
            OCRLine(
                text=text,
                confidence=avg_conf,
                bbox=bbox,
                source_index=source_index,
                metadata={
                    "ocr_engine": "tesseract",
                    "block_num": block_num,
                    "par_num": par_num,
                    "line_num": line_num,
                    "page_num": page_num,
                    "word_count": len(ordered_words),
                    "words": ordered_words,
                },
            )
        )
    return lines


def _sort_key_for_line_group(item: tuple[tuple[int, int, int, int], list[dict[str, int | float | str]]]) -> tuple[int, int, int, int, int, int]:
    (block_num, par_num, line_num, page_num), words = item
    top = min(int(word["top"]) for word in words)
    left = min(int(word["left"]) for word in words)
    return (page_num, block_num, par_num, line_num, top, left)


def _safe_int(data: dict[str, list], key: str, index: int, default: int = 0) -> int:
    try:
        return int(data[key][index])
    except (KeyError, ValueError, TypeError, IndexError):
        return default


def _safe_float(data: dict[str, list], key: str, index: int, default: float = 0.0) -> float:
    try:
        return float(data[key][index])
    except (KeyError, ValueError, TypeError, IndexError):
        return default
