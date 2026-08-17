from __future__ import annotations

from abc import ABC, abstractmethod

from abr.models import ImageArray, OCRLine


class OCRBackend(ABC):
    @abstractmethod
    def recognize(self, image: ImageArray, language: str = "de") -> list[OCRLine]:
        raise NotImplementedError
