# Control Panel Architecture

Last reviewed: `2026-08-01`

Deutsche Fassung: [Bedienpanel-Architektur](../docs_DE/CONTROL_PANEL_ARCHITECTURE.md)

## Goal

The ABR device's control logic is designed to run continuously on the
`Raspberry Pi 5` while:

- monitoring the buttons and `EC11` at all times
- separating hardware events from application logic
- remaining responsive during capture, OCR, TTS, and NFC operations

## Implemented Structure

The current Raspberry Pi path consists of four clearly separated layers:

1. `GPIO backend`
   - direct GPIO access through `RPi.GPIO`, based on `rpi-lgpio`
   - test fallback: `pinctrl`
2. `FrontPanelMonitor`
   - button polling in a long-lived thread
   - GPIO edge interrupts for both EC11 channels with `rpi-gpio`
   - button debouncing
   - `EC11` decoding
   - hardware-event generation only
3. `Action Router`
   - translates hardware events into application actions
   - also detects the three-button combination that opens the book deletion
     dialog
4. `Runtime Controller`
   - processes actions
   - controls jobs, audio, book context, and error paths

## EC11 Interrupts and Button Polling

With the production `rpi-gpio` backend, the EC11 uses edge interrupts on
channels A and B. The callback reads both signal levels as one snapshot and
performs only time-critical, non-blocking work:

- update the quadrature decoder
- change the thread-safe target volume held in memory
- enqueue a regular encoder event for logging and mixer synchronization

The interrupt does not start `amixer`, audio, or any other subprocesses. This
prevents long callback execution times. Mechanical buttons continue to use
the proven polling and debounce mechanism. If only `pinctrl` is available,
the encoder also continues to work through polling; the monitor thread then
updates the target-volume variable directly.

- buttons: polling with debounce
- encoder: edge interrupts with quadrature decoding and a polling fallback
- application logic: still runs after event translation; only the atomic
  target value is changed inside the callback

## Polling Fallback

The monitor uses two timing ranges:

- idle: `2.0 ms`
- during encoder activity: `0.5 ms`
- `encoder_active_hold_ms`: `25 ms`
- button debounce: `25 ms`

These short intervals apply to button snapshots and the encoder fallback.
When GPIO interrupts are active, encoder levels are not decoded again through
the polling path.

## Current Control Assignments

### `Start / Stop / NFC`

- starts the real `capture -> image preparation -> OCR -> page ingest` run
- stops an active foreground job
- stops active page playback
- also stops a heartbeat-only waiting state

### `EC11`

- changes the volume directly
- remains operational during page and system-audio playback, including
  `bing.wav`
- the interrupt updates only the target value; mixer access, logging, and
  other subprocesses continue to run outside the callback
- WAV playback itself checks the target value block by block; buffering and
  underrun protection are described in
  [CONTROL_RUNTIME_ARCHITECTURE.md](CONTROL_RUNTIME_ARCHITECTURE.md)

### `EC11 button`

- currently used in production only by the book deletion dialog

### Three-button combination

Simultaneously pressing:

- `Start / Stop / NFC`
- `Book summary`
- `Chapter/latest-pages summary`

opens the book deletion dialog.

## Production Summary Buttons

### `Chapter/latest-pages summary`

- first plays `kapitel_zusammenfassen`
- then starts a `bing` heartbeat until audio playback begins
- first assembles any sections that can now be completed, then examines the
  text from the persistent open-section boundary
- combines open text with the most recent available section summary to create
  a temporary recap
- before the first completed section, summarizes the open text by itself
- does not persist this temporary recap
- when there is no open text, continues to retrieve the latest available
  section summary and can generate or refresh it through Gemini as needed

### `Book summary`

- first plays `buch_zusammenfassen`
- then starts a `bing` heartbeat until audio playback begins
- creates an up-to-date “story so far” recap from all available section
  summaries

### Missing Summary Content

- the runtime plays `keine_zusammenfassung` only when neither a completed
  section nor open text is available

## Relevant Files

- [abr/hardware/control_panel.py](../abr/hardware/control_panel.py)
- [abr/control/frontpanel.py](../abr/control/frontpanel.py)
- [abr/control/runtime.py](../abr/control/runtime.py)
- [hardware/control_panel_service.py](../hardware/control_panel_service.py)

## Next Practical Improvements

At the control-panel level, the next useful work is no longer basic wiring but
refinement and operational readiness:

1. Continue testing the summary heartbeat and error messages on the actual Pi.
2. Add status or telemetry events for section and summary processing.
3. Add `systemd` startup for the runtime service at a later stage.
