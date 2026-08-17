from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from abr.models import ImageArray, PreprocessArtifacts


@dataclass(slots=True)
class PreprocessorConfig:
    ocr_input_mode: str = "enhanced"
    denoise_enabled: bool = True
    sharpen_alpha: float = 1.2
    sharpen_sigma: float = 1.0
    threshold_block_size: int = 35
    threshold_c: int = 11
    contrast_low_percentile: float = 5.0
    contrast_high_percentile: float = 95.0
    contrast_stretch_strength: float = 1.0
    left_page_rotate_deg: int = 0
    right_page_rotate_deg: int = 180


class ImagePreprocessor:
    def __init__(self, config: PreprocessorConfig | None = None) -> None:
        self.config = config or PreprocessorConfig()

    def run(self, image: ImageArray) -> PreprocessArtifacts:
        artifacts, _ = self.run_with_timings(image)
        return artifacts

    def run_with_timings(self, image: ImageArray) -> tuple[PreprocessArtifacts, dict[str, float]]:
        import cv2

        timings: dict[str, float] = {}

        started = time.monotonic()
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        timings["gray_sec"] = time.monotonic() - started

        started = time.monotonic()
        if self.config.denoise_enabled:
            denoised = cv2.fastNlMeansDenoising(gray, None, h=9, templateWindowSize=7, searchWindowSize=21)
        else:
            denoised = gray.copy()
        timings["denoise_sec"] = time.monotonic() - started

        started = time.monotonic()
        spread = self._spread_gray_levels(denoised)
        timings["contrast_spread_sec"] = time.monotonic() - started

        started = time.monotonic()
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(spread)
        timings["clahe_sec"] = time.monotonic() - started

        started = time.monotonic()
        blur = cv2.GaussianBlur(enhanced, (0, 0), sigmaX=self.config.sharpen_sigma)
        sharpened = cv2.addWeighted(enhanced, self.config.sharpen_alpha, blur, 1.0 - self.config.sharpen_alpha, 0)
        timings["sharpen_sec"] = time.monotonic() - started

        started = time.monotonic()
        binary = cv2.adaptiveThreshold(
            sharpened,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            self.config.threshold_block_size,
            self.config.threshold_c,
        )
        timings["binary_sec"] = time.monotonic() - started

        started = time.monotonic()
        ocr_source = self._select_ocr_source(enhanced, sharpened, binary)
        ocr_input = cv2.cvtColor(ocr_source, cv2.COLOR_GRAY2BGR)
        timings["ocr_prepare_sec"] = time.monotonic() - started

        artifacts = PreprocessArtifacts(
            gray=gray,
            enhanced=enhanced,
            sharpened=sharpened,
            binary=binary,
            ocr_input=ocr_input,
        )
        timings["preprocess_total_sec"] = sum(
            timings[key]
            for key in (
                "gray_sec",
                "denoise_sec",
                "contrast_spread_sec",
                "clahe_sec",
                "sharpen_sec",
                "binary_sec",
                "ocr_prepare_sec",
            )
        )
        return artifacts, timings

    def _select_ocr_source(self, enhanced: ImageArray, sharpened: ImageArray, binary: ImageArray) -> ImageArray:
        mode = self.config.ocr_input_mode
        if mode == "enhanced":
            return enhanced
        if mode == "sharpened":
            return sharpened
        if mode == "binary":
            return binary
        raise ValueError(f"Unsupported OCR input mode: {mode}")

    def _spread_gray_levels(self, gray: ImageArray) -> ImageArray:
        image_float = gray.astype(np.float32)
        lower = float(np.percentile(image_float, self.config.contrast_low_percentile))
        upper = float(np.percentile(image_float, self.config.contrast_high_percentile))
        if upper <= lower + 1.0:
            return gray.copy()

        stretched = (image_float - lower) * (255.0 / (upper - lower))
        stretched = np.clip(stretched, 0.0, 255.0)
        strength = float(np.clip(self.config.contrast_stretch_strength, 0.0, 1.0))
        blended = (image_float * (1.0 - strength)) + (stretched * strength)
        return np.clip(blended, 0.0, 255.0).astype(np.uint8)


def apply_configured_page_rotation(
    image: ImageArray,
    *,
    page_id: str | None,
    source_path: Path | None,
    config: PreprocessorConfig | None = None,
) -> ImageArray:
    active_config = config or PreprocessorConfig()
    rotate_deg = _rotation_for_page(page_id=page_id, source_path=source_path, config=active_config)
    if rotate_deg == 0:
        return image

    import cv2

    if rotate_deg == 90:
        return cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
    if rotate_deg == 180:
        return cv2.rotate(image, cv2.ROTATE_180)
    if rotate_deg == 270:
        return cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
    raise ValueError(f"Unsupported preprocessing rotation: {rotate_deg}")


def _rotation_for_page(
    *,
    page_id: str | None,
    source_path: Path | None,
    config: PreprocessorConfig,
) -> int:
    if source_path is not None:
        stem = source_path.stem.lower()
        if stem in {"left", "page_left", "links", "seite_links"}:
            return config.left_page_rotate_deg
        if stem in {"right", "page_right", "rechts", "seite_rechts"}:
            return config.right_page_rotate_deg

    if page_id == "page_1":
        return config.left_page_rotate_deg
    if page_id == "page_2":
        return config.right_page_rotate_deg
    return 0
