from __future__ import annotations

from abr.control.frontpanel import (
    ABRActionType,
    ABRController,
    ControllerState,
    FrontPanelButtonConfig,
    FrontPanelButtonEvent,
    FrontPanelButtonState,
    FrontPanelConfig,
    FrontPanelEncoderEvent,
    FrontPanelEventSink,
    FrontPanelEventType,
    FrontPanelMonitor,
    _ButtonDebouncer,
)
from abr.hardware.control_panel import CONTROL_PANEL_PINS, ENCODER_A_PIN, ENCODER_B_PIN


class _FakeGPIO:
    def __init__(self) -> None:
        self.levels = {pin: True for pin in CONTROL_PANEL_PINS}
        self.configured: list[int] = []
        self.closed = False

    def configure_inputs(self, pins) -> None:
        self.configured = list(pins)

    def read_levels(self, pins) -> dict[int, bool]:
        return {pin: self.levels[pin] for pin in pins}

    def close(self) -> None:
        self.closed = True


class _InterruptGPIO(_FakeGPIO):
    def __init__(self) -> None:
        super().__init__()
        self.callbacks = {}

    def add_edge_callback(self, pin, callback) -> bool:
        self.callbacks[pin] = callback
        return True

    def remove_edge_callback(self, pin) -> None:
        self.callbacks.pop(pin, None)

    def set_encoder_levels(self, a_high: bool, b_high: bool) -> None:
        old_a = self.levels[ENCODER_A_PIN]
        old_b = self.levels[ENCODER_B_PIN]
        self.levels[ENCODER_A_PIN] = a_high
        self.levels[ENCODER_B_PIN] = b_high
        if a_high != old_a:
            self.callbacks[ENCODER_A_PIN](ENCODER_A_PIN)
        if b_high != old_b:
            self.callbacks[ENCODER_B_PIN](ENCODER_B_PIN)


def test_button_debouncer_emits_after_stable_interval() -> None:
    config = FrontPanelButtonConfig("start_stop_nfc", "Start / Stop / NFC", 17, debounce_ms=20.0)
    debouncer = _ButtonDebouncer.create(config, is_pressed=False, now=0.0)

    assert debouncer.update(True, 0.005) is None
    assert debouncer.update(True, 0.015) is None

    event = debouncer.update(True, 0.030)
    assert event is not None
    assert event.event_type == FrontPanelEventType.BUTTON_DOWN
    assert event.state == FrontPanelButtonState.PRESSED


def test_monitor_emits_encoder_event_with_inverted_default_direction() -> None:
    gpio = _FakeGPIO()
    sink = FrontPanelEventSink()
    monitor = FrontPanelMonitor(gpio=gpio, config=FrontPanelConfig(), event_sink=sink)

    initial = dict(gpio.levels)
    monitor._last_levels = initial
    monitor._decoder.update(initial[ENCODER_A_PIN], initial[ENCODER_B_PIN])
    now = 1.0
    monitor._button_debouncers = {
        button.pin: _ButtonDebouncer.create(button, is_pressed=False, now=now)
        for button in monitor.config.buttons
    }

    for levels in (
        {**initial, ENCODER_A_PIN: False, ENCODER_B_PIN: True},
        {**initial, ENCODER_A_PIN: False, ENCODER_B_PIN: False},
        {**initial, ENCODER_A_PIN: True, ENCODER_B_PIN: False},
        initial,
    ):
        monitor._process_sample(levels, now)
        now += 0.001

    event = sink.get_nowait()
    assert isinstance(event, FrontPanelEncoderEvent)
    assert event.event_type == FrontPanelEventType.ENCODER_STEP
    assert event.delta == 1
    assert event.position == 1


def test_monitor_interrupt_updates_volume_target_before_event_is_consumed() -> None:
    gpio = _InterruptGPIO()
    sink = FrontPanelEventSink()
    immediate_deltas: list[int] = []
    monitor = FrontPanelMonitor(
        gpio=gpio,
        event_sink=sink,
        encoder_step_callback=immediate_deltas.append,
    )

    monitor.start()
    try:
        for a_high, b_high in (
            (False, True),
            (False, False),
            (True, False),
            (True, True),
        ):
            gpio.set_encoder_levels(a_high, b_high)

        assert immediate_deltas == [1]
        event = sink.get_nowait()
        assert isinstance(event, FrontPanelEncoderEvent)
        assert event.delta == 1
    finally:
        monitor.stop()

    assert gpio.callbacks == {}


def test_controller_translates_start_stop_and_volume_events() -> None:
    monitor = FrontPanelMonitor(gpio=_FakeGPIO())
    controller = ABRController(monitor=monitor)

    button_event = FrontPanelButtonEvent(
        event_type=FrontPanelEventType.BUTTON_DOWN,
        control="start_stop_nfc",
        label="Start / Stop / NFC",
        monotonic_time=1.0,
        pin=17,
        state=FrontPanelButtonState.PRESSED,
    )
    action = controller.translate_event(button_event)
    assert action is None
    delayed_actions = controller._action_router.drain_pending_actions(monotonic_time=1.3)
    assert len(delayed_actions) == 1
    assert delayed_actions[0].action_type == ABRActionType.START_STOP
    controller._transition_for_start_stop()
    assert controller.state == ControllerState.CAPTURING

    encoder_event = FrontPanelEncoderEvent(
        event_type=FrontPanelEventType.ENCODER_STEP,
        control="volume",
        label="Lautstaerke",
        monotonic_time=2.0,
        delta=-2,
        position=-3,
    )
    volume_action = controller.translate_event(encoder_event)
    assert volume_action is not None
    assert volume_action.action_type == ABRActionType.VOLUME_DELTA
    assert volume_action.value == -2


def test_action_router_emits_delete_combo_for_three_simultaneous_buttons() -> None:
    router = ABRController(monitor=FrontPanelMonitor(gpio=_FakeGPIO()))._action_router

    first = FrontPanelButtonEvent(
        event_type=FrontPanelEventType.BUTTON_DOWN,
        control="start_stop_nfc",
        label="Start / Stop / NFC",
        monotonic_time=1.0,
        pin=17,
        state=FrontPanelButtonState.PRESSED,
    )
    second = FrontPanelButtonEvent(
        event_type=FrontPanelEventType.BUTTON_DOWN,
        control="book_summary",
        label="Buch-Zusammenfassung",
        monotonic_time=1.05,
        pin=22,
        state=FrontPanelButtonState.PRESSED,
    )
    third = FrontPanelButtonEvent(
        event_type=FrontPanelEventType.BUTTON_DOWN,
        control="chapter_summary",
        label="Kapitel-/Letzte-Seiten-Zusammenfassung",
        monotonic_time=1.1,
        pin=24,
        state=FrontPanelButtonState.PRESSED,
    )

    assert router.translate_event(first) is None
    assert router.translate_event(second) is None
    action = router.translate_event(third)
    assert action is not None
    assert action.action_type == ABRActionType.DELETE_BOOK_REQUEST
