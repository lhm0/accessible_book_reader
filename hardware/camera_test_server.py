#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import json
import socket
import sys
import threading
import time
from http import server
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CAPTURE_SESSION_DIR = REPO_ROOT / "captures" / "latest"
DEFAULT_OCR_DEBUG_DIR = REPO_ROOT / "runs" / "latest" / "debug"


LIVE_PAGE_TEMPLATE = """<!doctype html>
<html lang="de">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>ABR Kamera-Test</title>
    <style>
      :root {{
        color-scheme: dark;
        --bg: #111318;
        --panel: #1b1f28;
        --border: #3a4152;
        --text: #f5f7fb;
        --muted: #a7b0c4;
        --accent: #9dd7ff;
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        font-family: "Iowan Old Style", "Palatino Linotype", serif;
        background:
          radial-gradient(circle at top, #1a2233 0%, var(--bg) 58%),
          var(--bg);
        color: var(--text);
      }}
      main {{
        width: min(1180px, 100%);
        margin: 0 auto;
        padding: 24px;
      }}
      h1 {{
        margin: 0 0 12px;
        font-size: clamp(2rem, 3vw, 3rem);
      }}
      p {{
        margin: 0 0 16px;
        color: var(--muted);
        line-height: 1.5;
      }}
      .panel {{
        border: 1px solid var(--border);
        border-radius: 18px;
        overflow: hidden;
        background: rgba(27, 31, 40, 0.92);
        box-shadow: 0 24px 90px rgba(0, 0, 0, 0.35);
      }}
      .meta {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
        gap: 12px;
        padding: 18px 20px;
        border-bottom: 1px solid var(--border);
      }}
      .meta div {{
        padding: 12px 14px;
        border-radius: 12px;
        background: rgba(255, 255, 255, 0.04);
      }}
      .meta strong {{
        display: block;
        margin-bottom: 6px;
        color: var(--accent);
      }}
      .viewer {{
        position: relative;
        background: #050608;
      }}
      img {{
        display: block;
        width: 100%;
        height: auto;
        background: #000;
      }}
      .crosshair {{
        position: absolute;
        inset: 0;
        pointer-events: none;
        opacity: 0;
        transition: opacity 140ms ease;
      }}
      .crosshair::before,
      .crosshair::after {{
        content: "";
        position: absolute;
        background: rgba(255, 96, 96, 0.92);
        box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.45);
      }}
      .crosshair::before {{
        top: 50%;
        left: 50%;
        width: min(10vw, 84px);
        height: 2px;
        transform: translate(-50%, -50%);
      }}
      .crosshair::after {{
        top: 50%;
        left: 50%;
        width: 2px;
        height: min(10vw, 84px);
        transform: translate(-50%, -50%);
      }}
      .viewer[data-crosshair-visible="true"] .crosshair {{
        opacity: 1;
      }}
      .toolbar {{
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 12px;
        padding: 14px 20px 0;
      }}
      .toggle {{
        display: inline-flex;
        align-items: center;
        gap: 10px;
        color: var(--text);
        cursor: pointer;
        user-select: none;
      }}
      .toggle input {{
        width: 18px;
        height: 18px;
        accent-color: #ff6666;
      }}
      .hint {{
        padding: 14px 20px 20px;
        font-size: 0.95rem;
      }}
      code {{
        color: var(--text);
      }}
    </style>
  </head>
  <body>
    <main>
      <h1>ABR Kamera-Test</h1>
      <p>
        Livebild von Kamera <code>{camera_index}</code>. Der Stream laeuft mit der
        konfigurierten Vollaufloesung <code>{resolution}</code>; die Aktualisierung
        erfolgt so schnell, wie Kamera, JPEG-Encoding und Netzwerk es zulaesst.
      </p>
      <section class="panel">
        <div class="meta">
          <div>
            <strong>Kamera</strong>
            <span id="camera-model">{camera_model}</span>
          </div>
          <div>
            <strong>Aufloesung</strong>
            <span id="resolution">{resolution}</span>
          </div>
          <div>
            <strong>Letzte gemessene FPS</strong>
            <span id="fps">{fps}</span>
          </div>
          <div>
            <strong>Frames seit Start</strong>
            <span id="frame-count">0</span>
          </div>
        </div>
        <div class="toolbar">
          <label class="toggle" for="crosshair-toggle">
            <input id="crosshair-toggle" type="checkbox" {crosshair_checked}>
            <span>Fadenkreuz einblenden</span>
          </label>
        </div>
        <div class="viewer" id="viewer" data-crosshair-visible="{crosshair_visible}">
          <img src="/stream.mjpg" alt="Livebild der Kamera">
          <div class="crosshair" aria-hidden="true"></div>
        </div>
        <p class="hint">
          Direktlink fuer Snapshot: <code>/snapshot.jpg</code>.
          Statusdaten: <code>/status.json</code>.
        </p>
      </section>
    </main>
    <script>
      function syncCrosshairToggle() {{
        const toggle = document.getElementById("crosshair-toggle");
        const viewer = document.getElementById("viewer");
        viewer.dataset.crosshairVisible = toggle.checked ? "true" : "false";
      }}

      async function refreshStatus() {{
        try {{
          const response = await fetch("/status.json", {{ cache: "no-store" }});
          const status = await response.json();
          document.getElementById("fps").textContent = status.fps.toFixed(1);
          document.getElementById("frame-count").textContent = status.frame_count;
          document.getElementById("camera-model").textContent = status.camera_model;
          document.getElementById("resolution").textContent = status.resolution;
        }} catch (_error) {{
          document.getElementById("fps").textContent = "unbekannt";
        }}
      }}

      document.getElementById("crosshair-toggle").addEventListener("change", syncCrosshairToggle);
      syncCrosshairToggle();
      refreshStatus();
      window.setInterval(refreshStatus, 1000);
    </script>
  </body>
</html>
"""


OCR_STAGE_FILES = {
    "gray": "01_gray.png",
    "enhanced": "02_enhanced.png",
    "sharpened": "03_sharpened.png",
    "binary": "04_binary.png",
    "oriented": "05_oriented.png",
}

OCR_OVERLAY_STAGE_FILE = "06_ocr_overlay.png"
OCR_OVERLAY_LEGACY_STAGE_FILE = "06_tesseract_words.png"
REVIEW_SOURCE_RAW = "raw"
REVIEW_SOURCE_RECTIFIED = "rectified"
REVIEW_SOURCE_ENHANCED = "enhanced"
REVIEW_SOURCE_OCR_OVERLAY = "ocr-overlay"
REVIEW_SOURCE_ORDER = (
    REVIEW_SOURCE_RAW,
    REVIEW_SOURCE_RECTIFIED,
    REVIEW_SOURCE_ENHANCED,
    REVIEW_SOURCE_OCR_OVERLAY,
)
REVIEW_SOURCE_LABELS = {
    REVIEW_SOURCE_RAW: "Raw Images",
    REVIEW_SOURCE_RECTIFIED: "Entzerrte Bilder",
    REVIEW_SOURCE_ENHANCED: "Enhanced Images",
    REVIEW_SOURCE_OCR_OVERLAY: "OCR Overlay",
}
REVIEW_MODE_DEFAULT_SOURCE = {
    "review": REVIEW_SOURCE_RECTIFIED,
    "capture-review": REVIEW_SOURCE_RECTIFIED,
    "ocr-review": REVIEW_SOURCE_ENHANCED,
    "ocr-words-review": REVIEW_SOURCE_OCR_OVERLAY,
}


REVIEW_PAGE_TEMPLATE = """<!doctype html>
<html lang="de">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>ABR Review</title>
    <style>
      :root {{
        color-scheme: dark;
        --bg: #101217;
        --panel: #181d27;
        --border: #384255;
        --text: #f4f7fc;
        --muted: #a8b3c6;
        --accent: #ffd36e;
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        font-family: "Iowan Old Style", "Palatino Linotype", serif;
        color: var(--text);
        background:
          radial-gradient(circle at top, #1f2736 0%, var(--bg) 58%),
          var(--bg);
      }}
      main {{
        width: min(1180px, 100%);
        margin: 0 auto;
        padding: 24px;
      }}
      h1 {{
        margin: 0 0 12px;
        font-size: clamp(2rem, 3vw, 3rem);
      }}
      p {{
        margin: 0 0 16px;
        color: var(--muted);
        line-height: 1.5;
      }}
      .panel {{
        border: 1px solid var(--border);
        border-radius: 18px;
        overflow: hidden;
        background: rgba(24, 29, 39, 0.94);
        box-shadow: 0 24px 90px rgba(0, 0, 0, 0.35);
      }}
      .source-picker {{
        display: flex;
        flex-wrap: wrap;
        gap: 12px;
        padding: 18px 20px;
        border-bottom: 1px solid var(--border);
        background: rgba(255, 255, 255, 0.02);
      }}
      .radio {{
        display: inline-flex;
        align-items: center;
        gap: 10px;
        padding: 10px 14px;
        border: 1px solid var(--border);
        border-radius: 999px;
        background: rgba(255, 255, 255, 0.04);
        cursor: pointer;
      }}
      .radio input {{
        accent-color: #ffd36e;
      }}
      .meta {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
        gap: 12px;
        padding: 18px 20px;
        border-bottom: 1px solid var(--border);
      }}
      .meta div {{
        padding: 12px 14px;
        border-radius: 12px;
        background: rgba(255, 255, 255, 0.04);
      }}
      .meta strong {{
        display: block;
        margin-bottom: 6px;
        color: var(--accent);
      }}
      .stack {{
        display: grid;
        gap: 18px;
        padding: 20px;
      }}
      figure {{
        margin: 0;
        border: 1px solid var(--border);
        border-radius: 14px;
        overflow: hidden;
        background: #040507;
      }}
      figcaption {{
        padding: 12px 14px;
        color: var(--muted);
        border-bottom: 1px solid var(--border);
      }}
      img {{
        display: block;
        width: 100%;
        height: auto;
        background: #000;
        min-height: 180px;
      }}
      .hint {{
        padding: 0 20px 20px;
        font-size: 0.95rem;
      }}
      .diag {{
        padding: 0 20px 20px;
        color: var(--muted);
        font-size: 0.95rem;
        line-height: 1.45;
      }}
      .diag strong {{
        color: var(--accent);
      }}
      code {{
        color: var(--text);
      }}
    </style>
  </head>
  <body>
    <main>
      <h1>ABR Review</h1>
      <p>
        Eine gemeinsame Review-Seite fuer Rohbilder, entzerrte Bilder,
        Enhanced-Bilder und OCR-Overlays. Die Ansicht liest standardmaessig
        aus <code>captures/latest</code> und <code>runs/latest/debug</code>
        und aktualisiert sich automatisch bei neuen Dateien.
      </p>
      <section class="panel">
        <div class="source-picker">
          {radio_controls}
        </div>
        <div class="meta">
          <div>
            <strong>Auswahl</strong>
            <span id="selected-source">{initial_source_label}</span>
          </div>
          <div>
            <strong>Status</strong>
            <span id="availability">{initial_availability}</span>
          </div>
          <div>
            <strong>Stand</strong>
            <span id="version">{initial_version}</span>
          </div>
          <div>
            <strong>Quelle</strong>
            <span id="source-dir">{initial_source_dir}</span>
          </div>
          <div>
            <strong>Capture Session</strong>
            <span id="session-name">{session_name}</span>
          </div>
          <div>
            <strong>OCR Run</strong>
            <span id="run-name">{run_name}</span>
          </div>
        </div>
        <div class="stack">
          <figure>
            <figcaption id="left-caption">{initial_left_label}</figcaption>
            <img id="left-image" src="{initial_left_src}" alt="Linkes Review-Bild">
          </figure>
          <figure>
            <figcaption id="right-caption">{initial_right_label}</figcaption>
            <img id="right-image" src="{initial_right_src}" alt="Rechtes Review-Bild">
          </figure>
        </div>
        <p class="hint">
          Statusdaten: <code>/review-status.json</code>.
        </p>
        <div class="diag">
          <strong>Pfad links:</strong> <span id="left-path">{initial_left_path}</span><br>
          <strong>Pfad rechts:</strong> <span id="right-path">{initial_right_path}</span><br>
          <strong>Fehlend:</strong> <span id="missing-paths">{initial_missing_paths}</span>
        </div>
      </section>
    </main>
    <script>
      let lastStatus = {initial_state_json};
      let currentSource = {initial_source_json};
      let currentVersion = String((lastStatus.sources[currentSource] || {{}}).version || "0");

      function selectedSourceState(status) {{
        return status.sources[currentSource] || null;
      }}

      function refreshImages() {{
        const source = selectedSourceState(lastStatus);
        const leftImage = document.getElementById("left-image");
        const rightImage = document.getElementById("right-image");
        if (!source || !source.available) {{
          leftImage.removeAttribute("src");
          rightImage.removeAttribute("src");
          return;
        }}
        leftImage.src = `/review-image/left?source=${{encodeURIComponent(currentSource)}}&version=${{encodeURIComponent(currentVersion)}}`;
        rightImage.src = `/review-image/right?source=${{encodeURIComponent(currentSource)}}&version=${{encodeURIComponent(currentVersion)}}`;
      }}

      function renderStatus(status) {{
        const source = selectedSourceState(status);
        document.getElementById("session-name").textContent = status.session_name;
        document.getElementById("run-name").textContent = status.run_name;
        document.getElementById("selected-source").textContent = source ? source.label : currentSource;
        document.getElementById("source-dir").textContent = source ? source.source_dir : "-";
        document.getElementById("version").textContent = source ? source.version : "-";
        document.getElementById("availability").textContent =
          source && source.available ? "Bilder verfuegbar" : "Noch keine Bilder";
        document.getElementById("left-caption").textContent = source ? source.left_label : "left";
        document.getElementById("right-caption").textContent = source ? source.right_label : "right";
        document.getElementById("left-path").textContent = source ? source.left_path : "-";
        document.getElementById("right-path").textContent = source ? source.right_path : "-";
        document.getElementById("missing-paths").textContent =
          source && source.missing_paths && source.missing_paths.length > 0
            ? source.missing_paths.join(" | ")
            : "keine";
      }}

      function setSource(nextSource) {{
        currentSource = nextSource;
        currentVersion = String((lastStatus.sources[currentSource] || {{}}).version || "0");
        renderStatus(lastStatus);
        refreshImages();
      }}

      async function refreshStatus() {{
        try {{
          const response = await fetch("/review-status.json", {{ cache: "no-store" }});
          const status = await response.json();
          lastStatus = status;
          if (!status.sources[currentSource]) {{
            currentSource = status.selected_source;
          }}
          const nextVersion = String((status.sources[currentSource] || {{}}).version || "0");
          const versionChanged = nextVersion !== currentVersion;
          currentVersion = nextVersion;
          renderStatus(status);
          if (versionChanged) {{
            refreshImages();
          }}
        }} catch (_error) {{
          document.getElementById("availability").textContent = "Status unbekannt";
        }}
      }}

      for (const input of document.querySelectorAll('input[name="review-source"]')) {{
        input.addEventListener("change", (event) => setSource(event.target.value));
      }}

      renderStatus(lastStatus);
      refreshImages();
      window.setInterval(refreshStatus, 1000);
    </script>
  </body>
</html>
"""

class LatestFrameBuffer:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._frame: bytes | None = None
        self._frame_count = 0
        self._fps = 0.0
        self._last_frame_time: float | None = None

    def update(self, frame: bytes) -> None:
        now = time.monotonic()
        with self._condition:
            if self._last_frame_time is not None:
                delta = now - self._last_frame_time
                if delta > 0:
                    instantaneous_fps = 1.0 / delta
                    if self._fps == 0.0:
                        self._fps = instantaneous_fps
                    else:
                        self._fps = (self._fps * 0.8) + (instantaneous_fps * 0.2)
            self._last_frame_time = now
            self._frame = frame
            self._frame_count += 1
            self._condition.notify_all()

    def wait_for_new_frame(self, last_seen: int, timeout: float = 5.0) -> tuple[int, bytes | None]:
        with self._condition:
            if self._frame_count <= last_seen:
                self._condition.wait(timeout=timeout)
            return self._frame_count, self._frame

    def snapshot(self) -> tuple[int, bytes | None, float]:
        with self._condition:
            return self._frame_count, self._frame, self._fps

    def last_frame_age(self) -> float | None:
        with self._condition:
            if self._last_frame_time is None:
                return None
            return time.monotonic() - self._last_frame_time


class StreamingOutput(io.BufferedIOBase):
    def __init__(self, frame_buffer: LatestFrameBuffer) -> None:
        super().__init__()
        self._frame_buffer = frame_buffer

    def write(self, buf: bytes) -> int:
        self._frame_buffer.update(bytes(buf))
        return len(buf)


class StreamWatchdog(threading.Thread):
    def __init__(
        self,
        frame_buffer: LatestFrameBuffer,
        stop_event: threading.Event,
        timeout_sec: float,
        ready_grace_sec: float = 10.0,
    ) -> None:
        super().__init__(daemon=True)
        self._frame_buffer = frame_buffer
        self._stop_event = stop_event
        self._timeout_sec = timeout_sec
        self._ready_grace_sec = ready_grace_sec
        self._started_at = time.monotonic()
        self.error_message: str | None = None

    def run(self) -> None:
        while not self._stop_event.is_set():
            time.sleep(0.5)
            frame_count, _frame, _fps = self._frame_buffer.snapshot()
            if frame_count == 0:
                if (time.monotonic() - self._started_at) > self._ready_grace_sec:
                    self.error_message = (
                        "Kamera liefert keine JPEG-Frames. "
                        "Bitte Kabel, Sensor und Overlay-Konfiguration pruefen."
                    )
                    self._stop_event.set()
                continue

            last_frame_age = self._frame_buffer.last_frame_age()
            if last_frame_age is not None and last_frame_age > self._timeout_sec:
                self.error_message = (
                    f"Seit {last_frame_age:.2f}s kein neues Kamerabild mehr. "
                    "Der Kamerapfad ist wahrscheinlich instabil."
                )
                self._stop_event.set()
                return


class ThreadingHTTPServer(server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def import_picamera2_runtime() -> tuple[Any, Any, Any]:
    try:
        from picamera2 import Picamera2
        from picamera2.encoders import JpegEncoder
        from picamera2.outputs import FileOutput
    except ImportError as exc:  # pragma: no cover - depends on Pi runtime
        raise RuntimeError(
            "Picamera2 ist nicht importierbar. Auf dem Raspberry Pi bitte "
            "`python3-picamera2` installieren oder dieses Skript mit `/usr/bin/python3` starten."
        ) from exc
    return Picamera2, JpegEncoder, FileOutput


def read_capture_review_state(capture_session_dir: Path) -> dict[str, Any]:
    case_dir = capture_session_dir / "case"
    metadata_path = capture_session_dir / "metadata.json"
    left_path = case_dir / "left.jpg"
    right_path = case_dir / "right.jpg"
    files = [metadata_path, left_path, right_path]
    existing = [path for path in files if path.exists()]
    available = left_path.exists() and right_path.exists()
    version = max((path.stat().st_mtime_ns for path in existing), default=0)
    session_name = capture_session_dir.name

    if metadata_path.exists():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            session_name = str(metadata.get("session_name") or session_name)
        except (json.JSONDecodeError, OSError):
            pass

    return {
        "session_name": session_name,
        "capture_session_dir": str(capture_session_dir),
        "case_dir": str(case_dir),
        "left_path": left_path,
        "right_path": right_path,
        "available": available,
        "version": version,
    }


def read_raw_review_state(capture_session_dir: Path) -> dict[str, Any]:
    raw_dir = capture_session_dir / "raw"
    metadata_path = capture_session_dir / "metadata.json"
    slot_camera_indices = {"left": 0, "right": 1}
    session_name = capture_session_dir.name

    if metadata_path.exists():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            session_name = str(metadata.get("session_name") or session_name)
            slots = metadata.get("slots") or {}
            for slot_name in ("left", "right"):
                slot_payload = slots.get(slot_name) or {}
                camera_index = slot_payload.get("camera_index")
                if isinstance(camera_index, int):
                    slot_camera_indices[slot_name] = camera_index
        except (json.JSONDecodeError, OSError):
            pass

    left_path = raw_dir / f"cam{slot_camera_indices['left']}_raw.jpg"
    right_path = raw_dir / f"cam{slot_camera_indices['right']}_raw.jpg"
    files = [metadata_path, left_path, right_path]
    existing = [path for path in files if path.exists()]
    available = left_path.exists() and right_path.exists()
    version = max((path.stat().st_mtime_ns for path in existing), default=0)

    return {
        "session_name": session_name,
        "capture_session_dir": str(capture_session_dir),
        "raw_dir": str(raw_dir),
        "left_path": left_path,
        "right_path": right_path,
        "available": available,
        "version": version,
    }


def read_ocr_review_state(ocr_debug_dir: Path, stage: str) -> dict[str, Any]:
    try:
        stage_file = OCR_STAGE_FILES[stage]
    except KeyError as exc:
        raise ValueError(f"Unbekannte OCR-Stufe: {stage}") from exc

    left_path = ocr_debug_dir / "page_1" / stage_file
    right_path = ocr_debug_dir / "page_2" / stage_file
    files = [left_path, right_path]
    existing = [path for path in files if path.exists()]
    available = left_path.exists() and right_path.exists()
    version = max((path.stat().st_mtime_ns for path in existing), default=0)
    run_name = ocr_debug_dir.parent.name if ocr_debug_dir.name == "debug" else ocr_debug_dir.name

    return {
        "run_name": run_name,
        "ocr_debug_dir": str(ocr_debug_dir),
        "stage": stage,
        "stage_file": stage_file,
        "left_path": left_path,
        "right_path": right_path,
        "available": available,
        "version": version,
    }


def read_ocr_words_review_state(ocr_debug_dir: Path) -> dict[str, Any]:
    preferred_left_path = ocr_debug_dir / "page_1" / OCR_OVERLAY_STAGE_FILE
    preferred_right_path = ocr_debug_dir / "page_2" / OCR_OVERLAY_STAGE_FILE
    legacy_left_path = ocr_debug_dir / "page_1" / OCR_OVERLAY_LEGACY_STAGE_FILE
    legacy_right_path = ocr_debug_dir / "page_2" / OCR_OVERLAY_LEGACY_STAGE_FILE

    if preferred_left_path.exists() or preferred_right_path.exists():
        left_path = preferred_left_path
        right_path = preferred_right_path
        stage_file = OCR_OVERLAY_STAGE_FILE
    else:
        left_path = legacy_left_path
        right_path = legacy_right_path
        stage_file = OCR_OVERLAY_LEGACY_STAGE_FILE

    files = [left_path, right_path]
    existing = [path for path in files if path.exists()]
    available = left_path.exists() and right_path.exists()
    version = max((path.stat().st_mtime_ns for path in existing), default=0)
    run_name = ocr_debug_dir.parent.name if ocr_debug_dir.name == "debug" else ocr_debug_dir.name

    return {
        "run_name": run_name,
        "ocr_debug_dir": str(ocr_debug_dir),
        "stage_file": stage_file,
        "left_path": left_path,
        "right_path": right_path,
        "available": available,
        "version": version,
    }


def read_review_state(capture_session_dir: Path, ocr_debug_dir: Path) -> dict[str, Any]:
    raw_state = read_raw_review_state(capture_session_dir)
    rectified_state = read_capture_review_state(capture_session_dir)
    enhanced_state = read_ocr_review_state(capture_session_dir / "debug", "enhanced")
    ocr_overlay_state = read_ocr_words_review_state(ocr_debug_dir)

    sources = {
        REVIEW_SOURCE_RAW: {
            "key": REVIEW_SOURCE_RAW,
            "label": REVIEW_SOURCE_LABELS[REVIEW_SOURCE_RAW],
            "source_dir": raw_state["raw_dir"],
            "left_path": raw_state["left_path"],
            "right_path": raw_state["right_path"],
            "left_label": "Raw / left",
            "right_label": "Raw / right",
            "available": raw_state["available"],
            "version": raw_state["version"],
        },
        REVIEW_SOURCE_RECTIFIED: {
            "key": REVIEW_SOURCE_RECTIFIED,
            "label": REVIEW_SOURCE_LABELS[REVIEW_SOURCE_RECTIFIED],
            "source_dir": rectified_state["case_dir"],
            "left_path": rectified_state["left_path"],
            "right_path": rectified_state["right_path"],
            "left_label": "Entzerrt / left",
            "right_label": "Entzerrt / right",
            "available": rectified_state["available"],
            "version": rectified_state["version"],
        },
        REVIEW_SOURCE_ENHANCED: {
            "key": REVIEW_SOURCE_ENHANCED,
            "label": REVIEW_SOURCE_LABELS[REVIEW_SOURCE_ENHANCED],
            "source_dir": enhanced_state["ocr_debug_dir"],
            "left_path": enhanced_state["left_path"],
            "right_path": enhanced_state["right_path"],
            "left_label": f"Enhanced / {enhanced_state['stage_file']}",
            "right_label": f"Enhanced / {enhanced_state['stage_file']}",
            "available": enhanced_state["available"],
            "version": enhanced_state["version"],
        },
        REVIEW_SOURCE_OCR_OVERLAY: {
            "key": REVIEW_SOURCE_OCR_OVERLAY,
            "label": REVIEW_SOURCE_LABELS[REVIEW_SOURCE_OCR_OVERLAY],
            "source_dir": ocr_overlay_state["ocr_debug_dir"],
            "left_path": ocr_overlay_state["left_path"],
            "right_path": ocr_overlay_state["right_path"],
            "left_label": f"OCR Overlay / {ocr_overlay_state['stage_file']}",
            "right_label": f"OCR Overlay / {ocr_overlay_state['stage_file']}",
            "available": ocr_overlay_state["available"],
            "version": ocr_overlay_state["version"],
        },
    }

    return {
        "session_name": rectified_state["session_name"],
        "run_name": ocr_overlay_state["run_name"],
        "capture_session_dir": str(capture_session_dir),
        "ocr_debug_dir": str(ocr_debug_dir),
        "sources": sources,
    }


def _missing_paths_for_source(source: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for key in ("left_path", "right_path"):
        path = source[key]
        if not Path(path).exists():
            missing.append(str(path))
    return missing


def serialize_review_state(review_state: dict[str, Any], selected_source: str) -> dict[str, Any]:
    resolved_source = selected_source if selected_source in review_state["sources"] else REVIEW_SOURCE_RECTIFIED
    return {
        "mode": "review",
        "selected_source": resolved_source,
        "session_name": review_state["session_name"],
        "run_name": review_state["run_name"],
        "capture_session_dir": review_state["capture_session_dir"],
        "ocr_debug_dir": review_state["ocr_debug_dir"],
        "sources": {
            source_key: {
                "key": source["key"],
                "label": source["label"],
                "source_dir": str(source["source_dir"]),
                "left_path": str(source["left_path"]),
                "right_path": str(source["right_path"]),
                "left_label": source["left_label"],
                "right_label": source["right_label"],
                "available": source["available"],
                "version": source["version"],
                "missing_paths": _missing_paths_for_source(source),
            }
            for source_key, source in review_state["sources"].items()
        },
    }


def review_source_state(review_state: dict[str, Any], source_key: str) -> dict[str, Any]:
    try:
        return review_state["sources"][source_key]
    except KeyError as exc:
        raise ValueError(f"Unbekannte Review-Quelle: {source_key}") from exc


def media_type_for_path(path: Path) -> str:
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if path.suffix.lower() == ".png":
        return "image/png"
    return "application/octet-stream"


def build_review_radio_controls(selected_source: str) -> str:
    controls: list[str] = []
    for source_key in REVIEW_SOURCE_ORDER:
        checked = "checked" if source_key == selected_source else ""
        label = REVIEW_SOURCE_LABELS[source_key]
        controls.append(
            f'<label class="radio"><input type="radio" name="review-source" value="{source_key}" {checked}>'
            f"<span>{label}</span></label>"
        )
    return "\n".join(controls)


def determine_max_sensor_mode(picam2: Any) -> dict[str, Any] | None:
    sensor_modes = list(getattr(picam2, "sensor_modes", []) or [])
    best_mode: dict[str, Any] | None = None
    best_key = (-1, -1.0, -1)
    for mode in sensor_modes:
        size = mode.get("size")
        if not size or len(size) != 2:
            continue
        width, height = int(size[0]), int(size[1])
        area = width * height
        fps = float(mode.get("fps", 0.0) or 0.0)
        bit_depth = int(mode.get("bit_depth", 0) or 0)
        key = (area, fps, bit_depth)
        if key > best_key:
            best_key = key
            best_mode = mode
    return best_mode


def determine_output_size(picam2: Any, override_width: int | None, override_height: int | None) -> tuple[int, int]:
    if override_width and override_height:
        return override_width, override_height

    best_mode = determine_max_sensor_mode(picam2)
    if best_mode and best_mode.get("size"):
        width, height = best_mode["size"]
        return int(width), int(height)

    sensor_resolution = getattr(picam2, "sensor_resolution", None)
    if sensor_resolution:
        width, height = sensor_resolution
        return int(width), int(height)

    properties = getattr(picam2, "camera_properties", {}) or {}
    pixel_array_size = properties.get("PixelArraySize")
    if pixel_array_size and len(pixel_array_size) == 2:
        width, height = pixel_array_size
        return int(width), int(height)

    raise RuntimeError("Konnte keine maximale Sensoraufloesung fuer die Kamera bestimmen.")


def build_camera_configuration(
    picam2: Any,
    output_size: tuple[int, int],
    buffer_count: int,
    prefer_full_sensor: bool,
) -> dict[str, Any]:
    main_config = {"size": output_size, "format": "BGR888"}
    sensor_mode = determine_max_sensor_mode(picam2) if prefer_full_sensor else None

    if sensor_mode and sensor_mode.get("size"):
        sensor_config: dict[str, Any] = {"output_size": tuple(sensor_mode["size"])}
        if sensor_mode.get("bit_depth"):
            sensor_config["bit_depth"] = int(sensor_mode["bit_depth"])
        try:
            config = picam2.create_video_configuration(
                main=main_config,
                sensor=sensor_config,
            )
        except TypeError:
            config = picam2.create_video_configuration(main=main_config)
    else:
        config = picam2.create_video_configuration(main=main_config)

    config["buffer_count"] = buffer_count
    return config


def camera_model(picam2: Any) -> str:
    properties = getattr(picam2, "camera_properties", {}) or {}
    return str(properties.get("Model") or properties.get("model") or "unbekannt")


def make_handler(app_state: dict[str, Any]) -> type[server.BaseHTTPRequestHandler]:
    class CameraTestHandler(server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if app_state["mode"] in {"review", "capture-review", "ocr-review", "ocr-words-review"}:
                if parsed.path == "/":
                    self._serve_review_index()
                    return
                if parsed.path == "/review-status.json":
                    self._serve_review_status()
                    return
                if parsed.path in ("/review-image/left", "/review-image/right"):
                    slot_name = "left" if parsed.path.endswith("/left") else "right"
                    query = parse_qs(parsed.query)
                    source_key = query.get("source", [app_state["review_source"]])[0]
                    self._serve_review_image(slot_name, source_key)
                    return
                self.send_error(404)
                return

            if parsed.path == "/":
                self._serve_index()
                return
            if parsed.path == "/stream.mjpg":
                self._serve_stream()
                return
            if parsed.path == "/snapshot.jpg":
                self._serve_snapshot()
                return
            if parsed.path == "/status.json":
                self._serve_status()
                return
            self.send_error(404)

        def log_message(self, format: str, *args: Any) -> None:
            message = "%s - - [%s] %s\n" % (
                self.client_address[0],
                self.log_date_time_string(),
                format % args,
            )
            sys.stderr.write(message)

        def _serve_index(self) -> None:
            page = LIVE_PAGE_TEMPLATE.format(
                camera_index=app_state["camera_index"],
                camera_model=app_state["camera_model"],
                resolution=app_state["resolution"],
                fps=f"{app_state['frame_buffer'].snapshot()[2]:.1f}",
                crosshair_checked="checked" if app_state["crosshair_enabled"] else "",
                crosshair_visible="true" if app_state["crosshair_enabled"] else "false",
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

        def _serve_review_index(self) -> None:
            review_state = read_review_state(app_state["capture_session_dir"], app_state["ocr_debug_dir"])
            payload = serialize_review_state(review_state, app_state["review_source"])
            selected_source = review_source_state(review_state, payload["selected_source"])
            availability = "Bilder verfuegbar" if selected_source["available"] else "Noch keine Bilder"
            version_query = selected_source["version"] or "0"
            if selected_source["available"]:
                left_src = f"/review-image/left?source={payload['selected_source']}&version={version_query}"
                right_src = f"/review-image/right?source={payload['selected_source']}&version={version_query}"
            else:
                left_src = ""
                right_src = ""
            page = REVIEW_PAGE_TEMPLATE.format(
                radio_controls=build_review_radio_controls(payload["selected_source"]),
                initial_source_label=selected_source["label"],
                initial_availability=availability,
                initial_version=selected_source["version"] or "-",
                initial_source_dir=selected_source["source_dir"],
                session_name=payload["session_name"],
                run_name=payload["run_name"],
                initial_left_label=selected_source["left_label"],
            initial_right_label=selected_source["right_label"],
            initial_left_src=left_src,
            initial_right_src=right_src,
            initial_left_path=str(selected_source["left_path"]),
            initial_right_path=str(selected_source["right_path"]),
            initial_missing_paths=" | ".join(_missing_paths_for_source(selected_source)) or "keine",
            initial_state_json=json.dumps(payload, ensure_ascii=False),
            initial_source_json=json.dumps(payload["selected_source"]),
        ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

        def _serve_stream(self) -> None:
            self.send_response(200)
            self.send_header("Age", "0")
            self.send_header("Cache-Control", "no-cache, private")
            self.send_header("Pragma", "no-cache")
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=FRAME")
            self.end_headers()

            last_seen = 0
            try:
                while not app_state["stop_event"].is_set():
                    frame_count, frame = app_state["frame_buffer"].wait_for_new_frame(last_seen)
                    if frame is None or frame_count == last_seen:
                        continue
                    last_seen = frame_count
                    self.wfile.write(b"--FRAME\r\n")
                    self.wfile.write(b"Content-Type: image/jpeg\r\n")
                    self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n".encode("ascii"))
                    self.wfile.write(frame)
                    self.wfile.write(b"\r\n")
            except (BrokenPipeError, ConnectionResetError):
                return

        def _serve_snapshot(self) -> None:
            _frame_count, frame, _fps = app_state["frame_buffer"].snapshot()
            if frame is None:
                self.send_error(503, "Noch kein Kamerabild verfuegbar.")
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(frame)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(frame)

        def _serve_status(self) -> None:
            frame_count, _frame, fps = app_state["frame_buffer"].snapshot()
            last_frame_age = app_state["frame_buffer"].last_frame_age()
            payload = {
                "camera_index": app_state["camera_index"],
                "camera_model": app_state["camera_model"],
                "resolution": app_state["resolution"],
                "crosshair_enabled": app_state["crosshair_enabled"],
                "frame_count": frame_count,
                "fps": fps,
                "healthy": not app_state["stop_event"].is_set(),
                "last_frame_age_sec": last_frame_age,
                "error": app_state.get("error_message"),
                "uptime_sec": time.monotonic() - app_state["started_at"],
            }
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _serve_review_status(self) -> None:
            review_state = read_review_state(app_state["capture_session_dir"], app_state["ocr_debug_dir"])
            payload = serialize_review_state(review_state, app_state["review_source"])
            payload["uptime_sec"] = time.monotonic() - app_state["started_at"]
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _serve_review_image(self, slot_name: str, source_key: str) -> None:
            try:
                source_state = review_source_state(
                    read_review_state(app_state["capture_session_dir"], app_state["ocr_debug_dir"]),
                    source_key,
                )
            except ValueError as exc:
                self.send_error(404, str(exc))
                return
            image_path = source_state[f"{slot_name}_path"]
            if not image_path.exists():
                self.send_error(404, f"Noch kein Bild fuer {slot_name} verfuegbar.")
                return
            image_bytes = image_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", media_type_for_path(image_path))
            self.send_header("Content-Length", str(len(image_bytes)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(image_bytes)

    return CameraTestHandler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Startet einen kleinen Webserver auf dem Raspberry Pi und zeigt "
            "entweder ein Picamera2-Livebild oder die letzten Capture-Ergebnisse."
        )
    )
    parser.add_argument(
        "--mode",
        choices=("live", "review", "capture-review", "ocr-review", "ocr-words-review"),
        default="live",
        help="Servermodus, Standard: live",
    )
    parser.add_argument("--camera", type=int, default=0, help="Kameraindex, Standard: 0")
    parser.add_argument("--host", default="0.0.0.0", help="Bind-Adresse, Standard: 0.0.0.0")
    parser.add_argument("--port", type=int, default=8000, help="HTTP-Port, Standard: 8000")
    parser.add_argument("--width", type=int, help="Optionale Zielbreite statt Vollaufloesung")
    parser.add_argument("--height", type=int, help="Optionale Zielhoehe statt Vollaufloesung")
    parser.add_argument(
        "--crosshair",
        action="store_true",
        help="Fadenkreuz im Browserbild initial einblenden",
    )
    parser.add_argument("--buffer-count", type=int, default=6, help="Picamera2 buffer_count, Standard: 6")
    parser.add_argument("--jpeg-quality", type=int, default=90, help="JPEG-Qualitaet 0-100, Standard: 90")
    parser.add_argument(
        "--frame-timeout",
        type=float,
        default=3.0,
        help="Maximale Zeit ohne neues JPEG-Frame in Sekunden, Standard: 3.0",
    )
    parser.add_argument(
        "--capture-session-dir",
        type=Path,
        default=DEFAULT_CAPTURE_SESSION_DIR,
        help=f"Capture-Session-Verzeichnis fuer den Review-Modus, Standard: {DEFAULT_CAPTURE_SESSION_DIR}",
    )
    parser.add_argument(
        "--ocr-debug-dir",
        type=Path,
        default=DEFAULT_OCR_DEBUG_DIR,
        help=f"OCR-Debug-Verzeichnis fuer den Review-Modus, Standard: {DEFAULT_OCR_DEBUG_DIR}",
    )
    parser.add_argument(
        "--ocr-stage",
        choices=tuple(OCR_STAGE_FILES.keys()),
        default="enhanced",
        help="Veraltete Option aus dem alten ocr-review-Modus; wird im neuen Review-Modus ignoriert.",
    )
    parser.add_argument(
        "--review-source",
        choices=REVIEW_SOURCE_ORDER,
        help="Initiale Bildquelle fuer --mode review, Standard: rectified",
    )
    return parser.parse_args()


def print_start_banner(args: argparse.Namespace, resolution: tuple[int, int], model: str) -> None:
    hostname = socket.gethostname()
    local_url = f"http://{hostname}.local:{args.port}/"
    bind_url = f"http://{args.host}:{args.port}/"
    print(f"Kamera-Testserver gestartet fuer Kamera {args.camera}.", file=sys.stderr)
    print(f"Kameramodell: {model}", file=sys.stderr)
    print(f"Aufloesung: {resolution[0]}x{resolution[1]}", file=sys.stderr)
    print(f"Fadenkreuz: {'aktiv' if args.crosshair else 'inaktiv'}", file=sys.stderr)
    print(f"Lokaler Bonjour-Link: {local_url}", file=sys.stderr)
    print(f"Bind-Adresse: {bind_url}", file=sys.stderr)
    print("Mit Ctrl+C beenden.", file=sys.stderr)


def print_review_banner(args: argparse.Namespace, review_source: str) -> None:
    hostname = socket.gethostname()
    local_url = f"http://{hostname}.local:{args.port}/"
    bind_url = f"http://{args.host}:{args.port}/"
    print("Review-Server gestartet.", file=sys.stderr)
    print(f"Session-Verzeichnis: {args.capture_session_dir.resolve()}", file=sys.stderr)
    print(f"Debug-Verzeichnis: {args.ocr_debug_dir.resolve()}", file=sys.stderr)
    print(f"Initiale Quelle: {REVIEW_SOURCE_LABELS[review_source]}", file=sys.stderr)
    print(f"Lokaler Bonjour-Link: {local_url}", file=sys.stderr)
    print(f"Bind-Adresse: {bind_url}", file=sys.stderr)
    print("Mit Ctrl+C beenden.", file=sys.stderr)


def main() -> int:
    args = parse_args()
    if args.mode in {"review", "capture-review", "ocr-review", "ocr-words-review"}:
        return run_review_mode(args)
    return run_live_mode(args)


def run_review_mode(args: argparse.Namespace) -> int:
    review_source = args.review_source or REVIEW_MODE_DEFAULT_SOURCE.get(args.mode, REVIEW_SOURCE_RECTIFIED)
    app_state = {
        "mode": args.mode,
        "capture_session_dir": args.capture_session_dir.resolve(),
        "ocr_debug_dir": args.ocr_debug_dir.resolve(),
        "review_source": review_source,
        "started_at": time.monotonic(),
    }
    httpd = ThreadingHTTPServer((args.host, args.port), make_handler(app_state))
    httpd.timeout = 0.5
    print_review_banner(args, review_source)

    try:
        while True:
            httpd.handle_request()
    except KeyboardInterrupt:
        return 0
    finally:
        httpd.server_close()


def run_live_mode(args: argparse.Namespace) -> int:
    if (args.width is None) != (args.height is None):
        print("--width und --height muessen gemeinsam gesetzt werden.", file=sys.stderr)
        return 2
    if not 0 <= args.jpeg_quality <= 100:
        print("--jpeg-quality muss zwischen 0 und 100 liegen.", file=sys.stderr)
        return 2
    if args.frame_timeout <= 0:
        print("--frame-timeout muss groesser als 0 sein.", file=sys.stderr)
        return 2

    try:
        Picamera2, JpegEncoder, FileOutput = import_picamera2_runtime()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    camera_info = Picamera2.global_camera_info()
    if args.camera < 0 or args.camera >= len(camera_info):
        print(
            "Keine passende Kamera verfuegbar. "
            "Bitte zuerst `rpicam-hello --list-cameras` pruefen.",
            file=sys.stderr,
        )
        return 1

    picam2 = Picamera2(args.camera)
    resolution = determine_output_size(picam2, args.width, args.height)
    configuration = build_camera_configuration(
        picam2,
        resolution,
        args.buffer_count,
        prefer_full_sensor=args.width is None and args.height is None,
    )
    picam2.configure(configuration)

    frame_buffer = LatestFrameBuffer()
    stop_event = threading.Event()
    streaming_output = StreamingOutput(frame_buffer)
    encoder = JpegEncoder(q=args.jpeg_quality)

    app_state = {
        "mode": "live",
        "camera_index": args.camera,
        "camera_model": camera_model(picam2),
        "resolution": f"{resolution[0]}x{resolution[1]}",
        "crosshair_enabled": args.crosshair,
        "frame_buffer": frame_buffer,
        "stop_event": stop_event,
        "error_message": None,
        "started_at": time.monotonic(),
    }

    httpd = ThreadingHTTPServer((args.host, args.port), make_handler(app_state))
    httpd.timeout = 0.5
    watchdog = StreamWatchdog(
        frame_buffer=frame_buffer,
        stop_event=stop_event,
        timeout_sec=args.frame_timeout,
    )
    picam2.start_recording(encoder, FileOutput(streaming_output))
    watchdog.start()
    print_start_banner(args, resolution, app_state["camera_model"])

    try:
        while not stop_event.is_set():
            httpd.handle_request()
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        httpd.server_close()
        watchdog.join(timeout=2.0)
        picam2.stop_recording()

    if watchdog.error_message is not None:
        app_state["error_message"] = watchdog.error_message
        print(f"Kamera-Stream fehlgeschlagen: {watchdog.error_message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
