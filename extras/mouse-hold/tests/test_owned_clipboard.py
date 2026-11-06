"""Unit tests never connect to a desktop; opt-in tests create their own Xvfb."""
import ctypes
import os
import select
import shutil
import subprocess
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import owned_clipboard as module
from owned_clipboard import OwnedClipboard, query_client_pid


class ClipboardTests(unittest.TestCase):
    def setUp(self):
        self.display = Mock()
        self.display.get_display_name.return_value = ":owned-test"
        self.display.intern_atom.return_value = 77
        self.display.get_selection_owner.return_value = SimpleNamespace(id=20)
        self.child = Mock(pid=4321)
        self.child.poll.return_value = None
        self.popen = Mock(return_value=self.child)
        self.pid_query = Mock(return_value=4321)
        self.writer = patch("owned_clipboard._write_stdin", return_value=True)
        self.write = self.writer.start()
        self.addCleanup(self.writer.stop)
        self.helper = OwnedClipboard(
            self.display, popen=self.popen, owner_pid=self.pid_query, timeout=.03)

    def test_verified_transfer_binds_owner_and_actual_child_pid(self):
        self.assertTrue(self.helper.copy("中文🙂\n"))
        self.assertEqual(self.helper.owner_id, 20)
        self.assertEqual(self.helper.expected_pid, 4321)
        self.assertTrue(self.helper.owner_matches(self.display))
        self.assertEqual(self.write.call_args.args[:2],
                         (self.child.stdin, "中文🙂\n".encode()))

    def test_xclip_is_foreground_and_uses_the_explicit_display(self):
        self.assertTrue(self.helper.copy("本次结果"))
        args, kwargs = self.popen.call_args
        self.assertEqual(args[0], [
            "xclip", "-quiet", "-selection", "clipboard", "-in",
            "-loops", "0", "-display", ":owned-test"])
        self.assertEqual(kwargs["stdin"], subprocess.PIPE)
        self.assertEqual(kwargs["stdout"], subprocess.DEVNULL)
        self.assertEqual(kwargs["stderr"], subprocess.DEVNULL)
        self.assertTrue(kwargs["start_new_session"])

    def test_competing_owner_between_copy_and_bind_is_not_trusted(self):
        self.pid_query.return_value = 999
        self.assertTrue(self.helper.copy("本次结果"))
        self.assertIsNone(self.helper.owner_id)
        self.assertFalse(self.helper.owner_matches(self.display))

    def test_owner_replaced_during_pid_query_is_not_bound(self):
        def replace(*_args, **_kwargs):
            self.display.get_selection_owner.return_value.id = 21
            return 4321
        self.pid_query.side_effect = replace
        self.assertTrue(self.helper.copy("本次结果"))
        self.assertIsNone(self.helper.owner_id)
        self.assertFalse(self.helper.owner_matches(self.display))

    def test_library_failure_leaves_copy_alive_but_disables_paste(self):
        self.pid_query.return_value = None
        self.assertTrue(self.helper.copy("本次结果"))
        self.assertFalse(self.helper.owner_matches(self.display))
        self.child.terminate.assert_not_called()
        self.child.kill.assert_not_called()

    def test_probe_exception_is_fail_closed_without_losing_copy(self):
        self.pid_query.side_effect = OSError
        self.assertTrue(self.helper.copy("本次结果"))
        self.assertFalse(self.helper.owner_matches(self.display))

    def test_owner_change_is_permanently_invalid_even_after_return(self):
        self.assertTrue(self.helper.copy("本次结果"))
        self.display.get_selection_owner.return_value.id = 21
        self.assertFalse(self.helper.owner_matches(self.display))
        self.display.get_selection_owner.return_value.id = 20
        self.assertFalse(self.helper.owner_matches(self.display))

    def test_final_check_never_opens_a_second_connection(self):
        self.assertTrue(self.helper.copy("本次结果"))
        self.pid_query.reset_mock()
        with patch("owned_clipboard.subprocess.run",
                   side_effect=AssertionError("最终检查不得另开连接")):
            self.assertTrue(self.helper.owner_matches(self.display))
        self.pid_query.assert_not_called()
        self.display.get_full_property.assert_not_called()
        self.display.convert_selection.assert_not_called()

    def test_other_connection_is_rejected_even_with_same_numeric_owner(self):
        self.assertTrue(self.helper.copy("本次结果"))
        self.assertFalse(self.helper.owner_matches(Mock()))

    def test_exited_child_is_rejected_even_if_xid_and_pid_are_reused(self):
        self.assertTrue(self.helper.copy("本次结果"))
        self.child.poll.return_value = 0
        self.assertFalse(self.helper.owner_matches(self.display))

    def test_failed_final_owner_query_is_fail_closed(self):
        self.assertTrue(self.helper.copy("本次结果"))
        self.display.get_selection_owner.side_effect = OSError
        self.assertFalse(self.helper.owner_matches(self.display))

    def test_close_never_kills_or_waits_for_clipboard_process(self):
        self.assertTrue(self.helper.copy("本次结果"))
        self.helper.close()
        self.helper.close()
        self.assertFalse(self.helper.owner_matches(self.display))
        self.child.terminate.assert_not_called()
        self.child.kill.assert_not_called()
        self.child.wait.assert_not_called()

    def test_missing_command_and_broken_input_do_not_enable_paste(self):
        self.popen.side_effect = FileNotFoundError
        self.assertFalse(self.helper.copy("本次结果"))
        self.assertFalse(self.helper.owner_matches(self.display))
        self.popen.side_effect = None
        helper = OwnedClipboard(self.display, popen=self.popen)
        self.write.return_value = False
        self.assertFalse(helper.copy("本次结果"))
        self.assertFalse(helper.owner_matches(self.display))
        self.child.terminate.assert_not_called()

    def test_single_use_prevents_rebinding_a_previous_result(self):
        self.assertTrue(self.helper.copy("第一次"))
        self.assertFalse(self.helper.copy("第二次"))
        self.assertFalse(self.helper.owner_matches(self.display))
        self.popen.assert_called_once()

    def test_unexpected_writer_exception_closes_stdin_without_killing_copy(self):
        self.write.side_effect = RuntimeError("模拟输入传输异常")
        self.assertFalse(self.helper.copy("本次结果"))
        self.child.stdin.close.assert_called_once()
        self.assertFalse(self.helper.owner_matches(self.display))
        self.child.terminate.assert_not_called()
        self.child.kill.assert_not_called()
        self.child.wait.assert_not_called()

    def test_invalid_or_oversized_text_never_starts_xclip(self):
        for text in (None, b"text", "", " \n", "a\0b", "\ud800",
                     "a" * (module.MAX_BYTES + 1)):
            with self.subTest(text_type=type(text).__name__):
                helper = OwnedClipboard(self.display, popen=self.popen)
                self.assertFalse(helper.copy(text))
        self.popen.assert_not_called()


class PipeTests(unittest.TestCase):
    def test_utf8_bytes_are_written_and_stdin_is_closed(self):
        read_fd, write_fd = os.pipe()
        stream = os.fdopen(write_fd, "wb", buffering=0)
        try:
            payload = "中文🙂\n".encode()
            self.assertTrue(module._write_stdin(
                stream, payload, time.monotonic() + 1))
            self.assertTrue(stream.closed)
            self.assertEqual(os.read(read_fd, 128), payload)
        finally:
            stream.close()
            os.close(read_fd)

    def test_full_pipe_times_out_and_closes_without_killing_any_process(self):
        read_fd, write_fd = os.pipe()
        stream = os.fdopen(write_fd, "wb", buffering=0)
        try:
            start = time.monotonic()
            self.assertFalse(module._write_stdin(
                stream, b"x" * module.MAX_BYTES, start + .03))
            self.assertTrue(stream.closed)
            self.assertLess(time.monotonic() - start, .5)
        finally:
            stream.close()
            os.close(read_fd)


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.display = Mock()
        self.display.get_display_name.return_value = ":owned-test"

    def test_probe_has_explicit_display_and_timeout_and_returns_only_pid(self):
        reply = SimpleNamespace(returncode=0, stdout="4321\n")
        with patch("owned_clipboard.subprocess.run", return_value=reply) as run:
            self.assertEqual(query_client_pid(self.display, 20, timeout=.2), 4321)
        args, kwargs = run.call_args
        self.assertEqual(args[0][-3:], ["--owner-pid", ":owned-test", "20"])
        self.assertEqual(kwargs["timeout"], .2)

    def test_timeout_or_unavailable_probe_is_unknown_not_trusted(self):
        for error in (OSError(), subprocess.TimeoutExpired("probe", .01)):
            with patch("owned_clipboard.subprocess.run", side_effect=error):
                self.assertIsNone(query_client_pid(self.display, 20))
        for output, code in (("", 0), ("-1", 0), ("0", 0),
                             ("4321", 1), ("4321\n9999", 0)):
            reply = SimpleNamespace(returncode=code, stdout=output)
            with patch("owned_clipboard.subprocess.run", return_value=reply):
                self.assertIsNone(query_client_pid(self.display, 20))

    def test_native_probe_without_libraries_or_display_fails_closed(self):
        with patch("owned_clipboard._load_xres", return_value=None):
            self.assertIsNone(module._native_client_pid(":owned-test", 20))
        x11, xres = Mock(), Mock()
        x11.XOpenDisplay.return_value = None
        with patch("owned_clipboard._load_xres", return_value=(x11, xres)):
            self.assertIsNone(module._native_client_pid(":owned-test", 20))
        xres.XResQueryClientIds.assert_not_called()

    def test_ctypes_abi_returns_pid_and_frees_native_results(self):
        x11, xres = Mock(), Mock()
        x11.XOpenDisplay.return_value = 123
        xres.XResQueryExtension.return_value = 1
        pid = ctypes.c_uint32(4321)
        values = (module._ClientIdValue * 1)()
        values[0].spec.mask = 2
        values[0].length = 4
        values[0].value = ctypes.cast(ctypes.pointer(pid), ctypes.c_void_p)

        def version(_display, major, minor):
            ctypes.cast(major, ctypes.POINTER(ctypes.c_int))[0] = 1
            ctypes.cast(minor, ctypes.POINTER(ctypes.c_int))[0] = 2
            return 1

        def query(_display, count, specs, count_out, values_out):
            spec = ctypes.cast(specs, ctypes.POINTER(module._ClientIdSpec))[0]
            self.assertEqual((count, spec.client, spec.mask), (1, 20, 2))
            ctypes.cast(count_out, ctypes.POINTER(ctypes.c_long))[0] = 1
            ctypes.cast(values_out, ctypes.POINTER(
                ctypes.POINTER(module._ClientIdValue)))[0] = values
            return 0  # Success == 0 here, unlike XResQueryVersion.

        xres.XResQueryVersion.side_effect = version
        xres.XResQueryClientIds.side_effect = query
        xres.XResGetClientPid.return_value = 4321
        with patch("owned_clipboard._load_xres", return_value=(x11, xres)):
            self.assertEqual(module._native_client_pid(":owned-test", 20), 4321)
        xres.XResClientIdsDestroy.assert_called_once()
        x11.XCloseDisplay.assert_called_once_with(123)

    def test_missing_or_old_extension_is_rejected_and_connection_closed(self):
        for available, minor in ((0, 2), (1, 1)):
            x11, xres = Mock(), Mock()
            x11.XOpenDisplay.return_value = 123
            xres.XResQueryExtension.return_value = available
            def version(_display, major, minor_out):
                ctypes.cast(major, ctypes.POINTER(ctypes.c_int))[0] = 1
                ctypes.cast(minor_out, ctypes.POINTER(ctypes.c_int))[0] = minor
                return 1
            xres.XResQueryVersion.side_effect = version
            with patch("owned_clipboard._load_xres", return_value=(x11, xres)):
                self.assertIsNone(module._native_client_pid(":owned-test", 20))
            xres.XResQueryClientIds.assert_not_called()
            x11.XCloseDisplay.assert_called_once()


@unittest.skipUnless(os.environ.get("VOXTYPE_OWNED_XVFB") == "1",
                     "显式开启时才创建独立 Xvfb")
class PrivateXvfbTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.xclip = shutil.which("xclip")
        if not cls.xclip or not shutil.which("Xvfb"):
            raise unittest.SkipTest("缺少 xclip 或 Xvfb")
        read_fd, write_fd = os.pipe()
        try:
            cls.server = subprocess.Popen(
                ["Xvfb", "-displayfd", str(write_fd), "-screen", "0",
                 "640x480x24", "-nolisten", "tcp", "-ac"],
                pass_fds=(write_fd,), stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL)
            cls.addClassCleanup(cls.stop_server)
            os.close(write_fd)
            write_fd = None
            if not select.select([read_fd], [], [], 5)[0]:
                raise AssertionError("独立 Xvfb 未启动")
            number = os.read(read_fd, 64).decode().strip()
            if not number.isdecimal():
                raise AssertionError("独立显示编号无效")
            cls.display_name = ":" + number
        finally:
            os.close(read_fd)
            if write_fd is not None:
                os.close(write_fd)

    @classmethod
    def stop_server(cls):
        cls.server.terminate()
        try:
            cls.server.wait(timeout=3)
        except subprocess.TimeoutExpired:
            cls.server.kill()
            cls.server.wait(timeout=3)

    def setUp(self):
        from Xlib import display
        self.display = display.Display(self.display_name)
        self.addCleanup(self.display.close)
        self.children = []
        self.addCleanup(self.release_test_clipboard)

    def release_test_clipboard(self):
        from Xlib import X
        root = self.display.screen().root
        window = root.create_window(0, 0, 1, 1, 0,
                                    self.display.screen().root_depth)
        window.set_selection_owner(
            self.display.intern_atom("CLIPBOARD"), X.CurrentTime)
        self.display.sync()
        for child in self.children:
            child.wait(timeout=3)
        window.destroy()
        self.display.sync()

    def test_real_xres_verifies_xclip_and_close_preserves_ownership(self):
        helper = OwnedClipboard(self.display, xclip=self.xclip, timeout=2)
        self.assertTrue(helper.copy("仅独立显示的合成文本🙂"))
        self.children.append(helper._process)
        self.assertIsNotNone(helper.owner_id)
        self.assertEqual(query_client_pid(self.display, helper.owner_id),
                         helper.expected_pid)
        self.display.grab_server()
        try:
            self.display.sync()
            self.assertTrue(helper.owner_matches(self.display))
        finally:
            self.display.ungrab_server()
            self.display.sync()
        original = helper.owner_id
        helper.close()
        self.assertIsNone(helper._process.poll())
        owner = self.display.get_selection_owner(
            self.display.intern_atom("CLIPBOARD"))
        self.assertEqual(owner.id, original)

    def test_unknown_xres_retains_copy_but_never_permits_paste(self):
        helper = OwnedClipboard(
            self.display, xclip=self.xclip,
            owner_pid=lambda *_args, **_kwargs: None)
        self.assertTrue(helper.copy("仅独立显示的合成结果"))
        self.children.append(helper._process)
        self.assertIsNone(helper.owner_id)
        self.assertFalse(helper.owner_matches(self.display))
        helper.close()
        self.assertIsNone(helper._process.poll())


if __name__ == "__main__":
    unittest.main()
