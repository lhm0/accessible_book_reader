# Control Runtime Architecture

Last reviewed: `2026-07-11`

Deutsche Fassung: [Control-Runtime-Architektur](../docs_DE/CONTROL_RUNTIME_ARCHITECTURE.md)

## Purpose

This document describes the currently implemented runtime architecture of the
ABR device on the `Raspberry Pi 5`.

Book, page, section, and summary logic is documented separately in
[BOOK_RUNTIME_DATA_ARCHITECTURE.md](BOOK_RUNTIME_DATA_ARCHITECTURE.md).

## Main Components

The runtime currently consists of:

1. `FrontPanelMonitor`
2. `Action Router`
3. `RuntimeController`
4. `ForegroundJobManager`
5. `PageIngestService`
6. `PageAudioPlayer`
7. `SystemAudio` worker
8. `AudioVolumeController`

## Core Design

GPIO monitoring is strictly separated from long-running work. Capture, OCR,
TTS, and audio playback do not block the front-panel path.

Two state dimensions are relevant in parallel:

- work state
- audio state

This separation is implemented in the current runtime.

## Runtime States

### Work State

Implemented states:

- `idle`
- `capture_ocr_running`
- `book_summary_running`
- `chapter_summary_running`
- `delete_book_confirmation`
- `cancelling_work`
- `error`

The two summary states are implemented as foreground jobs. The front panel
and audio-stop controls remain responsive while a summary job is running.

### Audio Layers

There are two distinct audio paths:

- `SystemAudio`
  - serial queue
  - warnings are intended to play in full
- `PageAudioPlayer`
  - used for page playback
  - explicitly cancellable

This separation is deliberate and significant to the application behavior.

Both paths use the same local playback implementation in
`abr/audio_playback.py` and share the same process-wide playback lock. On the
Raspberry Pi, `aplay` is started without an explicit ALSA `-D` argument. The
machine must therefore define the global `default` device in
`/etc/asound.conf` as a `plug` PCM targeting `hw:CARD=MAX98357A,DEV=0`. The
symbolic card name is deliberately more stable than `card 0`, `card 1`, or
`card 2`, whose numbers can change with HDMI and driver initialization order.
The `plug` conversion is required because the hardware path expects two
channels while generated WAV files may be mono.

## Foreground Job Rule

The following rules apply:

- exactly one foreground job at a time
- the production capture job follows
  `capture -> image preparation -> OCR -> page ingest`
- audio may run in parallel
- there is no hidden job queue

## Start and Stop Semantics

### `Start / Stop / NFC`

When `idle`:

- read the NFC tag
- establish the book context
- play `bing`
- start the heartbeat
- start `capture -> image preparation -> OCR -> page ingest`

While a foreground job is running:

- request cancellation
- play `abbruch`

During page playback:

- stop playback immediately
- play `abbruch`

During a heartbeat-only waiting state:

- stop the heartbeat
- discard a later `page-ingest` result
- play `abbruch`

## Heartbeat

A separate heartbeat thread represents the start/wait state.

Current behavior:

- default interval: `5s`
- signal: `bing`
- stops when:
  - the first page audio is ready
  - an error occurs
  - Stop is pressed
  - page ingest returns an empty result

This path explicitly prevents an endless heartbeat when OCR and ingest are
formally successful but produce no speakable pages. In this case,
`empty_page.wav` is played. Other error paths continue to use `fehler.wav`.

## System Audio

Pre-generated system prompts are stored by language under
`system_audio/messages/de/` and `system_audio/messages/en/`. At startup,
`control_panel_service.py` reads the active language profile and gives the
runtime controller only the corresponding directory. A language change with
`abr-language` therefore takes effect after restarting
`abr-control-panel.service`.

Logical filenames are identical in both language directories. Every new
system prompt must be provided in both languages. A missing prompt is not
replaced from another language directory; it is logged as a runtime error
with the fully resolved path.

Prompts include:

- `bing`
- `neues_buch`
- `abbruch`
- `buch_loeschen`
- `buch_geloescht`
- `buch_nicht_erkannt`
- `fehler`
- `kapitel_zusammenfassen`
- `buch_zusammenfassen`
- `keine_zusammenfassung`

These prompts use their own queue and should not be interrupted by page
playback.

## Page Audio

`PageAudioPlayer`:

- ignores pages with empty `speak_text`
- plays available pages in sequence
- starts only after the complete left-page audio is available
- processes image preparation, OCR, `PageIngestor`, and TTS for the right page
  while the left page is playing
- can be stopped immediately with `Start / Stop`

To reduce waiting time, both pages are still photographed first. Only then
are they processed left before right. This reduces the time from `Start` to
first audio without requiring the book to remain on the scanner.

Chapter announcements:

- are handled as SSML at runtime for `google` and `say`
- have a `1350ms` pause before `Chapter ...`
- have another `1350ms` pause afterward
- short, fully uppercase OCR headings are converted to readable case, treated
  as separate paragraphs, and followed by the same `1350ms` pause

## Volume

`AudioVolumeController`:

- currently uses `10` levels
- covers the range `20% .. 100%`
- prefers software volume control when no usable ALSA mixer is available
- also affects active playback

Volume has a thread-safe target value. An EC11 step changes it directly from
the GPIO edge callback through `request_delta()`; this path deliberately does
not start a mixer subprocess. The regular encoder event processed later
synchronizes the ALSA mixer when necessary and writes the log entry.

Both `PageAudioPlayer` and `SystemAudio` pass
`AudioVolumeController.current_percent` to local WAV playback as a
`volume_provider`. The `aplay` streaming path reads this value again for each
PCM block. A volume change therefore also takes effect during a synchronous
`bing.wav`, even though the main runtime thread is blocked until the sound
finishes.

Dynamically scaled WAV files are streamed to `aplay` as PCM and require
headroom for short scheduler delays on the Pi. The permitted PCM lead is
`250ms`, with a `300ms` ALSA buffer and a `50ms` period. The previous `100ms`
headroom could cause a short buffer underrun and audible interruption in the
roughly four-second `bing.wav` on a busy system. The larger headroom keeps
playback continuous. Every scaled PCM block is also flushed to the pipe
immediately instead of accumulating multiple blocks in Python's write buffer,
so volume changes remain perceptible with well under one second of latency.

## Usage Statistics

The production `control_panel_service` creates a `UsageStatisticsStore` below
the configured `library-root` and passes it to `RuntimeController`.

The runtime records per book:

- successfully ingested pages; `scan_id` plus `page_id` prevent double
  counting during incremental ingest of the same page
- actual duration of each page and summary audio around the blocking playback
  call, including playback stopped early
- starts of the chapter/latest-pages summary
- starts of the story-so-far summary

System audio and signal sounds use a separate playback path and do not count
as reading time. Statistics errors are logged but do not propagate into the
device workflow.

Persistent statistics are written atomically and protected against parallel
access from the runtime, audio thread, and report process. Reporting periods
use `Europe/Berlin` and run from `04:00` to `04:00`. Delivery, archiving, and
systemd operation are described in
[USAGE_STATISTICS.md](USAGE_STATISTICS.md).

## Book Deletion Dialog

Implemented in the runtime controller:

1. Press the three-button combination.
2. Read NFC.
3. If no tag is detected:
   - play `buch_nicht_erkannt`
4. If a tag is detected:
   - play `buch_loeschen`
   - confirm only with the `EC11` button
   - cancel with a function button
5. Result:
   - `abbruch` or `buch_geloescht`

## Implemented Scope

The runtime coordinates:

- front panel
- NFC
- capture and OCR
- heartbeat
- page ingest
- page playback
- volume
- book deletion
- section assembly after every successful page ingest
- immediate summaries for newly completed sections through `SummaryManager`
- button jobs for the latest section summary and story-so-far summary
- a temporary current recap combining the latest persistent section summary
  with the still-open section text

Important behavior of the summary buttons:

- chapter and book summaries start with a preceding system prompt
- the same `bing` heartbeat used by the Start button then runs
- before playing a chapter/latest-pages summary, `ChapterAssembler` completes
  any newly available sections and reads text from its persistent open
  boundary
- if open text exists, `SummaryManager.summarize_chapter_progress()` combines
  it with the latest section summary into an in-memory-only `SummaryRecord`;
  before the first section, open text is the only source
- without open text, the existing path to the latest persistent section
  summary remains unchanged
- the heartbeat stops only after summary text has been enqueued for audio
- `keine_zusammenfassung` is played only when there is neither a completed
  section nor open text

The temporary path is explicitly visible in the log:

```text
Temporaere Kapitelzusammenfassung wird aus dem letzten Abschnitt und N Zeichen offenem Text erzeugt.
Temporaere Kapitelzusammenfassung bereit; sie wird nicht gespeichert.
```

Before the first completed section, the first message states that only open
text is used. The audio label starts with
`kapitel-zusammenfassung-temporaer`; persistent section summaries keep their
existing labels.

## Remaining Work

1. Verify summary length control during real operation on the Pi.
2. Derive explicit `chapter_completed` or `summary_completed` events if
   needed.
3. Improve reporting for Google Cloud ADC, project configuration, and network
   errors where useful.

## Relevant Files

- [abr/control/runtime.py](../abr/control/runtime.py)
- [abr/control/frontpanel.py](../abr/control/frontpanel.py)
- [abr/control/audio_volume.py](../abr/control/audio_volume.py)
- [abr/book/page_ingestor.py](../abr/book/page_ingestor.py)
- [hardware/control_panel_service.py](../hardware/control_panel_service.py)

## Asynchronous NFC Query and Book Orientation

For the PN5180 gateway, the Start path uses a two-stage sequence:

1. Immediately after pressing `Start / Stop / NFC`: `STATUS_START`
2. Capture both camera images.
3. Immediately before image preparation and OCR: `STATUS_FETCH`

The subsequent selection logic is:

- `ISO14443A` is the primary book key.
- Reader 2 detecting ISO14443A reports orientation 1.
- Reader 1 detecting ISO14443A reports orientation 2.
- With orientation 1, the captured left/right assignment remains unchanged.
- With orientation 2, the two page files are swapped immediately after
  `STATUS_FETCH` and before image preparation.
- `case/right.jpg` is then rotated by 180 degrees. This makes the correction
  visible under `rectified images` in the camera test server as well.
- OCR preprocessing performs no further page rotation.
- If only ISO15693 is available, the book is resolved through existing
  `iso15693_tag_ids.txt` files and uses the Reader 2 orientation by default.

The ISO15693-only orientation can be changed with
`--iso15693-only-orientation reader1|reader2`.

## Isolated Neural2 Test Path

Production page playback remains:

- backend name `google`
- class `GoogleCloudTTSBackend`
- voice `de-DE-Standard-H`
- the default without an additional CLI option

The opt-in `google-standard-enhanced` path also uses
`GoogleCloudTTSBackend` and `de-DE-Standard-H`. Only runtime preparation
differs: it structures paragraphs and sentences using SSML, retains the
chapter pause, and moderately emphasizes short headings. In a question, the
complete final word is marked with `<prosody pitch="+3st">`.

After each sentence within a paragraph, it inserts
`<break time="900ms"/>`. The final sentence of a paragraph instead receives
`<break time="2000ms"/>`; the two pauses are not added together. In addition
to blank lines produced during page ingest, the renderer recognizes single
line breaks after `.` or `?` as a fallback. Closing quotation marks may occur
between the punctuation and line break. If the preceding paragraph is a line
of dialogue fully enclosed in `"..."`, `»...«`, or `„...“`, the following
paragraph boundary is treated as a sentence boundary and receives only a
`900ms` pause.

A validation step ensures that word order is unchanged. If validation fails,
the previous SSML preparation is used. The default `google` path remains
untouched.

The Neural2 experiment is separate:

- backend name `google-neural2`
- class `GoogleNeural2TTSBackend`
- default voice `de-DE-Neural2-H`
- enabled only with `--page-tts-backend google-neural2`

Both paths retain the existing SSML chapter pauses. Omitting the option or
using `--page-tts-backend google` switches back to the previous path without
migration or data changes.

A third, separately isolated experimental path also exists:

- backend name `google-gemini-flash`
- class `GoogleGeminiFlashTTSBackend`
- model `gemini-2.5-flash-tts`
- default voice `Charon`
- separate fields for spoken text and the audiobook-style prompt
- enabled only with `--page-tts-backend google-gemini-flash`

Gemini TTS receives plain text instead of SSML. The configured speed is added
to the prompt as a natural-language pacing instruction. Text and prompt are
checked separately against their respective `4000`-byte limits.

From this path as well, `--page-tts-backend google` or omitting the option
returns directly to `de-DE-Standard-H` without a data migration.

## Protection Against Incorrect Page Order

`RuntimeController` maintains volatile per-book state containing:

- page numbers from the most recently accepted scan
- scan ID, so the incremental left and right ingest results are treated as
  one spread
- confirmation flags for backward page turns and page repetition
- suppressed scan IDs, so the second partial result from a warned scan is not
  played either

If the new scan overlaps the previous spread, `repeat_page.wav` is played. If
its minimum page number is lower, `wrong_direction.wav` is played. In either
case, the pages are not queued for playback. A new scan consumes the matching
confirmation flag and is allowed to pass the rejected check once. The
backward-confirmation flag guarantees playback of the new scan. Scans without
page numbers are exempt from these checks.

Unlike general system prompts, these two warnings are played synchronously in
the page-ingest callback. The warning therefore finishes before the result is
discarded. The runtime logs `Seitenfolge-Hinweis startet` and
`Seitenfolge-Hinweis abgeschlossen`; a playback error instead identifies the
missing or unreadable audio path.

The incremental path has a synchronization point between left-page OCR and
the start of right-page processing: `PageIngestService.submit` returns a
completion event that the capture runner waits for. A page-order warning calls
`ForegroundJobManager.cancel_current_job()`. The waiting runner observes the
cancel event, raises `ForegroundJobCancelled`, and does not start right-page
OCR. The subsequent `CANCELLED` job event resets the runtime to `IDLE`.

## Segmenting Long Summary Audio

For Google backends, `PageAudioPlayer.enqueue_text()` checks the byte size of
the actual rendered input, including SSML for `google-standard-enhanced`.
Summaries are split above `900` bytes; `3800` bytes remains the general Google
safety limit. Text is split at complete sentence boundaries whenever
possible. Only a single overlong sentence falls back to word-based splitting.

All segments are queued as separate utterances of the same generation and are
synthesized and played in order by the existing prefetch/playback worker.
Labels range, for example, from `was-bisher-geschah:1/3` through `:3/3`. A
long summary therefore cannot end up as one oversized Google TTS request.

The summary intro and first `bing` are played synchronously before the summary
job starts. As soon as `PageAudioPlayer` becomes active, the system-audio
worker discards queued heartbeat entries. This prevents an already released
heartbeat from waiting behind summary playback on the global audio lock.

Before reusing `book_so_far_summary.json`, `SummaryManager` calculates a
SHA-256 fingerprint from the IDs, `updated_at` values, and text of the section
summaries used. The previous check of chapter IDs alone could not detect a
stale, short book-summary cache. The summary is regenerated when the
fingerprint is absent or different. The runtime log also records the exact
summary path and the character count of the text passed to audio playback.

## Completeness of Gemini Summaries

A `generateContent` response must not be stored merely because it already
contains text. If a candidate reports `finishReason=MAX_TOKENS`, the text is
incomplete and may even end in the middle of a word. `GeminiSummaryBackend`
discards such partial text and retries once without the `maxOutputTokens`
derived from `target-pages`. Only a response that was not truncated is
returned. A second truncated response produces an error instead of a damaged
cache file.

New section and book summaries include `generation_complete=true` in their
metadata. Legacy files without this marker are no longer accepted as valid
cache entries and are regenerated once on the next summary request. Error
details include `promptTokenCount`, `candidatesTokenCount`,
`thoughtsTokenCount`, and `totalTokenCount` when Vertex AI provides them.

The semantic summary length is no longer controlled by the technical token
limit. Instead, `target-pages` is converted into a concrete word limit using
`250` words per page. The first Gemini request states this limit in its prompt
and receives up to `2048` technical output tokens. If the result exceeds the
target by more than ten percent, a second Gemini request is used to shorten
it. If it remains above the tolerance, it is not saved. JSON metadata records
the target word count and the word counts before and after any shortening
pass.
