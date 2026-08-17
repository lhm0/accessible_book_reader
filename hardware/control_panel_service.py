#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from abr.control import (
    ABRAction,
    ABRActionType,
    AudioVolumeConfig,
    AudioVolumeController,
    ArtifactCleanupConfig,
    CaptureOCRJobConfig,
    ForegroundJobManager,
    PageAudioPlayer,
    PageSpeechConfig,
    FrontPanelConfig,
    FrontPanelMonitor,
    PageIngestRuntimeConfig,
    RuntimeController,
    build_page_ingest_service,
)
from abr.book import (
    BookStore,
    ChapterAssembler,
    GeminiSummaryBackend,
    GeminiSummaryConfig,
    SummaryManager,
    SummaryManagerConfig,
)
from abr.hardware.nfc_gateway import GatewayNFCTagReader, NFCGatewayConfig
from abr.hardware.pico_gateway_client import DEFAULT_DEVICE as DEFAULT_NFC_DEVICE
from abr.control.frontpanel import FrontPanelButtonConfig, FrontPanelEncoderEvent
from abr.usage_statistics import UsageStatisticsStore
from abr.language_config import DEFAULT_CONFIG_PATH as DEFAULT_LANGUAGE_CONFIG_PATH
from abr.language_config import LanguageConfigStore, LanguageProfile
from abr.system_audio import SystemAudioConfig


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Dauerhafter Frontpanel-Monitor fuer Taster und EC11 des ABR-Projekts."
    )
    parser.add_argument(
        "--gpio-backend",
        choices=("auto", "rpi-gpio", "pinctrl"),
        default="auto",
        help="GPIO-Backend fuer den direkten Pi-Zugriff, Standard: auto.",
    )
    parser.add_argument(
        "--poll-interval-ms",
        type=float,
        default=2.0,
        help="Normales Polling-Intervall in Millisekunden, Standard: 2.0.",
    )
    parser.add_argument(
        "--active-poll-interval-ms",
        type=float,
        default=0.5,
        help="Schnelles Polling waehrend Encoder-Aktivitaet, Standard: 0.5.",
    )
    parser.add_argument(
        "--encoder-active-hold-ms",
        type=float,
        default=25.0,
        help="Wie lange nach Encoder-Flanken schnell gepollt wird, Standard: 25.",
    )
    parser.add_argument(
        "--button-debounce-ms",
        type=float,
        default=25.0,
        help="Debounce-Zeit fuer alle Taster in Millisekunden, Standard: 25.",
    )
    parser.add_argument(
        "--job-mode",
        choices=("dummy", "capture-ocr"),
        default="capture-ocr",
        help="Welcher Start/Stop-Job ausgefuehrt wird, Standard: capture-ocr.",
    )
    parser.add_argument(
        "--dummy-job-seconds",
        type=float,
        default=8.0,
        help="Dauer des Dummy-Capture/OCR-Jobs in Sekunden, Standard: 8.0.",
    )
    parser.add_argument(
        "--capture-output-root",
        type=Path,
        default=Path("captures"),
        help="Ausgabewurzel fuer capture_double_page.py, Standard: captures",
    )
    parser.add_argument(
        "--ocr-output-dir",
        type=Path,
        default=Path("runs/latest_rapidocr"),
        help="Ausgabeverzeichnis fuer run_rapidocr.py, Standard: runs/latest_rapidocr",
    )
    parser.add_argument(
        "--orientation-mode",
        choices=("off", "simple"),
        default="off",
        help="Orientierungsmodus fuer run_rapidocr.py, Standard: off.",
    )
    parser.add_argument(
        "--overlay",
        action="store_true",
        help="OCR-Overlay-Bilder fuer run_rapidocr.py erzeugen.",
    )
    parser.add_argument(
        "--capture-timeout-ms",
        type=int,
        help="Optionaler Capture-Timeout fuer capture_double_page.py.",
    )
    parser.add_argument(
        "--keep-denoise",
        action="store_true",
        help="De-Noising im Capture/OCR-Pfad aktiv lassen. Standard ist --no-denoise.",
    )
    parser.add_argument(
        "--library-root",
        type=Path,
        default=Path("library"),
        help="Buchdaten-Wurzel fuer PageIngestor, Standard: library",
    )
    parser.add_argument(
        "--book-tag-id",
        default="TESTBOOK",
        help="Fallback-Buch-ID, wenn NFC explizit deaktiviert ist. Standard: TESTBOOK",
    )
    parser.add_argument(
        "--nfc-mode",
        choices=("gateway", "disabled"),
        default="gateway",
        help="Quelle fuer Buch-Tags. Standard: gateway.",
    )
    parser.add_argument(
        "--nfc-device",
        default=DEFAULT_NFC_DEVICE,
        help=f"UART-Geraet fuer das NFC-Gateway, Standard: {DEFAULT_NFC_DEVICE}",
    )
    parser.add_argument(
        "--nfc-baud",
        type=int,
        default=115200,
        help="Baudrate fuer das NFC-Gateway, Standard: 115200.",
    )
    parser.add_argument(
        "--nfc-timeout",
        type=float,
        default=10.0,
        help="Timeout fuer NFC-Statusabfrage inklusive STATUS_FETCH in Sekunden, Standard: 10.0.",
    )
    parser.add_argument(
        "--iso15693-only-orientation",
        choices=("reader1", "reader2"),
        default="reader2",
        help=(
            "Orientierung bei Zuordnung nur ueber ISO15693: reader2 behaelt die "
            "Links-/Rechts-Zuordnung, reader1 vertauscht beide Seiten. Die "
            "Seiten werden nicht zusaetzlich gedreht. Standard: reader2."
        ),
    )
    parser.add_argument(
        "--artifact-mode",
        choices=("debug", "production"),
        default="debug",
        help="Artefaktmodus: debug behaelt alles, production raeumt auf. Standard: debug.",
    )
    parser.add_argument(
        "--cleanup-stage",
        choices=("after-ocr", "after-ingest"),
        default="after-ingest",
        help="Wann in production aufgeraeumt wird. Standard: after-ingest.",
    )
    parser.add_argument(
        "--volume-mixer-control",
        default="auto",
        help="Mixer-Control fuer die EC11-Lautstaerkeregelung, Standard: auto.",
    )
    parser.add_argument(
        "--language-config",
        type=Path,
        default=DEFAULT_LANGUAGE_CONFIG_PATH,
        help="Persistente Buchsprachenkonfiguration, Standard: ~/.config/abr/device.json.",
    )
    parser.add_argument(
        "--page-tts-backend",
        choices=("google", "google-standard-enhanced", "google-neural2", "google-gemini-flash"),
        default="google",
        help=(
            "TTS-Pfad fuer Buchseiten: google nutzt die Standardstimme des Sprachprofils; "
            "google-standard-enhanced nutzt dieselbe Stimme mit erweiterter SSML-Aufbereitung; "
            "google-neural2 und google-gemini-flash aktivieren getrennte "
            "Versuchspfade. Standard: google."
        ),
    )
    parser.add_argument(
        "--page-tts-speed",
        type=float,
        default=0.9,
        help="Sprechgeschwindigkeit fuer die Seitenausgabe, Standard: 0.9.",
    )
    parser.add_argument(
        "--google-standard-voice-name",
        help="Optionale abweichende Google-Standardstimme; Standard kommt aus dem Sprachprofil.",
    )
    parser.add_argument(
        "--google-neural2-voice-name",
        help="Optionale Neural2-Stimme; Standard kommt aus dem Sprachprofil.",
    )
    parser.add_argument(
        "--google-gemini-flash-voice-name",
        default="Charon",
        help="Stimme fuer Gemini 2.5 Flash TTS, Standard: Charon.",
    )
    parser.add_argument(
        "--google-gemini-flash-prompt",
        help="Optionale Stilanweisung; Standard kommt aus dem Sprachprofil.",
    )
    parser.add_argument(
        "--summary-gemini-model",
        default="gemini-3.5-flash",
        help="Gemini-Modell fuer Kapitel- und Buchzusammenfassungen, Standard: gemini-3.5-flash.",
    )
    parser.add_argument(
        "--summary-gcp-project",
        help="Optionales Google-Cloud-Projekt fuer Gemini-Zusammenfassungen. Standard: ADC/gcloud-Projekt.",
    )
    parser.add_argument(
        "--summary-gcp-location",
        default="global",
        help="Google-Cloud-Location fuer Gemini-Zusammenfassungen, Standard: global.",
    )
    parser.add_argument(
        "--chapter-summary-target-pages",
        type=float,
        default=1.5,
        help=(
            "Zielgroesse fuer Kapitelzusammenfassungen; eine Textseite entspricht "
            "250 Woertern. Standard: 1.5."
        ),
    )
    parser.add_argument(
        "--book-summary-target-pages",
        type=float,
        default=1.5,
        help=(
            "Zielgroesse fuer 'Was bisher geschah'; eine Textseite entspricht "
            "250 Woertern. Standard: 1.5."
        ),
    )
    return parser


def _timestamp() -> str:
    return time.strftime("%H:%M:%S")


def _print_status(message: str) -> None:
    print(f"[{_timestamp()}] {message}", flush=True)


def _describe_action(action: ABRAction) -> str:
    if action.action_type == ABRActionType.DELETE_BOOK_REQUEST:
        return "Benutzereingabe: Dreifachtaste fuer Buch-Loeschen gedrueckt"
    if action.action_type == ABRActionType.START_STOP:
        return "Benutzereingabe: Start / Stop / NFC gedrueckt"
    if action.action_type == ABRActionType.BOOK_SUMMARY:
        return "Benutzereingabe: Buch-Zusammenfassung gedrueckt"
    if action.action_type == ABRActionType.CHAPTER_SUMMARY:
        return "Benutzereingabe: Kapitel-/Letzte-Seiten-Zusammenfassung gedrueckt"
    if action.action_type == ABRActionType.ENCODER_BUTTON:
        return "Benutzereingabe: EC11-Taster gedrueckt"
    if action.action_type == ABRActionType.VOLUME_DELTA:
        assert action.value is not None
        direction = "rechts" if action.value > 0 else "links"
        steps = abs(action.value)
        encoder_event = action.source_event
        position_text = ""
        if isinstance(encoder_event, FrontPanelEncoderEvent):
            position_text = f", Position {encoder_event.position}"
        if steps == 1:
            return f"Benutzereingabe: EC11 1 Rasterung nach {direction}{position_text}"
        return f"Benutzereingabe: EC11 {steps} Rasterungen nach {direction}{position_text}"
    return f"Benutzereingabe: {action.source_event.label}"


def _print_action(action: ABRAction) -> None:
    print(f"[{_timestamp()}] {_describe_action(action)}", flush=True)


def _build_page_speech_config(
    args: argparse.Namespace,
    language_profile: LanguageProfile,
) -> PageSpeechConfig:
    return PageSpeechConfig(
        language_code=language_profile.code,
        chapter_label=language_profile.chapter_label,
        tts_backend=args.page_tts_backend,
        tts_speed=args.page_tts_speed,
        elevenlabs_language_code=language_profile.elevenlabs_language_code,
        google_tts_voice_name=(
            args.google_standard_voice_name
            or language_profile.google_standard_voice_name
        ),
        google_tts_language_code=language_profile.google_tts_language_code,
        google_neural2_voice_name=(
            args.google_neural2_voice_name
            or language_profile.google_neural2_voice_name
        ),
        google_gemini_flash_voice_name=args.google_gemini_flash_voice_name,
        google_gemini_flash_prompt=(
            args.google_gemini_flash_prompt
            or language_profile.google_gemini_flash_prompt
        ),
    )


def _build_system_audio_config(language_profile: LanguageProfile) -> SystemAudioConfig:
    return SystemAudioConfig(
        root_dir=PROJECT_ROOT / "system_audio" / "messages" / language_profile.code,
    )


def main() -> int:
    args = _build_parser().parse_args()
    if min(
        args.poll_interval_ms,
        args.active_poll_interval_ms,
        args.encoder_active_hold_ms,
        args.button_debounce_ms,
        args.dummy_job_seconds,
    ) <= 0:
        print("Fehler: Alle Zeitparameter muessen > 0 sein.", file=sys.stderr)
        return 1
    if args.capture_timeout_ms is not None and args.capture_timeout_ms < 0:
        print("Fehler: --capture-timeout-ms darf nicht negativ sein.", file=sys.stderr)
        return 1
    if args.nfc_baud <= 0 or args.nfc_timeout <= 0:
        print("Fehler: --nfc-baud und --nfc-timeout muessen > 0 sein.", file=sys.stderr)
        return 1
    if args.page_tts_speed <= 0:
        print("Fehler: --page-tts-speed muss > 0 sein.", file=sys.stderr)
        return 1

    try:
        language_profile = LanguageConfigStore(args.language_config).load()
    except RuntimeError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1
    _print_status(
        f"Buchsprache: {language_profile.display_name} ({language_profile.code}); "
        f"TTS {language_profile.google_tts_language_code}."
    )

    config = FrontPanelConfig(
        gpio_backend=args.gpio_backend,
        poll_interval_ms=args.poll_interval_ms,
        active_poll_interval_ms=args.active_poll_interval_ms,
        encoder_active_hold_ms=args.encoder_active_hold_ms,
        buttons=tuple(
            FrontPanelButtonConfig(
                name=button.name,
                label=button.label,
                pin=button.pin,
                debounce_ms=args.button_debounce_ms,
            )
            for button in FrontPanelConfig().buttons
        ),
    )
    monitor = FrontPanelMonitor(config=config, status_callback=_print_status)
    job_manager = ForegroundJobManager()
    artifact_cleanup = ArtifactCleanupConfig(
        mode=args.artifact_mode,
        stage=args.cleanup_stage,
    )
    capture_ocr_config = CaptureOCRJobConfig(
        python_executable=sys.executable,
        project_root=PROJECT_ROOT,
        capture_output_root=args.capture_output_root,
        ocr_output_dir=args.ocr_output_dir,
        capture_timeout_ms=args.capture_timeout_ms,
        no_denoise=not args.keep_denoise,
        overlay=args.overlay,
        orientation_mode=args.orientation_mode,
        language=language_profile.ocr_language,
        iso15693_only_orientation=args.iso15693_only_orientation,
        artifact_cleanup=artifact_cleanup,
    )
    page_ingest_service = build_page_ingest_service(
        library_root=args.library_root,
        capture_ocr_config=capture_ocr_config,
        language_code=language_profile.code,
        status_callback=lambda message: _print_status(f"ingest: {message}"),
    )
    book_store = BookStore(args.library_root.expanduser().resolve())
    usage_statistics = UsageStatisticsStore(args.library_root)
    chapter_assembler = ChapterAssembler(book_store)
    summary_manager = SummaryManager(
        book_store,
        GeminiSummaryBackend(
            GeminiSummaryConfig(
                model=args.summary_gemini_model,
                project_id=args.summary_gcp_project,
                location=args.summary_gcp_location,
            )
        ),
        SummaryManagerConfig(
            chapter_summary_target_pages=args.chapter_summary_target_pages,
            book_summary_target_pages=args.book_summary_target_pages,
            language=language_profile.code,
        ),
    )
    nfc_tag_reader = None
    if args.nfc_mode == "gateway":
        nfc_tag_reader = GatewayNFCTagReader(
            NFCGatewayConfig(
                device=args.nfc_device,
                baud=args.nfc_baud,
                timeout=args.nfc_timeout,
            )
        )
    volume_controller = AudioVolumeController(
        AudioVolumeConfig(mixer_control=args.volume_mixer_control)
    )
    controller = RuntimeController(
        monitor=monitor,
        job_manager=job_manager,
        action_callback=_print_action,
        status_callback=lambda message: _print_status(f"runtime: {message}"),
        dummy_capture_job_seconds=args.dummy_job_seconds,
        capture_ocr_config=capture_ocr_config,
        capture_ocr_enabled=args.job_mode == "capture-ocr",
        page_ingest_service=page_ingest_service,
        page_ingest_config=PageIngestRuntimeConfig(
            library_root=args.library_root,
            fallback_tag_id=args.book_tag_id,
        ),
        system_audio_config=_build_system_audio_config(language_profile),
        page_audio_player=PageAudioPlayer(
            config=_build_page_speech_config(args, language_profile),
            status_callback=lambda message: _print_status(f"readout: {message}"),
            volume_provider=volume_controller.current_percent,
        ),
        chapter_assembler=chapter_assembler,
        summary_manager=summary_manager,
        volume_controller=volume_controller,
        nfc_tag_reader=nfc_tag_reader,
        usage_statistics=usage_statistics,
    )

    try:
        if args.job_mode == "capture-ocr":
            cleanup_text = (
                "Debug-Modus: alle technischen Artefakte bleiben erhalten."
                if args.artifact_mode == "debug"
                else f"Produktiv-Modus: Cleanup {args.cleanup_stage} aktiv."
            )
            _print_status(
                "Testmodus: Start / Stop startet bzw. stoppt den echten Capture/OCR-Pfad. "
                f"Page-Ingest speichert unter {args.library_root}; Buch-ID kommt aus {args.nfc_mode}. "
                f"Seitenausgabe verwendet {args.page_tts_backend}. "
                f"{cleanup_text} Dreifachtaste startet den Buch-Loeschdialog. "
                "Andere Eingaben werden nur als Text ausgegeben."
            )
        else:
            _print_status(
                "Testmodus: Start / Stop startet bzw. stoppt einen Dummy-Capture/OCR-Job. "
                "Andere Eingaben werden nur als Text ausgegeben."
            )
        controller.run_forever()
        return 0
    except KeyboardInterrupt:
        controller.stop()
        print("\nBeendet.", flush=True)
        return 0
    except RuntimeError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
