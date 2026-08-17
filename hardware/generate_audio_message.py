#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from abr.system_audio import SystemAudioConfig, synthesize_system_message


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Erzeugt eine vorproduzierte Audio-Botschaft fuer Systemhinweise."
    )
    parser.add_argument("filename", help="Zielname der Audio-Datei, z.B. warnung_scan_start")
    parser.add_argument("text", help="Zu sprechender Text")
    parser.add_argument(
        "--ssml",
        action="store_true",
        help="Text als SSML an das TTS-Backend senden. Fuer Google Cloud TTS koennen damit <break>-Pausen genutzt werden.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=PROJECT_ROOT / "system_audio" / "messages",
        help="Ablageverzeichnis fuer Audio-Botschaften. Standard: system_audio/messages",
    )
    parser.add_argument(
        "--tts-backend",
        default="google",
        choices=("auto", "piper", "espeak", "say", "openai", "elevenlabs", "google"),
        help="TTS-Backend. Standard: google.",
    )
    parser.add_argument(
        "--tts-speed",
        type=float,
        default=0.9,
        help="Sprechgeschwindigkeit. Standard: 0.9.",
    )
    parser.add_argument(
        "--tts-model",
        help="Optionales Modell fuer Backends wie Piper.",
    )
    parser.add_argument(
        "--tts-voice",
        help="Optionale allgemeine Voice-Auswahl fuer das gewaehlte Backend.",
    )
    parser.add_argument(
        "--google-tts-voice-name",
        default="de-DE-Standard-A",
        help="Google-Voice fuer Systemhinweise. Standard: de-DE-Standard-A.",
    )
    parser.add_argument(
        "--google-tts-language-code",
        default="de-DE",
        help="Google-Sprachcode. Standard: de-DE.",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    if args.tts_speed <= 0:
        print("Fehler: --tts-speed muss > 0 sein.", file=sys.stderr)
        return 1

    config = SystemAudioConfig(
        root_dir=args.output_root,
        tts_backend=args.tts_backend,
        tts_model=args.tts_model,
        tts_voice=args.tts_voice,
        tts_speed=args.tts_speed,
        google_tts_voice_name=args.google_tts_voice_name,
        google_tts_language_code=args.google_tts_language_code,
    )
    output_path = synthesize_system_message(
        args.text,
        args.filename,
        use_ssml=args.ssml,
        config=config,
    )
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
