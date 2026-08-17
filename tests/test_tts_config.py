from abr.cli import _default_audio_filename, build_parser


def test_default_audio_filename_for_say() -> None:
    assert _default_audio_filename("say") == "speech.aiff"


def test_default_audio_filename_for_other_backends() -> None:
    assert _default_audio_filename("espeak") == "speech.wav"


def test_cli_defaults_follow_current_project_path() -> None:
    args = build_parser().parse_args([])
    assert args.ocr_backend == "rapidocr"
    assert args.google_tts_voice_name == "de-DE-Standard-H"
    assert args.live_tts_max_chars == 4000
    assert args.no_debug_artifacts is False


def test_cli_allows_disabling_debug_and_tuning_live_tts_batches() -> None:
    args = build_parser().parse_args(["--no-debug-artifacts", "--live-tts-max-chars", "500"])
    assert args.no_debug_artifacts is True
    assert args.live_tts_max_chars == 500


def test_cli_allows_switching_ocr_backend() -> None:
    args = build_parser().parse_args(["--ocr-backend", "paddle"])
    assert args.ocr_backend == "paddle"


def test_cli_allows_rapidocr_backend() -> None:
    args = build_parser().parse_args(["--ocr-backend", "rapidocr"])
    assert args.ocr_backend == "rapidocr"
