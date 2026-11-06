"""Global hold policy: no control, application or focus dependency."""
import queue
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from gesture import Gesture
from listener import Companion


class GlobalHoldTests(unittest.TestCase):
    def setUp(self):
        self.c = Companion.__new__(Companion)
        self.c.gesture = Gesture()
        self.c.events = queue.Queue()
        self.c.target = None
        self.c.last_check = 0
        self.c.root = Mock()
        self.c.root.query_pointer.return_value = SimpleNamespace(root_x=100, root_y=100, mask=256)
        self.c.command = Mock()
        self.c.idle = Mock(return_value=True)
        self.c.unlocked = Mock(return_value=True)
        self.c.active = Mock(side_effect=AssertionError('must not inspect focus'))
        self.c.probe = Mock(side_effect=AssertionError('must not inspect controls'))
        self.c.gesture.press(1, 100, 100, 0)

    def tick(self, now):
        with patch('listener.time.monotonic', return_value=now):
            self.c.tick(now)

    def actions(self):
        return [args.args[0] for args in self.c.command.call_args_list if args.args[0]]

    def test_half_second_threshold(self):
        self.tick(.499)
        self.assertEqual(self.actions(), [])
        self.tick(.5)
        self.assertEqual(self.actions(), ['start'])

    def test_no_focus_or_input_field_required(self):
        self.tick(1.01)
        self.assertTrue(self.c.gesture.recording)
        self.c.active.assert_not_called()
        self.c.probe.assert_not_called()

    def test_focus_change_does_not_cancel_recording(self):
        self.tick(1.01)
        self.tick(1.6)
        self.assertEqual(self.actions(), ['start'])
        self.assertTrue(self.c.gesture.recording)

    def test_release_stops_even_without_focus(self):
        self.tick(1.01)
        self.c.events.put(('release', 1, 100, 100, 2))
        self.c.drain()
        self.assertEqual(self.actions(), ['start', 'stop'])

    def test_physical_release_before_event_stops_exactly_once(self):
        self.tick(1.01)
        self.c.root.query_pointer.return_value.mask = 0
        self.tick(1.3)
        self.c.events.put(('release', 1, 100, 100, 1.3))
        self.c.drain()
        self.assertEqual(self.actions(), ['start', 'stop'])
        self.assertFalse(self.c.gesture.recording)

    def test_drag_never_starts_even_after_return(self):
        self.c.move(120, 100)
        self.c.move(100, 100)
        self.tick(2)
        self.assertEqual(self.actions(), [])

    def test_drag_during_recording_does_not_cancel(self):
        self.tick(1.01)
        self.c.root.query_pointer.return_value.root_x = 120
        self.tick(1.2)
        self.assertEqual(self.actions(), ['start'])
        self.assertTrue(self.c.gesture.recording)

    def test_large_move_from_pointer_poll_cancels_once_without_stop(self):
        self.tick(1.01)
        self.c.root.query_pointer.return_value.root_x = 121
        self.tick(1.2)
        self.assertEqual(self.actions(), ['start', 'cancel'])
        self.assertFalse(self.c.gesture.recording)
        self.c.root.query_pointer.return_value.root_x = 100
        self.tick(2)
        self.c.events.put(('release', 1, 100, 100, 2.1))
        self.c.drain()
        self.assertEqual(self.actions(), ['start', 'cancel'])

    def test_large_move_event_cancels_before_queued_release(self):
        self.tick(1.01)
        self.c.events.put(('move', 0, 171, 171, 1.1))
        self.c.events.put(('release', 1, 171, 171, 1.2))
        self.c.drain()
        self.assertEqual(self.actions(), ['start', 'cancel'])

    def test_release_position_over_radius_cancels_even_without_move_event(self):
        self.tick(1.01)
        self.c.events.put(('release', 1, 121, 100, 1.2))
        self.c.drain()
        self.assertEqual(self.actions(), ['start', 'cancel'])

    def test_busy_voice_is_not_interrupted(self):
        self.c.idle.return_value = False
        self.tick(1.01)
        self.assertEqual(self.actions(), [])

    def test_locked_screen_denies_start(self):
        self.c.unlocked.return_value = False
        self.tick(1.01)
        self.assertEqual(self.actions(), [])

    def test_lock_during_recording_cancels(self):
        self.tick(1.01)
        self.c.unlocked.return_value = False
        self.tick(1.6)
        self.assertEqual(self.actions(), ['start', 'cancel'])

    def test_transient_lock_check_failure_does_not_cancel_recording(self):
        self.tick(1.01)
        self.c.unlocked.return_value = None
        self.tick(1.6)
        self.assertEqual(self.actions(), ['start'])
        self.assertTrue(self.c.gesture.recording)

    def test_release_arriving_during_start_checks_denies_start(self):
        def release():
            self.c.events.put(('release', 1, 100, 100, 1.01))
            return True
        self.c.unlocked.side_effect = release
        self.tick(1.01)
        self.assertEqual(self.actions(), [])

    def test_other_button_denies_start(self):
        self.c.root.query_pointer.return_value.mask = 256 | 1024
        self.tick(1.01)
        self.assertEqual(self.actions(), [])
