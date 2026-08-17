from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Sequence


DEFAULT_LANGUAGE = "de"
DEFAULT_CONFIG_PATH = Path("~/.config/abr/device.json")
CONFIG_VERSION = 1


@dataclass(frozen=True, slots=True)
class LanguageProfile:
    code: str
    display_name: str
    ocr_language: str
    google_tts_language_code: str
    google_standard_voice_name: str
    google_neural2_voice_name: str
    elevenlabs_language_code: str
    chapter_label: str
    summary_language: str
    google_gemini_flash_prompt: str


LANGUAGE_PROFILES: dict[str, LanguageProfile] = {
    "de": LanguageProfile(
        code="de",
        display_name="Deutsch",
        ocr_language="de",
        google_tts_language_code="de-DE",
        google_standard_voice_name="de-DE-Standard-H",
        google_neural2_voice_name="de-DE-Neural2-H",
        elevenlabs_language_code="de",
        chapter_label="Kapitel",
        summary_language="German",
        google_gemini_flash_prompt=(
            "Lies den folgenden deutschen Buchtext ruhig, klar und natuerlich vor. "
            "Beruecksichtige Bedeutung, Satzstruktur und Dialoge. Verwende eine warme, "
            "zurueckhaltende Hoerbuchintonation ohne uebertriebene Schauspielerei. "
            "Setze an Absatz- und Kapitelgrenzen gut wahrnehmbare Pausen."
        ),
    ),
    "en": LanguageProfile(
        code="en",
        display_name="English (United States)",
        ocr_language="en",
        google_tts_language_code="en-US",
        google_standard_voice_name="en-US-Standard-D",
        google_neural2_voice_name="en-US-Neural2-D",
        elevenlabs_language_code="en",
        chapter_label="Chapter",
        summary_language="English",
        google_gemini_flash_prompt=(
            "Read the following English book text calmly, clearly, and naturally. "
            "Respect meaning, sentence structure, and dialogue. Use a warm, restrained "
            "audiobook delivery without exaggerated acting. Add clearly perceptible "
            "pauses at paragraph and chapter boundaries."
        ),
    ),
}


def get_language_profile(code: str) -> LanguageProfile:
    normalized = code.strip().lower()
    try:
        return LANGUAGE_PROFILES[normalized]
    except KeyError as exc:
        supported = ", ".join(sorted(LANGUAGE_PROFILES))
        raise ValueError(f"Nicht unterstuetzte Buchsprache {code!r}; erlaubt: {supported}.") from exc


class LanguageConfigStore:
    def __init__(self, path: Path = DEFAULT_CONFIG_PATH) -> None:
        self.path = path.expanduser()

    def load(self) -> LanguageProfile:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return LANGUAGE_PROFILES[DEFAULT_LANGUAGE]
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Sprachkonfiguration kann nicht gelesen werden: {self.path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise RuntimeError(f"Ungueltige Sprachkonfiguration in {self.path}: JSON-Objekt erwartet.")
        raw_language = payload.get("language", DEFAULT_LANGUAGE)
        if not isinstance(raw_language, str):
            raise RuntimeError(f"Ungueltige Sprachkonfiguration in {self.path}: language muss Text sein.")
        try:
            return get_language_profile(raw_language)
        except ValueError as exc:
            raise RuntimeError(f"Ungueltige Sprachkonfiguration in {self.path}: {exc}") from exc

    def save(self, language: str) -> LanguageProfile:
        profile = get_language_profile(language)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        payload = {"version": CONFIG_VERSION, "language": profile.code}
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            self.path.chmod(0o600)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        return profile

    def ensure_exists(self) -> LanguageProfile:
        if self.path.exists():
            return self.load()
        return self.save(DEFAULT_LANGUAGE)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Buchsprache des Accessible Book Reader verwalten.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="Aktive und vorbereitete Sprachwerte anzeigen")
    set_parser = subparsers.add_parser("set", help="Buchsprache persistent setzen")
    set_parser.add_argument("language", choices=sorted(LANGUAGE_PROFILES))
    subparsers.add_parser("init", help="Fehlende Konfiguration mit Deutsch als Default anlegen")
    return parser


def _print_profile(profile: LanguageProfile) -> None:
    print(f"Aktive Buchsprache: {profile.display_name} ({profile.code})")
    print(f"OCR: {profile.ocr_language}")
    print(
        "TTS: "
        f"{profile.google_tts_language_code} / {profile.google_standard_voice_name}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    store = LanguageConfigStore(args.config)
    try:
        if args.command == "status":
            profile = store.load()
        elif args.command == "set":
            profile = store.save(args.language)
            print(f"Buchsprache wurde auf {profile.display_name} gesetzt.")
        else:
            profile = store.ensure_exists()
            print(f"Sprachkonfiguration ist vorhanden: {store.path}")
        _print_profile(profile)
    except (OSError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
