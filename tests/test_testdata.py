from pathlib import Path

from abr.testdata import resolve_input_images


def test_resolve_input_images_prefers_left_right_names(tmp_path: Path) -> None:
    case_dir = tmp_path / "case_001"
    case_dir.mkdir()
    left = case_dir / "left.jpg"
    right = case_dir / "right.png"
    other = case_dir / "aaa.jpg"
    left.write_bytes(b"x")
    right.write_bytes(b"y")
    other.write_bytes(b"z")

    resolved = resolve_input_images([], case_dir=str(case_dir))

    assert resolved == [left.resolve(), right.resolve()]


def test_resolve_input_images_falls_back_to_sorted_images(tmp_path: Path) -> None:
    case_dir = tmp_path / "case_002"
    case_dir.mkdir()
    first = case_dir / "001.jpg"
    second = case_dir / "002.jpg"
    first.write_bytes(b"a")
    second.write_bytes(b"b")

    resolved = resolve_input_images([], case_dir=str(case_dir))

    assert resolved == [first.resolve(), second.resolve()]
