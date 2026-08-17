from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from queue import Empty, Queue
from threading import Event, Lock, Thread
import time
from typing import Callable

from abr.hardware.control_panel import (
    BUTTON_LABELS,
    BUTTON_PINS,
    CONTROL_PANEL_PINS,
    EC11Decoder,
    ENCODER_A_PIN,
    ENCODER_B_PIN,
    InputGPIO,
    create_input_gpio,
)


class FrontPanelEventType(str, Enum):
    BUTTON_DOWN = "button_down"
    BUTTON_UP = "button_up"
    ENCODER_STEP = "encoder_step"


class FrontPanelButtonState(str, Enum):
    PRESSED = "pressed"
    RELEASED = "released"


class ABRActionType(str, Enum):
    START_STOP = "start_stop"
    BOOK_SUMMARY = "book_summary"
    CHAPTER_SUMMARY = "chapter_summary"
    ENCODER_BUTTON = "encoder_button"
    VOLUME_DELTA = "volume_delta"
    DELETE_BOOK_REQUEST = "delete_book_request"


class ControllerState(str, Enum):
    IDLE = "idle"
    CAPTURING = "capturing"
    READING = "reading"
    SUMMARIZING = "summarizing"
    STOPPING = "stopping"
    ERROR = "error"


@dataclass(frozen=True)
class FrontPanelEvent:
    event_type: FrontPanelEventType
    control: str
    label: str
    monotonic_time: float


@dataclass(frozen=True)
class FrontPanelButtonEvent(FrontPanelEvent):
    pin: int
    state: FrontPanelButtonState


@dataclass(frozen=True)
class FrontPanelEncoderEvent(FrontPanelEvent):
    delta: int
    position: int


@dataclass(frozen=True)
class ABRAction:
    action_type: ABRActionType
    source_event: FrontPanelEvent
    value: int | None = None


@dataclass(frozen=True)
class FrontPanelButtonConfig:
    name: str
    label: str
    pin: int
    debounce_ms: float = 25.0


@dataclass(frozen=True)
class FrontPanelEncoderConfig:
    name: str = "volume"
    label: str = "Lautstaerke"
    pin_a: int = ENCODER_A_PIN
    pin_b: int = ENCODER_B_PIN
    steps_per_detent: int = 4
    direction_sign: int = -1


@dataclass(frozen=True)
class FrontPanelConfig:
    poll_interval_ms: float = 2.0
    active_poll_interval_ms: float = 0.5
    encoder_active_hold_ms: float = 25.0
    buttons: tuple[FrontPanelButtonConfig, ...] = (
        FrontPanelButtonConfig("encoder_button", BUTTON_LABELS[BUTTON_PINS["encoder_button"]], BUTTON_PINS["encoder_button"]),
        FrontPanelButtonConfig("start_stop_nfc", BUTTON_LABELS[BUTTON_PINS["start_stop_nfc"]], BUTTON_PINS["start_stop_nfc"]),
        FrontPanelButtonConfig("book_summary", BUTTON_LABELS[BUTTON_PINS["book_summary"]], BUTTON_PINS["book_summary"]),
        FrontPanelButtonConfig("chapter_summary", BUTTON_LABELS[BUTTON_PINS["chapter_summary"]], BUTTON_PINS["chapter_summary"]),
    )
    encoder: FrontPanelEncoderConfig = field(default_factory=FrontPanelEncoderConfig)
    gpio_backend: str = "auto"


@dataclass
class _ButtonDebouncer:
    config: FrontPanelButtonConfig
    raw_pressed: bool
    stable_pressed: bool
    raw_changed_at: float

    @classmethod
    def create(cls, config: FrontPanelButtonConfig, is_pressed: bool, now: float) -> _ButtonDebouncer:
        return cls(
            config=config,
            raw_pressed=is_pressed,
            stable_pressed=is_pressed,
            raw_changed_at=now,
        )

    def update(self, is_pressed: bool, now: float) -> FrontPanelButtonEvent | None:
        if is_pressed != self.raw_pressed:
            self.raw_pressed = is_pressed
            self.raw_changed_at = now
            return None

        debounce_s = self.config.debounce_ms / 1000.0
        if is_pressed == self.stable_pressed or (now - self.raw_changed_at) < debounce_s:
            return None

        self.stable_pressed = is_pressed
        event_type = FrontPanelEventType.BUTTON_DOWN if is_pressed else FrontPanelEventType.BUTTON_UP
        state = FrontPanelButtonState.PRESSED if is_pressed else FrontPanelButtonState.RELEASED
        return FrontPanelButtonEvent(
            event_type=event_type,
            control=self.config.name,
            label=self.config.label,
            monotonic_time=now,
            pin=self.config.pin,
            state=state,
        )


class FrontPanelEventSink:
    def __init__(self) -> None:
        self._queue: Queue[FrontPanelEvent] = Queue()

    def put(self, event: FrontPanelEvent) -> None:
        self._queue.put(event)

    def get(self, timeout: float | None = None) -> FrontPanelEvent:
        return self._queue.get(timeout=timeout)

    def get_nowait(self) -> FrontPanelEvent:
        return self._queue.get_nowait()

    def empty(self) -> bool:
        return self._queue.empty()


class FrontPanelMonitor:
    def __init__(
        self,
        gpio: InputGPIO | None = None,
        config: FrontPanelConfig | None = None,
        event_sink: FrontPanelEventSink | None = None,
        status_callback: Callable[[str], None] | None = None,
        encoder_step_callback: Callable[[int], None] | None = None,
    ) -> None:
        self.config = config or FrontPanelConfig()
        self.gpio = gpio or create_input_gpio(self.config.gpio_backend)
        self.event_sink = event_sink or FrontPanelEventSink()
        self.status_callback = status_callback
        self.encoder_step_callback = encoder_step_callback
        self._stop_event = Event()
        self._worker: Thread | None = None
        self._decoder = EC11Decoder(steps_per_detent=self.config.encoder.steps_per_detent)
        self._encoder_lock = Lock()
        self._encoder_interrupts_active = False
        self._button_debouncers: dict[int, _ButtonDebouncer] = {}
        self._last_levels: dict[int, bool] | None = None
        self._encoder_fast_poll_until = 0.0

    def start(self) -> None:
        if self._worker is not None:
            raise RuntimeError("FrontPanelMonitor laeuft bereits.")
        self.gpio.configure_inputs(CONTROL_PANEL_PINS)
        initial_levels = self.gpio.read_levels(CONTROL_PANEL_PINS)
        now = time.monotonic()
        self._last_levels = initial_levels
        self._decoder.update(initial_levels[ENCODER_A_PIN], initial_levels[ENCODER_B_PIN])
        self._button_debouncers = {
            button.pin: _ButtonDebouncer.create(button, not initial_levels[button.pin], now)
            for button in self.config.buttons
        }
        self._encoder_interrupts_active = self._install_encoder_interrupts()
        self._worker = Thread(target=self._run_loop, name="abr-frontpanel", daemon=True)
        self._worker.start()
        encoder_mode = "GPIO-Interrupt" if self._encoder_interrupts_active else "Polling-Fallback"
        self._emit_status(f"Frontpanel-Monitor gestartet (EC11: {encoder_mode}).")

    def stop(self) -> None:
        self._stop_event.set()
        if self._worker is not None:
            self._worker.join()
            self._worker = None
        self._remove_encoder_interrupts()
        self.gpio.close()
        self._emit_status("Frontpanel-Monitor gestoppt.")

    def get_event(self, timeout: float | None = None) -> FrontPanelEvent:
        return self.event_sink.get(timeout=timeout)

    def set_encoder_step_callback(self, callback: Callable[[int], None] | None) -> None:
        self.encoder_step_callback = callback

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            now = time.monotonic()
            levels = self.gpio.read_levels(CONTROL_PANEL_PINS)
            self._process_sample(levels, now)
            interval_s = self._current_poll_interval(now)
            self._stop_event.wait(interval_s)

    def _process_sample(self, levels: dict[int, bool], now: float) -> None:
        for button in self.config.buttons:
            event = self._button_debouncers[button.pin].update(not levels[button.pin], now)
            if event is not None:
                self.event_sink.put(event)

        if not self._encoder_interrupts_active and self._last_levels is not None and (
            levels[ENCODER_A_PIN] != self._last_levels[ENCODER_A_PIN]
            or levels[ENCODER_B_PIN] != self._last_levels[ENCODER_B_PIN]
        ):
            hold_s = self.config.encoder_active_hold_ms / 1000.0
            self._encoder_fast_poll_until = now + hold_s

        if not self._encoder_interrupts_active:
            self._process_encoder_levels(
                levels[ENCODER_A_PIN],
                levels[ENCODER_B_PIN],
                now,
            )

        self._last_levels = levels

    def _process_encoder_levels(self, a_high: bool, b_high: bool, now: float) -> None:
        with self._encoder_lock:
            delta = self._decoder.update(a_high, b_high)
            delta *= self.config.encoder.direction_sign
            position = self._decoder.position * self.config.encoder.direction_sign
        if delta != 0:
            if self.encoder_step_callback is not None:
                self.encoder_step_callback(delta)
            self.event_sink.put(
                FrontPanelEncoderEvent(
                    event_type=FrontPanelEventType.ENCODER_STEP,
                    control=self.config.encoder.name,
                    label=self.config.encoder.label,
                    monotonic_time=now,
                    delta=delta,
                    position=position,
                )
            )

    def _install_encoder_interrupts(self) -> bool:
        add_callback = getattr(self.gpio, "add_edge_callback", None)
        if not callable(add_callback):
            return False
        installed: list[int] = []
        try:
            for pin in (ENCODER_A_PIN, ENCODER_B_PIN):
                if not add_callback(pin, self._handle_encoder_edge):
                    raise RuntimeError("GPIO-Backend bietet keine Flankeninterrupts.")
                installed.append(pin)
        except BaseException as exc:
            remove_callback = getattr(self.gpio, "remove_edge_callback", None)
            if callable(remove_callback):
                for pin in installed:
                    remove_callback(pin)
            self._emit_status(f"EC11-Interrupt nicht verfuegbar, Polling wird verwendet: {exc}")
            return False
        return True

    def _remove_encoder_interrupts(self) -> None:
        if not self._encoder_interrupts_active:
            return
        remove_callback = getattr(self.gpio, "remove_edge_callback", None)
        if callable(remove_callback):
            for pin in (ENCODER_A_PIN, ENCODER_B_PIN):
                remove_callback(pin)
        self._encoder_interrupts_active = False

    def _handle_encoder_edge(self, _pin: int) -> None:
        try:
            levels = self.gpio.read_levels((ENCODER_A_PIN, ENCODER_B_PIN))
            self._process_encoder_levels(
                levels[ENCODER_A_PIN],
                levels[ENCODER_B_PIN],
                time.monotonic(),
            )
        except BaseException as exc:  # pragma: no cover - hardware callback guard
            self._emit_status(f"EC11-Interrupt fehlgeschlagen: {exc}")

    def _current_poll_interval(self, now: float) -> float:
        if now < self._encoder_fast_poll_until:
            return self.config.active_poll_interval_ms / 1000.0
        return self.config.poll_interval_ms / 1000.0

    def _emit_status(self, message: str) -> None:
        if self.status_callback is not None:
            self.status_callback(message)


class FrontPanelActionRouter:
    CHORD_CONTROLS = ("start_stop_nfc", "book_summary", "chapter_summary")

    def __init__(self, chord_window_ms: float = 180.0) -> None:
        if chord_window_ms < 0:
            raise ValueError("chord_window_ms darf nicht negativ sein.")
        self.chord_window_ms = chord_window_ms
        self._pending_button_downs: dict[str, FrontPanelButtonEvent] = {}
        self._ready_actions: list[ABRAction] = []

    def translate_event(self, event: FrontPanelEvent) -> ABRAction | None:
        self._flush_expired_pending(event.monotonic_time)

        if event.event_type == FrontPanelEventType.BUTTON_UP:
            button_event = event
            assert isinstance(button_event, FrontPanelButtonEvent)
            pending_event = self._pending_button_downs.pop(button_event.control, None)
            if pending_event is not None:
                self._queue_button_action(pending_event)
            return self._pop_ready_action()

        if event.event_type == FrontPanelEventType.ENCODER_STEP:
            encoder_event = event
            assert isinstance(encoder_event, FrontPanelEncoderEvent)
            self._ready_actions.append(
                ABRAction(
                    action_type=ABRActionType.VOLUME_DELTA,
                    source_event=encoder_event,
                    value=encoder_event.delta,
                )
            )
            return self._pop_ready_action()

        button_event = event
        assert isinstance(button_event, FrontPanelButtonEvent)
        if button_event.control in self.CHORD_CONTROLS:
            self._pending_button_downs[button_event.control] = button_event
            if all(control in self._pending_button_downs for control in self.CHORD_CONTROLS):
                self._pending_button_downs.clear()
                self._ready_actions.append(ABRAction(ABRActionType.DELETE_BOOK_REQUEST, button_event))
            return self._pop_ready_action()

        self._queue_button_action(button_event)
        return self._pop_ready_action()

    def drain_pending_actions(self, monotonic_time: float | None = None) -> list[ABRAction]:
        self._flush_expired_pending(monotonic_time or time.monotonic())
        actions = list(self._ready_actions)
        self._ready_actions.clear()
        return actions

    def _flush_expired_pending(self, now: float) -> None:
        if not self._pending_button_downs:
            return
        window_s = self.chord_window_ms / 1000.0
        expired_controls = [
            control
            for control, event in self._pending_button_downs.items()
            if (now - event.monotonic_time) >= window_s
        ]
        for control in expired_controls:
            pending_event = self._pending_button_downs.pop(control, None)
            if pending_event is not None:
                self._queue_button_action(pending_event)

    def _queue_button_action(self, event: FrontPanelButtonEvent) -> None:
        if event.control == "start_stop_nfc":
            self._ready_actions.append(ABRAction(ABRActionType.START_STOP, event))
            return
        if event.control == "book_summary":
            self._ready_actions.append(ABRAction(ABRActionType.BOOK_SUMMARY, event))
            return
        if event.control == "chapter_summary":
            self._ready_actions.append(ABRAction(ABRActionType.CHAPTER_SUMMARY, event))
            return
        if event.control == "encoder_button":
            self._ready_actions.append(ABRAction(ABRActionType.ENCODER_BUTTON, event))

    def _pop_ready_action(self) -> ABRAction | None:
        if not self._ready_actions:
            return None
        return self._ready_actions.pop(0)


class ABRController:
    def __init__(
        self,
        monitor: FrontPanelMonitor,
        action_callback: Callable[[ABRAction], None] | None = None,
        status_callback: Callable[[str], None] | None = None,
    ) -> None:
        self.monitor = monitor
        self.action_callback = action_callback
        self.status_callback = status_callback
        self.state = ControllerState.IDLE
        self._stop_event = Event()
        self._action_router = FrontPanelActionRouter()

    def run_forever(self) -> None:
        self.monitor.start()
        self._emit_status("ABR-Controller gestartet.")
        try:
            while not self._stop_event.is_set():
                try:
                    event = self.monitor.get_event(timeout=0.2)
                except Empty:
                    continue
                action = self.translate_event(event)
                if action is None:
                    continue
                self._emit_status(f"Aktion erkannt: {action.action_type.value}")
                if self.action_callback is not None:
                    self.action_callback(action)
        finally:
            self.monitor.stop()
            self._emit_status("ABR-Controller gestoppt.")

    def stop(self) -> None:
        self._stop_event.set()

    def translate_event(self, event: FrontPanelEvent) -> ABRAction | None:
        action = self._action_router.translate_event(event)
        if action is None:
            return None
        if action.action_type == ABRActionType.START_STOP:
            self._transition_for_start_stop()
        elif action.action_type in (ABRActionType.BOOK_SUMMARY, ABRActionType.CHAPTER_SUMMARY):
            self.state = ControllerState.SUMMARIZING
        return action

    def _transition_for_start_stop(self) -> None:
        if self.state in (ControllerState.IDLE, ControllerState.ERROR):
            self.state = ControllerState.CAPTURING
            return
        if self.state in (ControllerState.CAPTURING, ControllerState.READING, ControllerState.SUMMARIZING):
            self.state = ControllerState.STOPPING
            return
        self.state = ControllerState.IDLE

    def _emit_status(self, message: str) -> None:
        if self.status_callback is not None:
            self.status_callback(message)
