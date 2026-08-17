from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil

_TRANSIENT_CAPTURE_DIRS = ("raw", "rectified", "case", "ocr", "debug")


@dataclass(frozen=True)
class ArtifactCleanupConfig:
    mode: str = "debug"
    stage: str = "after-ingest"

    def __post_init__(self) -> None:
        if self.mode not in {"debug", "production"}:
            raise ValueError(f"Ungueltiger Cleanup-Modus: {self.mode}")
        if self.stage not in {"after-ocr", "after-ingest"}:
            raise ValueError(f"Ungueltige Cleanup-Phase: {self.stage}")

    @property
    def enabled(self) -> bool:
        return self.mode == "production"


class ArtifactCleaner:
    def __init__(self, config: ArtifactCleanupConfig) -> None:
        self.config = config

    def cleanup_after_ocr(
        self,
        *,
        session_dir: Path,
        latest_dir: Path,
        ocr_output_dir: Path,
    ) -> list[Path]:
        if not self.config.enabled or self.config.stage != "after-ocr":
            return []
        removed: list[Path] = []
        for relative_name in _TRANSIENT_CAPTURE_DIRS:
            removed.extend(_remove_path(session_dir / relative_name))
            removed.extend(_remove_path(latest_dir / relative_name))
        removed.extend(_remove_path(ocr_output_dir))
        return removed

    def cleanup_after_ingest(
        self,
        *,
        session_dir: Path | None,
        latest_dir: Path,
        ocr_output_dir: Path,
    ) -> list[Path]:
        if not self.config.enabled:
            return []
        removed: list[Path] = []
        if session_dir is not None:
            removed.extend(_remove_path(session_dir))
        removed.extend(_remove_path(latest_dir))
        removed.extend(_remove_path(ocr_output_dir))
        return removed


def _remove_path(path: Path) -> list[Path]:
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        return []
    if resolved.is_dir():
        shutil.rmtree(resolved)
    else:
        resolved.unlink()
    return [resolved]
