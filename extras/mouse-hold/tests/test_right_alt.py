"""右 Alt 共用回填，但不与鼠标争用录音。"""
import queue
from unittest.mock import Mock, patch
from listener import Companion
from gesture import Gesture


def companion():
    c = Companion.__new__(Companion)
    c.gesture = Gesture()
    c.events = queue.Queue()
    c.alt_state = None
    c.alt_started = 0
    c.command = Mock()
    c.fill = Mock(return_value=True)
    c.idle = Mock(return_value=True)
    c.unlocked = Mock(return_value=True)
    c.alt_down = Mock(return_value=True)
    return c


def test_alt_captures_focused_window_and_stops_once():
    c = companion()
    c.alt_press(1)
    c.fill.assert_any_call('press_focused')
    c.alt_tick(1.1)
    c.command.assert_called_once_with('start')
    c.alt_press(1.2)  # 重复按下不重新捕获或录音
    c.alt_release()
    c.alt_release()
    assert [x.args for x in c.command.call_args_list] == [('start',), ('stop',)]


def test_short_tap_does_not_start_recording():
    c = companion()
    c.alt_press(1)
    c.alt_release()
    c.command.assert_not_called()
    c.fill.assert_any_call('discard_pending')


def test_mouse_recording_ignores_alt():
    c = companion()
    c.gesture.recording = True
    c.alt_press(1)
    assert c.alt_state is None
    c.command.assert_not_called()


def test_alt_watchdog_cancels():
    c = companion()
    c.alt_state = 'recording'
    c.alt_started = 1
    c.alt_tick(62)
    c.command.assert_called_once_with('cancel')
    assert c.alt_state is None


def test_physical_release_stops_without_queued_event():
    c = companion()
    c.alt_state = 'recording'
    c.alt_started = 1
    c.alt_down.return_value = False
    c.alt_tick(2)
    c.command.assert_called_once_with('stop')


def test_keyboard_recording_mouse_press_invalidates_without_new_capture():
    c = companion()
    c.alt_state = 'recording'
    c.events.put(('press', 1, 10, 10, 2))
    c.drain()
    c.fill.assert_called_once_with('invalidate')
    assert not c.gesture.pending


def test_focused_worker_does_not_probe_mouse_target():
    from fill_worker import capture_target
    with patch('fill_worker.WindowTarget') as cls, patch('fill_worker.Target') as direct:
        cls.return_value.capture.return_value = True
        assert capture_target(0, 0, focused=True) is cls.return_value
        cls.return_value.capture.assert_called_once_with(0, 0, focused=True)
        direct.assert_not_called()


def test_watchdog_requires_release_before_next_recording():
    c = companion()
    c.alt_state = 'recording'
    c.alt_started = 1
    c.alt_tick(62)
    c.alt_press(63)
    assert c.alt_state is None
    c.alt_release()
    c.alt_press(64)
    assert c.alt_state == 'pending'


def test_lock_screen_cancels_keyboard_recording():
    c = companion()
    c.alt_state = 'recording'
    c.alt_started = 1
    c.last_check = 1
    c.unlocked.return_value = False
    c.alt_tick(2)
    c.command.assert_called_once_with('cancel')


def test_capture_deadline_falls_back_to_clipboard_recording():
    c = companion()
    c.fill.return_value = False
    c.alt_press(1)
    c.alt_tick(1.2)
    c.command.assert_not_called()
    c.alt_tick(1.6)
    c.command.assert_called_once_with('start')
