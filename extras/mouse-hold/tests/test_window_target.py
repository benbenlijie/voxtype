"""Window compatibility safety checks; no real desktop input."""
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from Xlib import X
from window_target import WindowTarget, trusted_chatgpt, trusted_target


class IdentityTests(unittest.TestCase):
    def test_only_installed_chatgpt_of_current_user_is_approved(self):
        with patch("window_target.os.stat", return_value=SimpleNamespace(st_uid=os.getuid())), \
             patch("window_target.os.readlink", return_value="/usr/lib/chatgpt/ChatGPT"):
            self.assertTrue(trusted_chatgpt(123))

    def test_other_program_and_other_user_are_rejected(self):
        for uid, exe in [(os.getuid(), "/usr/bin/bash"),
                         (os.getuid() + 1, "/usr/lib/chatgpt/ChatGPT")]:
            with patch("window_target.os.stat", return_value=SimpleNamespace(st_uid=uid)), \
                 patch("window_target.os.readlink", return_value=exe):
                self.assertFalse(trusted_chatgpt(123))

    def test_exited_process_is_rejected(self):
        with patch("window_target.os.stat", side_effect=FileNotFoundError):
            self.assertFalse(trusted_chatgpt(123))

    def test_current_users_other_gui_program_is_approved_for_ctrl_v(self):
        with patch("window_target.os.stat",
                   return_value=SimpleNamespace(st_uid=os.getuid())), \
             patch("window_target.os.readlink",
                   return_value="/usr/bin/firefox"):
            self.assertEqual(trusted_target(123), "generic")

    def test_other_user_gui_program_is_rejected(self):
        with patch("window_target.os.stat",
                   return_value=SimpleNamespace(st_uid=os.getuid() + 1)), \
             patch("window_target.os.readlink",
                   return_value="/usr/bin/firefox"):
            self.assertIsNone(trusted_target(123))


class WindowTests(unittest.TestCase):
    def setUp(self):
        self.t = WindowTarget.__new__(WindowTarget)
        self.t.display = Mock()
        self.t.root = Mock()
        self.t.window = Mock()
        self.t.window.get_attributes.return_value.map_state = X.IsViewable
        self.t.xid, self.t.pid, self.t.focus_xid = 11, 123, 12
        self.t.start = "start"
        self.t.changed = False
        self.t.last_active = 11
        self.t.clipboard_owner = 55
        self.t.clipboard = Mock()
        self.t.clipboard.owner_matches.return_value = True
        self.t.clipboard_atom, self.t.active_atom = 77, 99
        self.t.mode = "window"
        self.t.control, self.t.v_key = 37, 55
        self.t.shift, self.t.insert_key = 50, 118
        self.t.guard = Mock(return_value=True)
        self.t.barrier = Mock(return_value=True)
        self.t.property = Mock(side_effect=lambda w, n: 11 if w is self.t.root else 123)
        self.t.process_start = Mock(return_value="start")
        self.t.display.pending_events.return_value = 0
        self.t.display.get_input_focus.return_value.focus.id = 12
        self.t.display.get_selection_owner.return_value.id = 55
        self.t.display.query_keymap.return_value = bytes(32)
        self.t.root.query_pointer.return_value.mask = 0
        self.approved = patch("window_target.trusted_chatgpt", return_value=True)
        self.approved.start()
        self.addCleanup(self.approved.stop)

    def test_same_window_and_focus_are_valid(self):
        self.assertTrue(self.t.valid())

    def test_diagnostic_names_active_window_change(self):
        self.t.property = Mock(return_value=90)
        self.assertFalse(self.t.valid())
        self.assertEqual(self.t.rejection_reason, "活动窗口发生变化")

    def test_diagnostic_names_focus_change_without_reading_text(self):
        self.t.display.get_input_focus.return_value.focus.id = 13
        self.assertFalse(self.t.valid())
        self.assertEqual(self.t.rejection_reason, "键盘焦点发生变化")

    def test_diagnostic_retains_first_focus_event_metadata(self):
        self.t.display.pending_events.side_effect = [2, 1, 0]
        self.t.display.next_event.side_effect = [
            SimpleNamespace(type=X.FocusOut, mode=X.NotifyGrab, detail=X.NotifyAncestor),
            SimpleNamespace(type=X.PropertyNotify, atom=99)]
        self.assertFalse(self.t.valid())
        self.assertEqual(self.t.rejection_reason,
                         "窗口收到失焦事件（模式=1，细节=0）")

    def test_diagnostic_names_barrier_failure_without_injection(self):
        self.t.barrier.return_value = False
        with patch("window_target.xtest.fake_input") as fake:
            self.assertFalse(self.t.insert("不能出现在日志中的识别原文"))
        self.assertEqual(self.t.rejection_reason, "鼠标键盘监听未确认")
        fake.assert_not_called()

    def test_diagnostic_names_held_keys_without_key_identity(self):
        self.t.display.query_keymap.return_value = bytes([1]) + bytes(31)
        with patch("window_target.xtest.fake_input") as fake:
            self.assertFalse(self.t.insert("不能出现在日志中的识别原文"))
        self.assertEqual(self.t.rejection_reason, "仍有键盘按键处于按下状态")
        fake.assert_not_called()

    def test_different_active_window_is_rejected(self):
        self.t.property = Mock(return_value=90)
        self.assertFalse(self.t.valid())

    def test_changed_focus_in_same_window_is_rejected(self):
        self.t.display.get_input_focus.return_value.focus.id = 13
        self.assertFalse(self.t.valid())

    def test_reused_process_is_rejected(self):
        self.t.process_start.return_value = "another-start"
        self.assertFalse(self.t.valid())

    def test_destroyed_or_hidden_window_is_rejected(self):
        self.t.window.get_attributes.return_value.map_state = X.IsUnmapped
        self.assertFalse(self.t.valid())

    def test_leave_and_return_notifications_are_not_ignored(self):
        self.t.active_atom = 99
        self.t.display.pending_events.side_effect = [2, 1, 0]
        self.t.display.next_event.side_effect = [
            SimpleNamespace(type=X.PropertyNotify, atom=99),
            SimpleNamespace(type=X.PropertyNotify, atom=99)]
        self.t.pump()
        self.assertTrue(self.t.changed)

    def test_focus_out_rejects_even_if_focus_has_returned(self):
        self.t.display.pending_events.side_effect = [1, 0]
        self.t.display.next_event.return_value = SimpleNamespace(type=X.FocusOut)
        self.t.pump()
        self.assertTrue(self.t.changed)

    def test_copy_owner_changed_before_paste_is_rejected(self):
        self.t.display.get_selection_owner.return_value.id = 56
        self.assertFalse(self.t.insert("本次结果"))

    def test_held_key_or_mouse_button_prevents_paste(self):
        for keys, mask in [(bytes([1]) + bytes(31), 0), (bytes(32), 256),
                           (bytes(32), X.ControlMask)]:
            self.t.display.query_keymap.return_value = keys
            self.t.root.query_pointer.return_value.mask = mask
            self.assertFalse(self.t.insert("本次结果"))

    def test_invalidated_after_previous_checks_prevents_paste(self):
        self.t.guard.return_value = False
        self.assertFalse(self.t.insert("本次结果"))

    def test_no_paste_if_clipboard_owner_was_not_bound(self):
        self.t.clipboard_owner = None
        self.assertFalse(self.t.insert("本次结果"))

    def test_unverified_copy_process_is_never_trusted(self):
        self.t.clipboard.owner_matches.return_value = False
        with patch("window_target.xtest.fake_input") as fake:
            self.assertFalse(self.t.insert("本次结果"))
        fake.assert_not_called()

    def test_copy_process_exits_during_listener_ack_never_pastes(self):
        def ack():
            self.t.clipboard.owner_matches.return_value = False
            return True
        self.t.barrier.side_effect = ack
        with patch("window_target.xtest.fake_input") as fake:
            self.assertFalse(self.t.insert("本次结果"))
        fake.assert_not_called()
        self.t.display.ungrab_server.assert_called_once()

    def test_binding_without_proof_never_adopts_current_clipboard(self):
        self.assertFalse(self.t.bind_clipboard(None))
        self.assertIsNone(self.t.clipboard_owner)
        self.t.display.get_selection_owner.assert_not_called()

    def test_binding_uses_proven_owner_not_current_owner(self):
        clipboard = Mock(owner_id=55)
        clipboard.owner_matches.return_value = True
        self.assertTrue(self.t.bind_clipboard(clipboard))
        self.assertIs(self.t.clipboard, clipboard)
        self.assertEqual(self.t.clipboard_owner, 55)
        clipboard.owner_matches.assert_called_once_with(self.t.display)

    def test_one_ctrl_v_and_no_enter_or_focus_restoration(self):
        with patch("window_target.xtest.fake_input") as fake:
            self.assertTrue(self.t.insert("本次结果"))
        self.assertEqual([call.args[1:] for call in fake.call_args_list],
                         [(X.KeyPress, 37), (X.KeyPress, 55),
                          (X.KeyRelease, 55), (X.KeyRelease, 37)])
        self.t.display.grab_server.assert_called_once()

    def test_generic_gui_window_uses_one_ctrl_v(self):
        self.t.mode = "generic"
        with patch("window_target.trusted_target", return_value="generic"), \
             patch("window_target.xtest.fake_input") as fake:
            self.assertTrue(self.t.insert("普通程序结果"))
        self.assertEqual([call.args[1:] for call in fake.call_args_list],
                         [(X.KeyPress, 37), (X.KeyPress, 55),
                          (X.KeyRelease, 55), (X.KeyRelease, 37)])

    def test_terminal_uses_shift_insert(self):
        self.t.mode = "terminal"
        self.t.shift = 50
        self.t.insert_key = 118
        self.t.terminal_keys = (50, 118)
        with patch("window_target.trusted_target", return_value="terminal"), \
             patch("window_target.xtest.fake_input") as fake:
            self.assertTrue(self.t.insert("终端结果"))
        self.assertEqual([call.args[1:] for call in fake.call_args_list],
                         [(X.KeyPress, 50), (X.KeyPress, 118),
                          (X.KeyRelease, 118), (X.KeyRelease, 50)])
        self.t.display.ungrab_server.assert_called_once()
        self.t.window.set_input_focus.assert_not_called()

    def test_failure_releases_control_and_ungrabs_server_without_retry(self):
        def send(_display, kind, code):
            if kind == X.KeyPress and code == 55:
                raise RuntimeError("测试失败")
        with patch("window_target.xtest.fake_input", side_effect=send) as fake:
            with self.assertRaises(RuntimeError):
                self.t.insert("本次结果")
        self.assertEqual([call.args[1:] for call in fake.call_args_list],
                         [(X.KeyPress, 37), (X.KeyPress, 55),
                          (X.KeyRelease, 55), (X.KeyRelease, 37)])
        self.t.display.ungrab_server.assert_called_once()

    def test_no_listener_ack_never_injects(self):
        self.t.barrier.return_value = False
        with patch("window_target.xtest.fake_input") as fake:
            self.assertFalse(self.t.insert("结果"))
        fake.assert_not_called()

    def test_repeated_v_release_error_still_releases_ctrl(self):
        def send(_display, kind, code):
            if kind == X.KeyRelease and code == 55:
                raise RuntimeError("松开 V 失败")
        with patch("window_target.xtest.fake_input", side_effect=send) as fake:
            with self.assertRaises(RuntimeError):
                self.t.insert("结果")
        self.assertIn((X.KeyRelease, 37),
                      [call.args[1:] for call in fake.call_args_list])


class SelectionTests(unittest.TestCase):
    def test_logs_exact_delivery_stage_but_never_transcript_or_exception_text(self):
        from fill_worker import deliver
        secret = "不能出现在日志中的识别原文"
        for stage in ("clipboard", "safe1", "target", "safe2", "insert", "exception"):
            with self.subTest(stage=stage):
                target = Mock(mode="window", rejection_reason="测试拒绝原因")
                target.bind_clipboard.return_value = stage != "clipboard"
                target.valid.return_value = stage != "target"
                target.insert.return_value = False
                if stage == "exception":
                    target.insert.side_effect = RuntimeError(secret)
                safe = Mock(side_effect=([False] if stage == "safe1" else
                                         [True, False] if stage == "safe2" else
                                         [True, True]))
                expected = {
                    "clipboard": "剪贴板归属未确认",
                    "safe1": "第一次安全检查未通过",
                    "target": "目标检查未通过：测试拒绝原因",
                    "safe2": "第二次安全检查未通过",
                    "insert": "粘贴前检查未通过：测试拒绝原因",
                    "exception": "粘贴检查异常：RuntimeError",
                }[stage]
                with self.assertLogs("voxtype-mouse-hold", level="INFO") as logs:
                    self.assertEqual(deliver(secret, target, lambda _: True,
                                             safe, clipboard=Mock()), "copied")
                self.assertIn(expected, "\n".join(logs.output))
                self.assertNotIn(secret, "\n".join(logs.output))
                self.assertLessEqual(target.insert.call_count, 1)

    def test_chatgpt_does_not_need_accessibility_registration(self):
        from fill_worker import capture_target
        compat = Mock()
        compat.capture.return_value = True
        with patch("fill_worker.WindowTarget", return_value=compat), \
             patch("fill_worker.Target") as direct:
            self.assertIs(capture_target(100, 200), compat)
        direct.assert_not_called()

    def test_other_software_keeps_existing_direct_target(self):
        from fill_worker import capture_target
        compat, direct = Mock(), Mock()
        compat.capture.return_value = False
        direct.capture.return_value = True
        with patch("fill_worker.WindowTarget", return_value=compat), \
             patch("fill_worker.Target", return_value=direct):
            self.assertIs(capture_target(100, 200), direct)
        compat.close.assert_called_once()

    def test_generic_window_is_fallback_when_direct_accessibility_is_unavailable(self):
        from fill_worker import capture_target
        compat, direct = Mock(), Mock()
        compat.capture.return_value = True
        compat.mode = "generic"
        direct.capture.return_value = False
        with patch("fill_worker.WindowTarget", return_value=compat), \
             patch("fill_worker.Target", return_value=direct):
            self.assertIs(capture_target(100, 200), compat)
        direct.close.assert_called_once()

    def test_clipboard_owner_bound_after_copy_not_before(self):
        from fill_worker import deliver
        events = []
        target = Mock()
        target.mode = "window"
        clipboard = Mock()
        target.bind_clipboard.side_effect = lambda proof: events.append("bind") or True
        target.valid.return_value = True
        target.insert.side_effect = lambda text: events.append("paste") or True
        self.assertEqual(deliver("结果", target,
                                 lambda text: events.append("copy") or True,
                                 lambda: True, clipboard=clipboard), "filled")
        target.bind_clipboard.assert_called_once_with(clipboard)
        self.assertEqual(events, ["copy", "bind", "paste"])

    def test_unproven_copy_is_not_pasted(self):
        from fill_worker import deliver
        target = Mock(mode="window")
        target.bind_clipboard.return_value = False
        self.assertEqual(deliver("结果", target, lambda text: True,
                                 lambda: True), "copied")
        target.insert.assert_not_called()

    def test_window_paste_error_is_never_retried(self):
        from fill_worker import deliver
        target = Mock()
        target.mode = "window"
        target.valid.return_value = True
        target.insert.side_effect = RuntimeError("可能已经发出粘贴")
        self.assertEqual(deliver("结果", target, Mock(return_value=True),
                                 lambda: True), "copied")
        target.insert.assert_called_once()


if __name__ == "__main__":
    unittest.main()
