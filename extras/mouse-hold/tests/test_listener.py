import subprocess
import unittest
from unittest.mock import patch
from listener import Companion


class ListenerSafetyTests(unittest.TestCase):
    def setUp(self):
        self.c = Companion.__new__(Companion)
        self.c.voxtype = "/test/voxtype"
        self.c.dry_run = False
        self.c.owns_recording = False
        self.c.require_unlock = True

    def test_cancel_logs_reason_without_field_content(self):
        from gesture import Gesture
        from unittest.mock import Mock
        self.c.gesture = Gesture()
        self.c.gesture.started(0)
        self.c.target = {"path": "/example"}
        self.c.command = Mock()
        with self.assertLogs("voxtype-mouse-hold", level="INFO") as logs:
            self.c.cancel("活动窗口改变")
        self.assertIn("活动窗口改变", " ".join(logs.output))
        self.c.command.assert_called_once_with("cancel")

    def test_start_tracks_ownership_before_uncertain_timeout(self):
        with patch("listener.subprocess.run", side_effect=subprocess.TimeoutExpired("test", 1)):
            with self.assertRaises(subprocess.TimeoutExpired):
                self.c.command("start")
        self.assertTrue(self.c.owns_recording)

    def test_failed_stop_retains_ownership_for_final_cleanup(self):
        self.c.owns_recording = True
        with patch("listener.subprocess.run", side_effect=subprocess.CalledProcessError(1, "test")):
            with self.assertRaises(subprocess.CalledProcessError):
                self.c.command("stop")
        self.assertTrue(self.c.owns_recording)
        with patch("listener.subprocess.run"):
            self.c.command("cancel")
        self.assertFalse(self.c.owns_recording)

    def test_unavailable_voxtype_is_not_idle(self):
        with patch("listener.subprocess.check_output", side_effect=OSError):
            self.assertFalse(self.c.idle())

    def test_only_idle_status_allows_start(self):
        for status in ["recording", "transcribing", "", "unknown"]:
            with patch("listener.subprocess.check_output", return_value=status):
                self.assertFalse(self.c.idle())
        with patch("listener.subprocess.check_output", return_value="idle\n"):
            self.assertTrue(self.c.idle())

    def test_indicator_prepared_before_start_and_stop_not_after(self):
        from unittest.mock import Mock
        self.c.display, self.c.root = Mock(), Mock()
        order = []
        with patch("listener.prepare_indicator", create=True,
                   side_effect=lambda *_: order.append("prepare") or 1) as prepare, \
             patch("listener.subprocess.run",
                   side_effect=lambda args, **_: order.append(args[2])):
            self.c.command("start")
            self.c.command("stop")
        self.assertEqual(order, ["prepare", "start", "prepare", "stop"])
        self.assertEqual(prepare.call_count, 2)
        prepare.assert_called_with(self.c.display, self.c.root)

    def test_indicator_preparation_error_never_bypasses_fill_checks_or_blocks_voice(self):
        from unittest.mock import Mock
        self.c.display, self.c.root = Mock(), Mock()
        with patch("listener.prepare_indicator", create=True,
                   side_effect=RuntimeError("测试")):
            with patch("listener.subprocess.run") as run:
                self.c.command("start")
        run.assert_called_once()
        self.assertTrue(self.c.owns_recording)

    def test_dry_run_never_changes_indicator(self):
        self.c.dry_run = True
        with patch("listener.prepare_indicator", create=True) as prepare, \
             patch("listener.subprocess.run") as run:
            self.c.command("start")
        prepare.assert_not_called()
        run.assert_not_called()

    def test_locked_or_unavailable_lock_service_denies_start(self):
        for status in ["(true,)", "", "unexpected"]:
            with patch("listener.subprocess.check_output", return_value=status):
                self.assertFalse(self.c.unlocked())
        with patch("listener.subprocess.check_output", side_effect=OSError):
            self.assertIsNone(self.c.unlocked())
        with patch("listener.subprocess.check_output", return_value="(false,)\n"):
            self.assertTrue(self.c.unlocked())


if __name__ == "__main__":
    unittest.main()
