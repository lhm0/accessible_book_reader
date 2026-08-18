# German and U.S. English Book Languages

Last reviewed: `2026-08-07` — stages 1 through 5 and multilingual system
prompts implemented

Deutsche Fassung: [Buchsprachen Deutsch und U.S.-Englisch](../docs_DE/LANGUAGE_PROFILES.md)

## Goal

ABR supports German and English books. The language is deliberately selected
with a command; automatic language detection is not planned. English uses
U.S. English (`en-US`) throughout.

The existing German production path remains the default. If the configuration
file is missing, the code uses exactly the previous German values.

## Stage 1: Central Language Profiles

The following are implemented:

- [abr/language_config.py](../abr/language_config.py)
- immutable `LanguageProfile` for `de`
- immutable `LanguageProfile` for `en` using U.S. English
- persistent selection in `~/.config/abr/device.json`
- atomic writes with file mode `0600`
- fallback to German when the configuration is missing
- clear startup failure when the configuration is invalid
- CLI commands for `status`, `set`, and idempotent `init`
- installer for the system-wide `abr-language` command

Configured values:

| Value | German | English |
|---|---|---|
| Profile code | `de` | `en` |
| OCR language | `de` | `en` |
| Google language code | `de-DE` | `en-US` |
| Google Standard voice | `de-DE-Standard-H` | `en-US-Standard-D` |
| Google Neural2 voice | `de-DE-Neural2-H` | `en-US-Neural2-D` |
| Chapter label | `Kapitel` | `Chapter` |
| Summary language | German | English |

The Gemini Flash TTS prompt template is also configured per profile.

## Stage 2: Runtime, TTS, and Chapter Announcements

The production runtime reads `~/.config/abr/device.json` at startup. An
existing invalid configuration prevents startup with a clear error message;
a missing file continues to select German.

The active profile controls:

- Google Standard voice and `languageCode`
- Google Neural2 voice
- ElevenLabs language code
- the German or U.S. English Gemini Flash audiobook prompt
- the chapter label `Kapitel` or `Chapter`
- spelled-out isolated chapter numbers, for example `Kapitel zwei.` or
  `Chapter forty-two.`
- chapter pauses in both the regular and enhanced SSML renderers

The active profile also selects pre-generated system prompts from
`system_audio/messages/de/` or `system_audio/messages/en/`. Logical filenames
such as `bing`, `fehler`, and `buch_nicht_erkannt` are identical in both
directories. The runtime therefore switches only the language directory, not
individual message names. Because the profile is read at service startup, the
selection takes effect after the service restart performed by `abr-language`.

## Stage 3: RapidOCR

The OCR language code is carried through the complete path:

- `CaptureOCRJobConfig.language`
- `hardware/run_rapidocr.py --language de|en`
- regular and incremental runtime paths
- orientation testing and final page recognition
- `ocr_language` in `report.json` and `ScanRecord` metadata
- language and model profile in each RapidOCR line's metadata

The model strategy protects the verified German behavior:

- `de` continues to construct the previous parameterless `RapidOCR()` engine
- `en` explicitly selects `LangRec.EN`, `ModelType.MOBILE`, and
  `OCRVersion.PPOCRV5` for recognition
- separate German and English engines are cached within the process

RapidOCR version `3.4` or newer is required. The optional dependency is
therefore constrained to `rapidocr>=3.4,<4`. After updating on the Pi:

```bash
cd ~/src/abr
source .venv/bin/activate
pip install -e ".[ocr-rapidocr]"
```

On the first English OCR run, RapidOCR may download the English model. With an
internet connection available, do this once before the actual test. Using
existing capture images:

```bash
python hardware/run_rapidocr.py \
  --ocr-dir captures/latest/ocr \
  --output-dir runs/english_rapidocr \
  --orientation-mode off \
  --language en \
  --overlay
```

The language and model profile are then recorded in the report:

```bash
python -m json.tool runs/english_rapidocr/report.json | less
```

The API configuration follows the official
[RapidOCR model list](https://rapidai.github.io/RapidOCRDocs/latest/model_list/).

## Stage 4: Summaries and Cache

The active language profile is passed to `SummaryManager` at startup. It now
controls:

- section summaries
- temporary recaps combining a completed section with open pages
- book recaps in the style of `Was bisher geschah` or
  `Previously in the book`
- the second shortening pass when the word limit is exceeded
- English page-range descriptions in Gemini prompts

English instructions request natural U.S. English and fluent prose suitable
for reading aloud. The German prompts remain unchanged.

Persistent section and book summaries now carry `metadata.language` with `de`
or `en`. A cache is reused only when its language matches the active profile.
Legacy summary files without a language field are treated as German for
compatibility, so existing German caches remain valid. Temporary recaps are
still not persisted, but also carry their language in runtime metadata.

## Stage 5: Book Protection and Integration

On the first scan of a new NFC book, the active profile is stored permanently
as `BookRecord.language` in `book.json`. The following protections then apply:

- OCR report and active profile must match
- active profile and stored book language must match
- all pages must use the same language as their book
- sections carry the validated book language in their metadata
- summary generation and playback reject a different language
- page playback rejects pages whose language differs from the active TTS
  language

An English book therefore cannot accidentally be continued or summarized in
German mode, and vice versa. Before switching to another book, first activate
its language with `abr-language`.

Legacy books without `language` are deliberately treated as German. When such
a book is ingested again in German mode, `language: de` is added, preserving
compatibility with existing German data.

English test books created before Stage 5 must be reviewed and either migrated
once or recreated. Set `language` to `en` only when all page metadata contains
`en`. After backing up and inspecting the current test book, it can be migrated
with this small Python script:

```bash
cp library/53C78C6D220001/book.json \
  library/53C78C6D220001/book.json.before-language-migration

.venv/bin/python - <<'PY'
from dataclasses import replace
from pathlib import Path
from abr.book import BookStore

tag_id = "53C78C6D220001"
store = BookStore(Path("library"))
book = store.load_book(tag_id)
if book is None:
    raise SystemExit("Book not found")
if book.language not in {None, "en"}:
    raise SystemExit(f"Book is already bound to {book.language}")
bad_pages = [
    page.page_id for page in store.list_pages(tag_id)
    if page.metadata.get("language") != "en"
]
if bad_pages:
    raise SystemExit(f"Migration cancelled; non-English pages: {bad_pages}")
store.save_book(replace(book, language="en"))
print(f"{tag_id} was safely bound to en.")
PY
```

The automated `tests/test_english_book_integration.py` test covers:

```text
capture images -> English OCR report -> ingest -> BookRecord.language
-> section -> English summary -> en-US TTS handoff
```

RapidOCR, Gemini, and Google TTS are replaced by deterministic backends in
this test. Their production interfaces and all language checks are exercised
for real. Quality and runtime testing with real services remains a manual Pi
test.

Direct development test without installation:

```bash
.venv/bin/python -m abr.language_config status
.venv/bin/python -m abr.language_config set en
.venv/bin/python -m abr.language_config set de
```

Install the system command on the Pi:

```bash
cd ~/src/abr
sudo deploy/install_language_switch.sh
abr-language status
```

Switch languages with:

```bash
sudo abr-language en
sudo abr-language de
```

The command writes the selection as the configured service user, restarts
`abr-control-panel.service`, and verifies that the service is active. The
language change therefore applies from the next scan; the service restart
terminates an active scan.

The installer initializes a missing configuration with `de`. Reinstalling
does not overwrite an existing selection.

## Extension: Multilingual System Prompts

Control prompts now follow the manually selected profile as well. The
directory structure is:

```text
system_audio/messages/
  de/
    <logical-name>.wav
  en/
    <logical-name>.wav
```

At startup, `hardware/control_panel_service.py` creates a `SystemAudioConfig`
whose `root_dir` points to the `language_profile.code` subdirectory. The path
is built as an absolute path from `PROJECT_ROOT` and is therefore independent
of the systemd service's working directory. Every call in `RuntimeController`
uses this single configuration.

Filenames are identical in both languages; only the recording is translated.
Whenever a new runtime message is added, both a German and an English WAV file
must be created. A missing prompt is reported as an error and is not replaced
from the other language directory.

For example, additional English recordings can be generated with:

```bash
export SSL_CERT_FILE="$(python -c 'import certifi; print(certifi.where())')"

python hardware/generate_audio_message.py \
  --ssml \
  --output-root "$HOME/tmp_audio_export/en" \
  --google-tts-language-code en-US \
  --google-tts-voice-name en-US-Standard-C \
  fehler \
  '<speak>An error occurred.<break time="700ms"/>Please try again.</speak>'
```

The explicit certificate variable is particularly relevant on the development
Mac when the project `.venv` is based on PlatformIO's Python installation and
its built-in CA path does not exist. Do not disable SSL verification.

## Tests for Stages 1–5 and System Prompts

[tests/test_language_config.py](../tests/test_language_config.py) covers:

- German default without a configuration file
- preservation of the previous German voices and codes
- explicit U.S. English values
- atomic persistence and file permissions
- idempotent initialization
- rejection of unknown languages
- status output without unintentionally creating a file
- unchanged German runtime TTS values
- U.S. English runtime TTS values
- explicit voice and prompt overrides
- language-dependent selection of German and English system prompts
- English number words for isolated chapter numbers
- English chapter pauses in regular and enhanced SSML paths
- unchanged parameterless RapidOCR constructor for German
- English PP-OCRv5 Mobile model selection
- separate engine caches for German and English
- language propagation into orientation tests and page recognition
- `ocr_language` and OCR line metadata in the report
- unchanged German summary prompts and cache compatibility
- U.S. English section, progress, book, and shortening prompts
- language in persistent and temporary summary metadata
- language-dependent summary cache validation
- persistent language binding for new NFC books
- German migration of legacy books without a language field
- rejection of mixed OCR, page, summary, and TTS data
- English integration test from capture image through en-US TTS handoff

The real quality and runtime comparison using English book pages on the
Raspberry Pi remains an open practical verification task.
