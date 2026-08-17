from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from abr.models import PipelineResult


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Accessible Book Reader prototype")
    parser.add_argument("images", nargs="*", help="Input page images")
    parser.add_argument(
        "--case-dir",
        type=Path,
        help="Prepared OCR directory containing left/right images and manifest.json",
    )
    parser.add_argument("--lang", default="de", help="OCR language, e.g. de or en")
    parser.add_argument("--ocr-backend", default="rapidocr", choices=["paddle", "rapidocr", "tesseract"])
    parser.add_argument(
        "--ocr-input-mode",
        default="enhanced",
        choices=["enhanced", "sharpened", "binary"],
        help="Kompatibilitaetsoption. Die Bildoptimierung laeuft nicht mehr in run_fallback_pipeline.py, sondern vorher ueber hardware/enhance_for_ocr.py oder capture_double_page.",
    )
    parser.add_argument(
        "--tesseract-preset",
        default="default",
        choices=["default", "single-column", "single-block", "sparse"],
        help="Tesseract-Settings-Variante fuer --ocr-backend tesseract, Standard: default",
    )
    parser.add_argument("--debug-dir", type=Path, help="Directory for OCR/layout debug images")
    parser.add_argument("--no-debug-artifacts", action="store_true", help="Disable writing intermediate debug images")
    parser.add_argument("--output-dir", type=Path, default=Path("runs/latest"), help="Directory for text and JSON reports")
    parser.add_argument("--speak", action="store_true", help="Speak complete reading chunks")
    parser.add_argument("--tts-backend", default="auto", choices=["auto", "piper", "espeak", "say", "openai", "elevenlabs", "google"])
    parser.add_argument("--tts-model", help="Path to a Piper model file")
    parser.add_argument("--tts-voice", help="Optional voice name for the selected TTS backend")
    parser.add_argument("--tts-speed", type=float, default=1.0, help="Speech speed multiplier: 1.0 normal, 0.8 slower, 1.2 faster")
    parser.add_argument("--live-tts-max-chars", type=int, default=4000, help="Maximum characters per live TTS batch before splitting")
    parser.add_argument("--openai-tts-model", default="gpt-4o-mini-tts", help="OpenAI TTS model for --tts-backend openai")
    parser.add_argument("--openai-tts-instructions", help="Optional voice instructions for OpenAI TTS")
    parser.add_argument("--elevenlabs-voice-id", help="ElevenLabs voice ID for --tts-backend elevenlabs")
    parser.add_argument("--elevenlabs-model-id", default="eleven_multilingual_v2", help="ElevenLabs model ID for --tts-backend elevenlabs")
    parser.add_argument("--elevenlabs-language-code", default="de", help="Optional language code for ElevenLabs, e.g. de")
    parser.add_argument("--google-tts-voice-name", default="de-DE-Standard-H", help="Google Cloud TTS voice name for --tts-backend google")
    parser.add_argument("--google-tts-language-code", default="de-DE", help="Google Cloud TTS language code for --tts-backend google")
    parser.add_argument("--audio-out", type=Path, help="Write synthesized speech to an audio file")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    from abr.debug import DebugArtifactWriter
    from abr.testdata import resolve_input_images
    from abr.ocr import create_ocr_backend
    from abr.pipeline import ABRPipeline
    from abr.tts import create_tts_backend

    _validate_case_dir(args.case_dir, parser)
    image_paths = resolve_input_images(args.images, case_dir=str(args.case_dir) if args.case_dir else None)
    _validate_ocr_input_mode(args.ocr_input_mode, parser)
    output_dir = _resolve_output_dir(args.output_dir, args.case_dir)
    debug_dir = None if args.no_debug_artifacts else (args.debug_dir or (output_dir / "debug"))
    ocr_backend = create_ocr_backend(args.ocr_backend, tesseract_preset=args.tesseract_preset)
    debug_writer = DebugArtifactWriter(debug_dir)
    pipeline = ABRPipeline(ocr_backend=ocr_backend, debug_writer=debug_writer)

    tts_backend = None
    audio_out = args.audio_out
    if args.speak or args.audio_out:
        tts_backend = create_tts_backend(
            args.tts_backend,
            model_path=args.tts_model,
            voice=args.tts_voice,
            require_playback=args.speak,
            speed=args.tts_speed,
            openai_model=args.openai_tts_model,
            openai_instructions=args.openai_tts_instructions,
            elevenlabs_voice_id=args.elevenlabs_voice_id,
            elevenlabs_model_id=args.elevenlabs_model_id,
            elevenlabs_language_code=args.elevenlabs_language_code,
            google_tts_voice_name=args.google_tts_voice_name,
            google_tts_language_code=args.google_tts_language_code,
        )

    status_callback = _make_status_printer()

    result = pipeline.run(
        image_paths,
        language=args.lang,
        speak=args.speak,
        tts_backend=tts_backend,
        output_dir=output_dir,
        audio_output_path=audio_out,
        status_callback=status_callback,
        live_tts_max_chars=args.live_tts_max_chars,
    )
    _print_report(result)
    return 0


def _resolve_output_dir(output_dir: Path, case_dir: Path | None) -> Path:
    default_output = Path("runs/latest")
    if case_dir and output_dir == default_output:
        case_dir = case_dir.expanduser().resolve()
        if case_dir.name == "ocr" and (case_dir / "manifest.json").exists():
            return Path("runs") / case_dir.parent.name
        return Path("runs") / case_dir.name
    return output_dir


def _validate_case_dir(case_dir: Path | None, parser: argparse.ArgumentParser) -> None:
    if case_dir is None:
        return
    resolved = case_dir.expanduser().resolve()
    manifest_path = resolved / "manifest.json"
    if not manifest_path.exists():
        parser.error(
            "--case-dir erwartet jetzt einen vorbereiteten OCR-Ordner mit manifest.json. "
            "Bitte zuerst hardware/enhance_for_ocr.py oder hardware/capture_double_page.py verwenden."
        )


def _validate_ocr_input_mode(ocr_input_mode: str, parser: argparse.ArgumentParser) -> None:
    if ocr_input_mode != "enhanced":
        parser.error(
            "--ocr-input-mode wird in run_fallback_pipeline.py nicht mehr angewendet. "
            "Bitte die gewuenschte OCR-Variante vorher mit hardware/enhance_for_ocr.py erzeugen."
        )


def _default_audio_filename(tts_backend: str) -> str:
    if tts_backend == "say":
        return "speech.aiff"
    if tts_backend == "elevenlabs":
        return "speech.mp3"
    return "speech.wav"


def _make_status_printer():
    start_monotonic = time.monotonic()

    def _print_status(message: str) -> None:
        elapsed = time.monotonic() - start_monotonic
        wall_clock = time.strftime("%H:%M:%S")
        print(f"[status {wall_clock} +{elapsed:6.2f}s] {message}", file=sys.stderr, flush=True)

    return _print_status


def _print_report(result: PipelineResult) -> None:
    print("=== Page Analysis ===")
    for page in result.pages:
        avg_conf = sum(line.confidence for line in page.lines) / max(1, len(page.lines))
        print(f"[{page.slot}] {page.source_path.name}")
        print(f"  rotation: {page.orientation.rotation_deg} deg ({page.orientation.reason})")
        print(f"  page number: {page.page_number if page.page_number is not None else 'n/a'}")
        print(f"  OCR lines: {len(page.lines)} | avg confidence: {avg_conf:.3f}")
        if page.debug_paths:
            debug_listing = ", ".join(f"{stage}={path}" for stage, path in sorted(page.debug_paths.items()))
            print(f"  debug: {debug_listing}")
        for block in page.layout_blocks:
            print(f"  - {block.kind}: {block.text}")

    print("\n=== Reading Stream ===")
    for chunk in result.reading_chunks:
        status = "complete" if chunk.complete else "fragment"
        print(f"[{status}] ({', '.join(chunk.source_pages)}) {chunk.text}")

    print("\n=== Combined Text ===")
    print(result.combined_text)
    if result.timings:
        print("\n=== Timings ===")
        for key, value in sorted(result.timings.items()):
            print(f"{key}: {value:.3f}s")
    if result.tts_metrics:
        print("\n=== TTS Metrics ===")
        print(f"time_to_first_audio_sec: {result.tts_metrics.time_to_first_audio_sec}")
        print(f"time_to_first_playback_sec: {result.tts_metrics.time_to_first_playback_sec}")
        print(f"total_live_tts_sec: {result.tts_metrics.total_live_tts_sec}")
    if result.output_dir:
        print(f"\nOutput directory: {result.output_dir}")
    if result.report_path:
        print(f"JSON report: {result.report_path}")
    if result.audio_path:
        print(f"Audio file: {result.audio_path}")
