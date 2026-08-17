from abr.tts.command_backend import _piper_length_scale, _words_per_minute


def test_piper_length_scale_increases_when_speed_is_lower() -> None:
    assert _piper_length_scale(0.8) > 1.0
    assert _piper_length_scale(1.0) == 1.0


def test_words_per_minute_scales_with_speed() -> None:
    assert _words_per_minute(0.8) < _words_per_minute(1.0)
    assert _words_per_minute(1.2) > _words_per_minute(1.0)
