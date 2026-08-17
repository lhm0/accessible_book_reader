from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import numpy as np
except ImportError:  # pragma: no cover - fallback for lightweight environments
    np = None


class DebugArtifactWriter:
    def __init__(self, output_dir: Path | None) -> None:
        self.output_dir = Path(output_dir).expanduser().resolve() if output_dir else None
        if self.output_dir:
            self.output_dir.mkdir(parents=True, exist_ok=True)

    @property
    def enabled(self) -> bool:
        return self.output_dir is not None

    def write_image(self, page_id: str, stage: str, image: Any) -> Path | None:
        if not self.output_dir:
            return None
        import cv2

        page_dir = self.output_dir / page_id
        page_dir.mkdir(parents=True, exist_ok=True)
        output_path = page_dir / f"{stage}.png"
        cv2.imwrite(str(output_path), image)
        return output_path
