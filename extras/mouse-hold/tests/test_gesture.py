from gesture import Gesture


def test_default_delay_and_startup_radius():
    gesture = Gesture()
    gesture.press(1, 100, 100, 0)
    assert not gesture.due(0.499)
    assert gesture.due(0.5)
    assert gesture.move(106, 100) is None
    assert gesture.move(107, 100) is None
    assert not gesture.due(1)


def test_move_away_then_back_before_start_cancels():
    gesture = Gesture()
    gesture.press(1, 100, 100, 0)
    assert gesture.move(107, 100) is None
    assert gesture.move(100, 100) is None
    assert not gesture.due(1)


def test_exactly_100_pixels_during_recording_is_allowed():
    gesture = Gesture()
    gesture.press(1, 100, 100, 0)
    gesture.started(0.5)
    assert gesture.move(160, 180) is None
    assert gesture.recording
    assert gesture.release(1) == "stop"


def test_more_than_100_pixels_cancels_and_return_does_not_rearm():
    gesture = Gesture()
    gesture.press(1, 100, 100, 0)
    gesture.started(0.5)
    assert gesture.move(201, 100) == "cancel"
    assert gesture.move(100, 100) is None
    assert not gesture.recording
    assert not gesture.due(2)


def test_other_button_cannot_start_and_cancels_pending_gesture():
    gesture = Gesture()
    assert gesture.press(3, 100, 100, 0) is None
    assert not gesture.due(1)


def test_recording_watchdog_cancels_at_120_seconds():
    gesture = Gesture()
    gesture.press(1, 100, 100, 0)
    gesture.started(0.5)
    assert gesture.watchdog(120.49) is None
    assert gesture.watchdog(120.5) == "cancel"


def test_short_click_does_not_start_recording():
    gesture = Gesture()
    gesture.press(1, 100, 100, 0)
    assert gesture.release(1) is None
    assert not gesture.due(1)
