from __future__ import annotations

from pathlib import Path


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}


def resolve_input_images(images: list[str], case_dir: str | None = None) -> list[Path]:
    if case_dir:
        return _resolve_case_dir(Path(case_dir))
    if not images:
        raise ValueError("No input images were provided.")
    return [Path(image).expanduser().resolve() for image in images]


def _resolve_case_dir(case_dir: Path) -> list[Path]:
    resolved = case_dir.expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"Case directory not found: {resolved}")
    if not resolved.is_dir():
        raise ValueError(f"Case path is not a directory: {resolved}")

    left = _find_named_image(resolved, ("left", "page_left", "links", "seite_links"))
    right = _find_named_image(resolved, ("right", "page_right", "rechts", "seite_rechts"))
    if left and right:
        return [left, right]

    images = sorted(path for path in resolved.iterdir() if path.suffix.lower() in IMAGE_EXTENSIONS)
    if len(images) < 2:
        raise ValueError(
            f"Case directory must contain at least two images or files named like left/right: {resolved}"
        )
    return images[:2]


def _find_named_image(directory: Path, stems: tuple[str, ...]) -> Path | None:
    for stem in stems:
        for extension in IMAGE_EXTENSIONS:
            candidate = directory / f"{stem}{extension}"
            if candidate.exists():
                return candidate.resolve()
    return None
