from pathlib import Path

import cv2
import numpy as np

from abr.preprocessing.processor import PreprocessorConfig, apply_configured_page_rotation


def test_preprocessor_config_defaults_to_enhanced_mode() -> None:
    config = PreprocessorConfig()

    assert config.ocr_input_mode == "enhanced"
    assert config.denoise_enabled is True
    assert config.sharpen_alpha == 1.2
    assert config.contrast_stretch_strength == 1.0
    assert config.right_page_rotate_deg == 180


def test_preprocessor_config_supports_binary_mode() -> None:
    config = PreprocessorConfig(ocr_input_mode="binary")

    assert config.ocr_input_mode == "binary"


def test_preprocessor_can_skip_denoising() -> None:
    from abr.preprocessing.enhance_for_ocr import preprocess_image_with_timings

    image = np.full((20, 30, 3), 160, dtype=np.uint8)

    artifacts, timings = preprocess_image_with_timings(
        image,
        config=PreprocessorConfig(denoise_enabled=False),
        page_id="page_1",
        source_path=Path("left.jpg"),
    )

    assert np.array_equal(artifacts.gray, artifacts.enhanced) is False
    assert "denoise_sec" in timings


def test_apply_configured_page_rotation_rotates_right_page_by_default() -> None:
    image = np.zeros((2, 3, 3), dtype=np.uint8)
    image[0, 0] = (255, 0, 0)

    rotated = apply_configured_page_rotation(
        image,
        page_id="page_2",
        source_path=Path("right.jpg"),
        config=PreprocessorConfig(),
    )

    assert np.array_equal(rotated, cv2.rotate(image, cv2.ROTATE_180))


def test_preprocessor_keeps_dark_text_darker_than_background() -> None:
    from abr.preprocessing.enhance_for_ocr import preprocess_image

    height, width = 120, 200
    x = np.linspace(150, 220, width, dtype=np.float32)
    background = np.tile(x, (height, 1))
    image = np.stack([background, background, background], axis=2).astype(np.uint8)
    image[45:60, 40:150] = 60
    image[70:82, 60:170] = 80

    artifacts = preprocess_image(image)
    background_mean = float(artifacts.enhanced[10:30, 20:180].mean())
    text_mean = float(artifacts.enhanced[45:60, 40:150].mean())

    assert text_mean < background_mean - 20.0


def test_preprocessor_increases_separation_for_low_contrast_text() -> None:
    from abr.preprocessing.enhance_for_ocr import preprocess_image

    image = np.full((120, 220, 3), 182, dtype=np.uint8)
    image[35:55, 40:180] = 168
    image[70:88, 55:190] = 172

    artifacts = preprocess_image(image)
    original_background_mean = float(image[10:30, 20:200, 0].mean())
    original_text_mean = float(image[35:55, 40:180, 0].mean())
    enhanced_background_mean = float(artifacts.enhanced[10:30, 20:200].mean())
    enhanced_text_mean = float(artifacts.enhanced[35:55, 40:180].mean())

    original_gap = original_background_mean - original_text_mean
    enhanced_gap = enhanced_background_mean - enhanced_text_mean

    assert enhanced_gap > original_gap * 1.8
