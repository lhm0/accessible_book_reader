from __future__ import annotations

import re
import time
from dataclasses import dataclass

from abr.models import ImageArray, OCRLine, OrientationCandidate
from abr.ocr.base import OCRBackend


class TextPlausibilityScorer:
    _valid_word = re.compile(r"[A-Za-zÄÖÜäöüß]{2,}")

    def score(self, lines: list[OCRLine]) -> float:
        if not lines:
            return float("-inf")

        text = " ".join(line.text for line in lines).strip()
        if not text:
            return float("-inf")

        avg_conf = sum(line.confidence for line in lines) / len(lines)
        words = text.split()
        valid_words = sum(1 for word in words if self._valid_word.search(word))
        alpha_chars = sum(1 for char in text if char.isalpha())
        total_chars = len(text)
        punctuation_bonus = 0.2 if any(char in text for char in ".?!,:;") else 0.0
        lowercase_bonus = 0.1 if any(char.islower() for char in text) else 0.0
        valid_ratio = valid_words / max(1, len(words))
        alpha_ratio = alpha_chars / max(1, total_chars)
        return avg_conf * 0.6 + valid_ratio * 0.25 + alpha_ratio * 0.05 + punctuation_bonus + lowercase_bonus


@dataclass(slots=True)
class OrientationDetectionResult:
    candidate: OrientationCandidate
    rotated_image: ImageArray
    timings: dict[str, float]


class OCRBasedOrientationDetector:
    def __init__(self, ocr_backend: OCRBackend, scorer: TextPlausibilityScorer | None = None) -> None:
        self.ocr_backend = ocr_backend
        self.scorer = scorer or TextPlausibilityScorer()

    def detect(self, image: ImageArray, language: str = "de") -> OrientationDetectionResult:
        candidates: list[tuple[OrientationCandidate, ImageArray]] = []
        timings: dict[str, float] = {}
        total_started = time.monotonic()
        for rotation_deg in (0, 180):
            rotate_started = time.monotonic()
            rotated = self._rotate(image, rotation_deg)
            timings[f"rotate_{rotation_deg}_sec"] = time.monotonic() - rotate_started
            started = time.monotonic()
            lines = self.ocr_backend.recognize(rotated, language=language)
            timings[f"ocr_{rotation_deg}_sec"] = time.monotonic() - started
            score = self.scorer.score(lines)
            reason = f"{len(lines)} lines, score={score:.3f}"
            candidates.append((OrientationCandidate(rotation_deg=rotation_deg, score=score, lines=lines, reason=reason), rotated))

        best_candidate, best_image = max(candidates, key=lambda item: item[0].score)
        timings["ocr_total_sec"] = sum(timings.get(f"ocr_{rotation_deg}_sec", 0.0) for rotation_deg in (0, 180))
        timings["rotate_total_sec"] = sum(timings.get(f"rotate_{rotation_deg}_sec", 0.0) for rotation_deg in (0, 180))
        timings["total_sec"] = time.monotonic() - total_started
        return OrientationDetectionResult(
            candidate=best_candidate,
            rotated_image=best_image,
            timings=timings,
        )

    @staticmethod
    def _rotate(image: ImageArray, rotation_deg: int) -> ImageArray:
        if rotation_deg == 0:
            return image.copy()
        if rotation_deg == 180:
            import cv2

            return cv2.rotate(image, cv2.ROTATE_180)
        raise ValueError(f"Unsupported rotation: {rotation_deg}")
