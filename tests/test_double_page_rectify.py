import json
from pathlib import Path

import cv2
import numpy as np

from abr.hardware.double_page_rectify import RectifySlot, rectify_existing_capture


def test_rectify_existing_capture_creates_rectified_and_case(tmp_path: Path) -> None:
    session_dir = tmp_path / "captures" / "latest"
    raw_dir = session_dir / "raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / "cam0_raw.jpg").write_bytes(b"raw-0")
    (raw_dir / "cam1_raw.jpg").write_bytes(b"raw-1")

    calls: list[tuple[int, Path, Path]] = []

    def fake_rectify(slot: RectifySlot, raw_path: Path, rectified_path: Path) -> list[str]:
        calls.append((slot.camera_index, raw_path, rectified_path))
        rectified_path.write_bytes(raw_path.read_bytes() + b"-rectified")
        return ["fake-rectify", str(slot.camera_index), str(rectified_path)]

    rectify_existing_capture(
        session_dir=session_dir,
        slots=[
            RectifySlot("left", 0, tmp_path / "cam0_planar.npz"),
            RectifySlot("right", 1, tmp_path / "cam1_planar.npz"),
        ],
        python_executable="/fake/python",
        rectify_func=fake_rectify,
    )

    assert calls == [
        (0, raw_dir / "cam0_raw.jpg", session_dir / "rectified" / "cam0_rectified.jpg"),
        (1, raw_dir / "cam1_raw.jpg", session_dir / "rectified" / "cam1_rectified.jpg"),
    ]
    assert (session_dir / "case" / "left.jpg").read_bytes() == b"raw-0-rectified"
    assert (session_dir / "case" / "right.jpg").read_bytes() == b"raw-1-rectified"

    metadata = json.loads((session_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["case_dir"] == str(session_dir / "case")
    assert metadata["slots"]["left"]["rectify_command"][0] == "fake-rectify"
    assert metadata["slots"]["right"]["case_path"] == str(session_dir / "case" / "right.jpg")


def test_rectify_existing_capture_requires_raw_dir(tmp_path: Path) -> None:
    try:
        rectify_existing_capture(
            session_dir=tmp_path / "missing",
            slots=[RectifySlot("left", 0, tmp_path / "cam0_planar.npz")],
            python_executable="/fake/python",
        )
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("Expected FileNotFoundError for missing raw directory")


def test_rectify_existing_capture_applies_rotation(tmp_path: Path) -> None:
    session_dir = tmp_path / "captures" / "latest"
    raw_dir = session_dir / "raw"
    raw_dir.mkdir(parents=True)
    source = np.zeros((40, 60, 3), dtype=np.uint8)
    source[0:10, 0:10] = (255, 0, 0)
    source[30:40, 50:60] = (0, 255, 0)
    ok = cv2.imwrite(str(raw_dir / "cam1_raw.jpg"), source)
    assert ok

    def fake_rectify(slot: RectifySlot, raw_path: Path, rectified_path: Path) -> list[str]:
        ok_write = cv2.imwrite(str(rectified_path), cv2.imread(str(raw_path), cv2.IMREAD_COLOR))
        assert ok_write
        return ["fake-rectify", str(slot.camera_index), str(rectified_path)]

    rectify_existing_capture(
        session_dir=session_dir,
        slots=[RectifySlot("right", 1, tmp_path / "cam1_planar.npz", rotate_deg=180)],
        python_executable="/fake/python",
        rectify_func=fake_rectify,
    )

    rotated = cv2.imread(str(session_dir / "case" / "right.jpg"), cv2.IMREAD_COLOR)
    assert rotated is not None
    assert int(rotated[0:10, 0:10, 1].mean()) > 150
    assert int(rotated[30:40, 50:60, 0].mean()) > 150
