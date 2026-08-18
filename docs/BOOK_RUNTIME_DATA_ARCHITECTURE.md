# Book Runtime and Data Architecture

Last reviewed: `2026-08-18`

Deutsche Fassung: [Laufzeit- und Datenarchitektur für Bücher](../docs_DE/BOOK_RUNTIME_DATA_ARCHITECTURE.md)

## Purpose

This document describes persistent book data and the processing path from NFC
identification to speakable pages, synthetic sections, and summaries.

The principal components are:

- `BookSessionResolver`
- `BookStore`
- `PageIngestor` and `PageIngestService`
- `ChapterAssembler`
- `SummaryManager`
- `SummaryService` as an optional asynchronous helper

## Core design

The runtime separates volatile state—inputs, active jobs, and audio—from
persistent book state. All persistent data for a book resides below
`library/<tag_id>/`.

The primary ISO14443A NFC tag is the book's primary key. Additional ISO15693
IDs may be associated with the same book as aliases. A book is also
permanently bound to the active `de` or `en` language profile when it is first
ingested. Legacy `book.json` files without a `language` field are treated as
German and are updated on the next German access. Mixed-language book, OCR,
page, chapter, or summary data is rejected.

## Per-book directory structure

```text
library/
  <tag_id>/
    book.json
    iso15693_tag_ids.txt
    state/
      chapter_assembler_state.json
      pending_right_tail_fragment.json
    scans/
      <scan_id>/
        manifest.json
    pages/
      0008.json
      0009.json
      page_1.json
    chapters/
      chapter_0001/
        chapter.json
        text.txt
    summaries/
      chapter_0001_summary.json
      book_so_far_summary.json
```

- Pages with a detected page number use a zero-padded four-digit filename.
  Otherwise, the sanitized `page_id` is used.
- `iso15693_tag_ids.txt` contains one alias per line. If only a known
  ISO15693 tag is detected, new data continues to be stored in the associated
  ISO14443A book directory.
- JSON and text files are replaced atomically through a temporary file.

## Persistent data objects

### `BookRecord` in `book.json`

- `tag_id`, `created_at`, and `last_seen_at`
- optional bibliographic fields `title` and `author`
- `language`: persistent `de` or `en` book profile

### `ScanRecord` in `scans/<scan_id>/manifest.json`

- `scan_id`, `created_at`, and `session_dir`
- optional `capture_dir`, `ocr_dir`, and `report_path`
- `left_page_id` and `right_page_id`
- metadata including OCR language, orientation, and pipeline timings

The stored paths refer to runtime artifacts outside the book directory and may
become historical after those artifacts are cleaned up. The semantic page
records remain independent of them.

### `PageRecord` in `pages/<key>.json`

- identity and origin: `page_id`, `scan_id`, `created_at`, `side`
- content: `clean_text`, `speak_text`
- structure: `page_number`, `chapter_number`, `chapter_heading`, and
  `chapter_markers[]`
- page transition: `tail_fragment`
- provenance and diagnostics: `source_report_path` and `metadata`

`clean_text` is the semantically cleaned, source-faithful text. `speak_text`
is prepared for TTS, so the two may intentionally differ. `metadata.language`
records the active language profile.

### `ChapterRecord` in `chapters/<chapter_id>/chapter.json`

- `chapter_id`, `created_at`, `completed_at`, and `text_path`
- `page_ids`, `page_numbers`, `start_page`, and `end_page`
- optional detected `chapter_number` and `chapter_heading`
- optional `summary_path`
- metadata describing start, end, and next boundaries, boundary type, page
  span, and language

The assembled section text is stored alongside the record in `text.txt`.

### `SummaryRecord` in `summaries/*.json`

- `summary_id`, `summary_type`, `updated_at`, and `text`
- `source_chapter_ids`, `model_name`, and `metadata`

Section summaries and the book-so-far summary are persisted. A temporary
summary of the open section exists in memory only.

## Page ingestion

`PageIngestor` first verifies that the OCR report, active language profile,
and stored book agree. It then performs semantic post-processing:

- detects page numbers and infers one missing number from the opposite page
  of a complete spread using `-1` or `+1`
- filters footer artifacts in the page-number area
- detects markers such as `Chapter X`, isolated chapter numbers, heading-only
  pages, and multiple markers on one page
- removes the page number from `clean_text` and `speak_text`
- renders chapter numbers as cardinal words in `speak_text`
- repairs hyphenation within a page and across page boundaries
- joins letter-spaced sequences of at least three letters
- converts short all-uppercase headings to title-style capitalization for
  TTS only and treats them as separate paragraphs
- carries paragraph boundaries over from OCR `layout_blocks`
- detects incomplete sentence tails and moves them across page boundaries
- prevents short parenthesized OCR artifacts containing digits, such as
  `(r9or)`, from being propagated as sentence tails

German `speak_text` currently applies two pronunciation exceptions: `Dr.` →
`Doktor` and `Notre-Dame` → `Notre Damm`. `clean_text` and English books are
unchanged. Existing pages are not migrated retroactively; they receive the
new processing only when ingested again.

### Missing page numbers

If no number can be determined, `page_number` remains `null` and the filename
is derived from `page_id`. An early-ingested single left page does not infer
its number from older records; it only consumes a previously persisted right
sentence tail.

### Chapter markers

`chapter_markers[]` is authoritative and may contain multiple markers.
`chapter_number` and `chapter_heading` mirror only the first marker for
compatibility. A heading-only page can be retained as a
`heading_only_page`.

### Sentence tails and page transitions

`tail_fragment` stores an incomplete sentence tail:

- A left-page tail is removed from early left-page playback and moved to the
  right page of the same spread.
- A right-page tail is prepended to the next left page and also persisted in
  `state/pending_right_tail_fragment.json`.
- If the right page has no tail, the pending state is actively cleared.

## Audio playback

The runtime reads `speak_text`, not raw OCR text. SSML pauses are generated at
playback time and are not stored in page JSON files.

The `google-standard-enhanced` backend uses:

- `900 ms` after a completed sentence within a paragraph
- `2000 ms` at the end of a paragraph
- only the sentence pause after a fully enclosed line of dialogue, even if a
  new paragraph follows in the printed book
- `1350 ms` after moderately emphasized headings normalized from uppercase
  and after chapter announcements
- `700 ms` after ordinary short headings

If OCR produces a valid report but no speakable page, the `PageRecord`s are
still saved. Instead of page text, the runtime plays either
`system_audio/messages/de/empty_page.wav` or
`system_audio/messages/en/empty_page.wav`, according to the language profile,
and completes the job cleanly.

## Section assembly

`ChapterAssembler` operates on persisted `PageRecord`s:

1. It starts at the persistent boundary in
   `state/chapter_assembler_state.json`.
2. Between pages 10 and 20, it ends a section at the first detected chapter
   boundary.
3. If no such boundary exists, it uses the last complete paragraph on page
   20.
4. The next boundary may be inside a page and is persisted with an offset.
5. It writes a `ChapterRecord` and `text.txt` after verifying consistent book
   and page languages.

`collect_pending_content()` additionally returns text from the open boundary
through the newest page without persisting a section.

## Summaries

By default, `SummaryManager` uses `gemini-3.5-flash` through Google Cloud and
the same ADC/service-account mechanism as the other Google Cloud operations.

- Target lengths are expressed in text pages; one target page equals 250
  words.
- The class and command-line defaults are `1.5` pages for both section and
  book summaries. The shipped systemd unit currently overrides both values
  with `0.75` pages.
- If output exceeds the word target by more than ten percent, a shortening
  pass is run. Output that remains too long is not cached.
- Metadata records target length, word counts, policy version, token budget,
  completion state, and language.
- Old caches are regenerated when the target length or language changes.
- The book summary is also regenerated when the chapter list or the content
  or update time of a section summary changes. A SHA-256 fingerprint tracks
  those inputs.
- If Gemini returns no complete text because of an output limit, the request
  is retried once without `maxOutputTokens`.

After writing a new section, the production runtime immediately generates its
summary and updates `book_so_far_summary.json` when needed.

### Temporary summary of the open section

The chapter/latest-pages button first assembles all sections that can now be
completed, then collects open text from the persisted boundary:

- With no open text, the latest persistent section summary is loaded or
  generated.
- With open text, `summarize_chapter_progress()` combines the latest
  persistent section summary with the new text.
- Before the first completed section, the open text is the only source.

The resulting `temporary_chapter_progress` record is passed directly to audio
playback and is not persisted. Its metadata includes `pending_page_ids`,
`pending_page_numbers`, `pending_text_characters`, and `temporary=true`.

`SummaryService` still provides a testable asynchronous queue, but it is not
the primary path in the production `hardware/control_panel_service.py`.

## Open validation and extension work

- Validate section heuristics with more real-world books.
- Tune prompt length and model choice using practical results.
- Add telemetry or status events for section and summary processing if
  needed.

## Relevant files

- [abr/book/models.py](../abr/book/models.py)
- [abr/book/store.py](../abr/book/store.py)
- [abr/book/session.py](../abr/book/session.py)
- [abr/book/page_ingestor.py](../abr/book/page_ingestor.py)
- [abr/book/chapter_assembler.py](../abr/book/chapter_assembler.py)
- [abr/book/summary_manager.py](../abr/book/summary_manager.py)
- [abr/control/runtime.py](../abr/control/runtime.py)
- [hardware/control_panel_service.py](../hardware/control_panel_service.py)
- [hardware/page_ingest_debug.py](../hardware/page_ingest_debug.py)
- [deploy/abr-control-panel.service](../deploy/abr-control-panel.service)
