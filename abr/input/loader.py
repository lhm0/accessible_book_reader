from __future__ import annotations

from pathlib import Path
from typing import Iterable

from abr.models import PageInput


def load_page_inputs(paths: Iterable[Path]) -> list[PageInput]:
    import cv2

    inputs: list[PageInput] = []
    for index, path in enumerate(paths, start=1):
        source_path = Path(path).expanduser().resolve()
        if not source_path.exists():
            raise FileNotFoundError(f"Image not found: {source_path}")
        image = cv2.imread(str(source_path), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError(f"Failed to load image: {source_path}")
        inputs.append(PageInput(page_id=f"page_{index}", source_path=source_path, image=image))
    return inputs
