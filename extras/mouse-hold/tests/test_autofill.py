import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

from autofill import Autofill
from fill_worker import read_result, deliver
from fill_target import Target, safe_metadata, decode_transcript
from listener import Companion


class ResultTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "transcript"

    def result(self, text="中文测试\n", status="ok", chars=4):
        self.path.write_text(text)
        self.path.with_name("transcript.done").write_text(
            json.dumps({"status": status, "chars": chars}))

    def test_file_without_completion_never_delivers(self):
        self.path.write_text("半截")
        self.assertIsNone(read_result(self.path))

    def test_exact_chinese_result_removes_only_added_newline(self):
        self.result()
        self.assertEqual(read_result(self.path), ("ok", "中文测试"))

    def test_result_file_is_restricted_before_reading(self):
        self.result()
        self.path.chmod(0o644)
        self.assertEqual(read_result(self.path), ("ok", "中文测试"))
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)

    def test_original_final_newline_preserved(self):
        self.assertEqual(decode_transcript("中文\n", 3), "中文\n")

    def test_corrupt_or_mismatched_result_rejected(self):
        for status, chars in [("ok", 99), ("ok", True), ("ok", -1),
                              ("ok", "4"), ("error", 0), ("empty", 0)]:
            self.result(status=status, chars=chars)
            self.assertEqual(read_result(self.path)[0], "skip")

    def test_empty_transcript_not_inserted(self):
        self.result(text="\n", chars=0)
        self.assertEqual(read_result(self.path)[0], "skip")

    def test_clipboard_first_then_insert_into_target(self):
        copy, target = Mock(return_value=True), Mock()
        target.valid.return_value = True
        target.insert.return_value = True
        self.assertEqual(deliver("识别结果", target, copy, lambda: True), "filled")
        copy.assert_called_once_with("识别结果")
        target.insert.assert_called_once_with("识别结果")

    def test_generic_window_binds_clipboard_before_insert(self):
        from fill_worker import deliver
        copy, target, clipboard = Mock(return_value=True), Mock(), Mock()
        target.mode = "generic"
        target.bind_clipboard.return_value = True
        target.valid.return_value = True
        target.insert.return_value = True
        self.assertEqual(deliver("普通程序结果", target, copy, lambda: True,
                                 clipboard=clipboard), "filled")
        target.bind_clipboard.assert_called_once_with(clipboard)
        target.insert.assert_called_once_with("普通程序结果")

    def test_invalidated_session_only_copies(self):
        copy, target = Mock(return_value=True), Mock()
        self.assertEqual(deliver("结果", target, copy, lambda: False), "copied")
        copy.assert_called_once_with("结果")
        target.insert.assert_not_called()

    def test_changed_target_only_copies(self):
        target = Mock()
        target.mode = "direct"
        target.valid.return_value = False
        self.assertEqual(deliver("结果", target, Mock(return_value=True),
                                 lambda: True), "copied")
        target.insert.assert_not_called()

    def test_failed_copy_does_not_insert(self):
        target = Mock()
        self.assertEqual(deliver("结果", target, Mock(return_value=False),
                                 lambda: True), "copy_failed")
        target.insert.assert_not_called()

    def test_insert_error_is_not_retried(self):
        target = Mock()
        target.valid.return_value = True
        target.insert.side_effect = RuntimeError("接口失败")
        self.assertEqual(deliver("结果", target, Mock(return_value=True),
                                 lambda: True), "copied")
        target.insert.assert_called_once()

    def test_invalidated_during_checks_does_not_insert(self):
        target = Mock()
        target.valid.return_value = True
        safe = Mock(side_effect=[True, False])
        self.assertEqual(deliver("结果", target, Mock(return_value=True), safe), "copied")
        target.insert.assert_not_called()

    def test_unrelated_file_cannot_be_taken_as_this_recording(self):
        unrelated = self.path.with_name("different-recording")
        unrelated.write_text("别的结果\n")
        unrelated.with_name(unrelated.name + ".done").write_text(
            json.dumps({"status": "ok", "chars": 4}))
        self.assertIsNone(read_result(self.path))

    def test_partial_or_invalid_completion_cannot_deliver(self):
        self.path.write_text("中文测试\n")
        self.path.with_name("transcript.done").write_text('{"status":')
        self.assertEqual(read_result(self.path)[0], "skip")

    def test_lock_check_failure_denies_insert(self):
        from fill_worker import unlocked
        with patch("fill_worker.subprocess.check_output", side_effect=OSError):
            self.assertFalse(unlocked())
        for reply in ["(true,)", "", "unexpected"]:
            with patch("fill_worker.subprocess.check_output", return_value=reply):
                self.assertFalse(unlocked())

    def test_user_action_while_lock_query_waits_blocks_insertion(self):
        from fill_worker import run
        directory = self.path.parent
        self.result()
        (directory / "started").touch()
        (directory / "stopped").touch()
        target = Mock()
        target.mode = "direct"
        target.changed = False
        target.capture.return_value = True
        target.valid.return_value = True
        target.root.query_pointer.return_value.mask = 0
        replies = []
        def lock_reply():
            replies.append(True)
            if len(replies) == 2:
                (directory / "invalid").touch()
            return True
        with patch("fill_worker.capture_target", return_value=target), \
                patch("fill_worker.copy_clipboard", return_value=True), \
                patch("fill_worker.unlocked", side_effect=lock_reply):
            self.assertEqual(run(directory, 0, 0), 0)
        target.insert.assert_not_called()
        self.assertEqual(len(replies), 2)


class MetadataTests(unittest.TestCase):
    def test_only_nonpassword_editable_unselected_known_caret(self):
        valid = dict(password=False, editable=True, enabled=True,
                     visible=True, selections=0, caret=2, count=4)
        self.assertTrue(safe_metadata(**valid))
        for key, val in [("password", True), ("editable", False),
                         ("enabled", False), ("visible", False),
                         ("selections", 1), ("caret", -1),
                         ("caret", 5), ("count", -1)]:
            self.assertFalse(safe_metadata(**dict(valid, **{key: val})), key)

    def test_insertion_character_offset_and_utf8_byte_length(self):
        target = Target.__new__(Target)
        target.node = Mock()
        target.snapshot = (2, 4)
        self.assertTrue(target.insert("中文🙂"))
        target.node.get_editable_text_iface().insert_text.assert_called_once_with(
            2, "中文🙂", 10)
        target.node.get_text_iface.assert_not_called()

    def test_text_or_caret_or_selection_change_permanently_invalidates(self):
        for event_type in ["object:text-changed:insert", "object:text-changed:delete",
                           "object:text-caret-moved", "object:text-selection-changed"]:
            target = Target.__new__(Target)
            target.node = Mock()
            target.changed = False
            event = SimpleNamespace(type=event_type, source=target.node)
            target.event(event)
            self.assertTrue(target.changed)

    def test_verified_indicator_focus_is_not_a_user_target_change(self):
        target = Target.__new__(Target)
        target.node = Mock()
        target.changed = False
        other = Mock()
        other.get_process_id.return_value = 123
        event = SimpleNamespace(type="object:state-changed:focused",
                                source=other, detail1=1)
        with patch("fill_target.trusted_indicator", return_value=True):
            target.event(event)
        self.assertFalse(target.changed)
        with patch("fill_target.trusted_indicator", return_value=False):
            target.event(event)
        self.assertTrue(target.changed)

    def test_focus_lost_to_indicator_does_not_cancel_original_target(self):
        target = Target.__new__(Target)
        target.node = Mock()
        target.changed = False
        target.event(SimpleNamespace(type="object:state-changed:focused",
                                    source=target.node, detail1=0))
        self.assertFalse(target.changed)

    def test_only_original_or_verified_indicator_window_is_allowed(self):
        target = Target.__new__(Target)
        target.xid = 10
        target.root = Mock()
        target.display = Mock()
        target.property = Mock(return_value=10)
        self.assertTrue(target.window_allowed())
        target.property.return_value = 0
        self.assertFalse(target.window_allowed())
        target.property.side_effect = [20, 123]
        with patch("fill_target.trusted_indicator", return_value=True):
            self.assertTrue(target.window_allowed())
        target.property.side_effect = [20, 123]
        with patch("fill_target.trusted_indicator", return_value=False):
            self.assertFalse(target.window_allowed())


class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.manager = Autofill(runtime=Path(self.temp.name))
        self.addCleanup(self.manager.close)
        self.child = Mock()
        self.child.poll.return_value = None
        self.patch = patch("autofill.subprocess.Popen", return_value=self.child)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_workers_use_the_python_interpreter_running_the_listener(self):
        process = Mock()
        process.poll.return_value = None
        manager = Autofill(runtime=self.temp.name, require_unlock=False)
        with patch("autofill.subprocess.Popen", return_value=process) as popen:
            manager.press(12, 34)
        self.assertEqual(popen.call_args.args[0][0], sys.executable)

    def prepare(self):
        self.manager.press(100, 100)
        job = self.manager.current
        (job.directory / "ready").write_text("{}")
        return job

    def test_late_target_cannot_delay_start_or_enable_file_mode(self):
        self.manager.press(100, 100)
        self.assertEqual(self.manager.start_args(), [])

    def test_only_ready_target_gets_unique_file_and_no_submit(self):
        job = self.prepare()
        args = self.manager.start_args()
        self.assertIn("--file=" + str(job.directory / "transcript"), args)
        self.assertIn("--no-auto-submit", args)
        self.assertIn("--no-smart-auto-submit", args)
        self.manager.action("stop")
        self.assertTrue((job.directory / "stopped").exists())

    def test_cancel_never_marks_stopped(self):
        job = self.prepare()
        self.manager.start_args()
        self.manager.action("cancel")
        self.assertFalse((job.directory / "stopped").exists())
        self.assertTrue((job.directory / "cancelled").exists())

    def test_user_key_invalidates_without_cancelling_voice(self):
        job = self.prepare()
        self.manager.start_args()
        self.manager.invalidate()
        self.assertTrue((job.directory / "invalid").exists())
        self.assertFalse((job.directory / "cancelled").exists())

    def test_next_press_invalidates_previous_delivery(self):
        old = self.prepare()
        self.manager.start_args()
        self.manager.action("stop")
        self.manager.press(200, 200)
        self.assertTrue((old.directory / "invalid").exists())
        self.assertNotEqual(old.directory, self.manager.current.directory)

    def test_plain_clipboard_start_never_has_submit_override(self):
        self.assertEqual(self.manager.start_args(), [])

    def test_invalidated_before_start_keeps_original_output_mode(self):
        self.prepare()
        self.manager.invalidate()
        self.assertEqual(self.manager.start_args(), [])

    def test_failed_worker_cannot_receive_new_file_output(self):
        self.prepare()
        self.child.poll.return_value = 1
        self.assertEqual(self.manager.start_args(), [])

    def test_runtime_directory_is_private(self):
        job = self.prepare()
        self.assertEqual(job.directory.stat().st_mode & 0o777, 0o700)

    def test_reaped_job_files_are_removed_and_never_replayed(self):
        job = self.prepare()
        self.child.poll.return_value = 0
        self.manager.poll()
        self.assertFalse(job.directory.exists())
        self.assertFalse(self.manager.jobs)

    def test_crashed_worker_rescues_only_this_stopped_recording_to_clipboard(self):
        job = self.prepare()
        self.manager.start_args()
        self.manager.action("stop")
        self.child.poll.return_value = 1
        with patch("autofill.subprocess.Popen", return_value=Mock()) as spawn:
            self.manager.poll()
        self.assertIn("--copy-only", spawn.call_args.args[0])
        self.assertTrue((job.directory / "invalid").exists())
        self.assertTrue(job.directory.exists())

    def test_worker_crash_during_recording_keeps_job_until_mouse_release(self):
        job = self.prepare()
        self.manager.start_args()
        self.child.poll.return_value = 1
        self.manager.poll()
        self.assertIs(self.manager.current, job)
        self.assertIn(job, self.manager.jobs)
        self.manager.action("stop")
        self.assertTrue((job.directory / "stopped").exists())
        with patch("autofill.subprocess.Popen", return_value=Mock()) as spawn:
            self.manager.poll()
        self.assertIn("--copy-only", spawn.call_args.args[0])

    def test_cancelled_worker_is_not_rescued_or_replayed(self):
        job = self.prepare()
        self.manager.start_args()
        self.manager.action("cancel")
        self.child.poll.return_value = 1
        with patch("autofill.subprocess.Popen") as spawn:
            self.manager.poll()
        spawn.assert_not_called()


class ListenerIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.c = Companion.__new__(Companion)
        self.c.voxtype = "/test/voxtype"
        self.c.dry_run = False
        self.c.autofill = Mock()
        self.c.owns_recording = False

    def test_file_override_is_only_added_to_this_mouse_start(self):
        args = ["--file=/private/test/transcript", "--no-auto-submit"]
        self.c.autofill.start_args.return_value = args
        with patch("listener.subprocess.run") as run:
            self.c.command("start")
            run.assert_called_once_with(
                ["/test/voxtype", "record", "start"] + args,
                check=True, timeout=1, stdout=-3)
        with patch("listener.subprocess.run") as run:
            self.c.command("stop")
            self.assertEqual(run.call_args.args[0], ["/test/voxtype", "record", "stop"])
        self.c.autofill.action.assert_called_once_with("stop")

    def test_helper_failure_does_not_block_recording(self):
        self.c.autofill.start_args.side_effect = OSError
        with patch("listener.subprocess.run") as run:
            self.c.command("start")
            self.assertEqual(run.call_args.args[0], ["/test/voxtype", "record", "start"])

    def test_dry_run_never_invokes_voice_or_helper_output(self):
        self.c.dry_run = True
        with patch("listener.subprocess.run") as run:
            self.c.command("start")
        run.assert_not_called()
        self.c.autofill.start_args.assert_not_called()

    def test_key_event_only_invalidates_fill_not_voice(self):
        import queue
        from gesture import Gesture
        self.c.events = queue.Queue()
        self.c.gesture = Gesture()
        self.c.gesture.started(0)
        self.c.events.put(("key", 0, 0, 0, 1))
        with patch("listener.subprocess.run") as run:
            self.c.drain()
        run.assert_not_called()
        self.c.autofill.invalidate.assert_called_once()
        self.assertTrue(self.c.gesture.recording)

if __name__ == "__main__":
    unittest.main()
