"""Opt-in X11 compatibility for ChatGPT and terminal windows."""
import os
from pathlib import Path

from Xlib import X, XK, display
from Xlib.ext import xtest


def trusted_chatgpt(pid):
    try:
        process = f"/proc/{pid}"
        return (os.stat(process).st_uid == os.getuid()
                and os.readlink(process + "/exe") == "/usr/lib/chatgpt/ChatGPT")
    except (OSError, ValueError):
        return False


TERMINAL_EXECUTABLES = {
    "alacritty", "foot", "gnome-terminal-server", "guake", "kitty",
    "kgx", "konsole", "lxterminal", "mate-terminal", "qterminal",
    "st", "terminator", "tilix", "urxvt", "wezterm-gui", "xfce4-terminal",
    "xterm",
}
SHIFT_INSERT_TERMINALS = {"st", "urxvt", "xterm"}


def trusted_terminal(pid):
    try:
        process = f"/proc/{pid}"
        if os.stat(process).st_uid != os.getuid():
            return False
        executable = os.path.basename(os.readlink(process + "/exe"))
        return executable in TERMINAL_EXECUTABLES
    except (OSError, ValueError):
        return False


def trusted_user_window(pid):
    """Allow one-shot paste into a window owned by the current user."""
    try:
        return os.stat(f"/proc/{pid}").st_uid == os.getuid()
    except (OSError, ValueError):
        return False


def trusted_target(pid):
    if trusted_chatgpt(pid):
        return "window"
    if trusted_terminal(pid):
        return "terminal"
    return "generic" if trusted_user_window(pid) else None


def terminal_paste_keys(display, pid):
    """Return the paste shortcut supported by the known terminal family."""
    executable = os.path.basename(os.readlink(f"/proc/{pid}/exe"))
    if executable in SHIFT_INSERT_TERMINALS:
        return (
            display.keysym_to_keycode(XK.string_to_keysym("Shift_L")),
            display.keysym_to_keycode(XK.string_to_keysym("Insert")),
        )
    return (
        display.keysym_to_keycode(XK.string_to_keysym("Control_L")),
        display.keysym_to_keycode(XK.string_to_keysym("Shift_L")),
        display.keysym_to_keycode(XK.string_to_keysym("v")),
    )


def window_id(value):
    return value.id if hasattr(value, "id") else int(value)


class WindowTarget:
    mode = "window"

    def __init__(self):
        self.display = display.Display()
        self.root = self.display.screen().root
        self.active_atom = self.display.intern_atom("_NET_ACTIVE_WINDOW")
        self.clipboard_atom = self.display.intern_atom("CLIPBOARD")
        self.changed = False
        self.change_reason = None
        self.rejection_reason = None
        self.clipboard_owner = None
        self.clipboard = None
        self.guard = lambda: True
        self.barrier = lambda: False  # No listener acknowledgement, no paste.
        self.control = self.display.keysym_to_keycode(XK.string_to_keysym("Control_L"))
        self.shift = self.display.keysym_to_keycode(XK.string_to_keysym("Shift_L"))
        self.v_key = self.display.keysym_to_keycode(XK.string_to_keysym("v"))
        self.insert_key = self.display.keysym_to_keycode(
            XK.string_to_keysym("Insert"))
        self.terminal_keys = ()

    def property(self, window, name):
        value = window.get_full_property(self.display.intern_atom(name),
                                         X.AnyPropertyType)
        return int(value.value[0]) if value is not None and len(value.value) else 0

    def process_start(self):
        return Path(f"/proc/{self.pid}/stat").read_text().rsplit(")", 1)[1].split()[19]

    def mark_changed(self, reason):
        # Keep only fixed check names and numeric event metadata, never text.
        if not self.changed:
            self.change_reason = reason
        self.changed = True

    def reject(self, reason):
        self.rejection_reason = reason
        return False

    def capture(self, x, y):
        self.xid = self.property(self.root, "_NET_ACTIVE_WINDOW")
        if not self.xid:
            return False
        self.window = self.display.create_resource_object("window", self.xid)
        self.pid = self.property(self.window, "_NET_WM_PID")
        self.mode = trusted_target(self.pid)
        if not self.mode:
            return False
        if not self.display.has_extension("XTEST"):
            return False
        if self.mode in {"window", "generic"} and (not self.control or not self.v_key):
            return False
        if self.mode == "terminal":
            try:
                self.terminal_keys = terminal_paste_keys(self.display, self.pid)
            except (OSError, ValueError):
                return False
            if not all(self.terminal_keys):
                return False
        modifiers = self.display.get_modifier_mapping()
        if self.control not in modifiers[2]:
            return False
        self.start = self.process_start()
        # x,y is only used to check the original press, never to click again.
        point = self.root.translate_coords(self.window, 0, 0)
        bounds = self.window.get_geometry()
        if not (point.x <= x < point.x + bounds.width
                and point.y <= y < point.y + bounds.height):
            return False
        focus = self.display.get_input_focus().focus
        self.focus_xid = window_id(focus)
        node = focus
        for _ in range(32):
            if not hasattr(node, "query_tree"):
                return False
            if node.id == self.xid:
                break
            if node.id == self.root.id:
                return False
            node = node.query_tree().parent
        else:
            return False
        self.last_active = self.xid
        self.root.change_attributes(event_mask=X.PropertyChangeMask)
        self.window.change_attributes(event_mask=X.StructureNotifyMask | X.FocusChangeMask)
        if self.focus_xid != self.xid:
            focus.change_attributes(event_mask=X.StructureNotifyMask | X.FocusChangeMask)
        self.display.sync()
        return self.valid()

    def pump(self):
        # A leave-and-return is unsafe too. Property notifications are retained
        # even if the current active window has already become the old one.
        count = 0
        while self.display.pending_events():
            count += 1
            if count > 256:
                self.mark_changed("窗口事件过多")
                break
            event = self.display.next_event()
            if event.type == X.PropertyNotify and event.atom == self.active_atom:
                self.mark_changed("活动窗口属性发生变化")
            elif event.type == X.FocusOut:
                self.mark_changed("窗口收到失焦事件（模式=%s，细节=%s）" %
                                  (getattr(event, "mode", -1),
                                   getattr(event, "detail", -1)))
            elif event.type == X.DestroyNotify:
                self.mark_changed("原窗口已销毁")
            elif event.type == X.UnmapNotify:
                self.mark_changed("原窗口已隐藏")
        if self.property(self.root, "_NET_ACTIVE_WINDOW") != self.xid:
            self.mark_changed("活动窗口发生变化")

    def valid(self):
        try:
            self.pump()
            if self.changed:
                return self.reject(getattr(self, "change_reason", None)
                                   or "窗口历史状态已失效")
            if trusted_target(self.pid) != self.mode:
                return self.reject("原目标窗口进程身份无法确认")
            if self.process_start() != self.start:
                return self.reject("原进程已经更换")
            if self.property(self.window, "_NET_WM_PID") != self.pid:
                return self.reject("窗口所属进程发生变化")
            if self.window.get_attributes().map_state != X.IsViewable:
                return self.reject("原窗口不可见")
            if window_id(self.display.get_input_focus().focus) != self.focus_xid:
                return self.reject("键盘焦点发生变化")
            return True
        except Exception as exc:
            self.mark_changed("窗口检查异常：" + type(exc).__name__)
            return self.reject(self.change_reason or "窗口检查不可用")

    def bind_clipboard(self, clipboard):
        # Never treat an arbitrary current owner as our recording's copy.
        # The helper proves its foreground xclip process owns this X window.
        self.clipboard_owner = None
        self.clipboard = None
        if clipboard is None or not clipboard.owner_matches(self.display):
            return self.reject("剪贴板归属未确认")
        self.clipboard_owner = clipboard.owner_id
        self.clipboard = clipboard
        return bool(self.clipboard_owner)

    def insert(self, _text):
        # The caller copied this recording and bound its clipboard owner.
        # Serialise the final X11 focus checks and key requests against other
        # clients. This cannot promise application-level field identity.
        pressed = []
        grabbed = False
        try:
            self.display.grab_server()
            grabbed = True
            self.display.sync()
            if not self.valid():
                return False
            if (not self.clipboard_owner or self.clipboard is None
                    or not self.clipboard.owner_matches(self.display)
                    or window_id(self.display.get_selection_owner(self.clipboard_atom))
                    != self.clipboard_owner):
                return self.reject("粘贴前剪贴板归属发生变化")
            if not self.barrier():
                return self.reject("鼠标键盘监听未确认")
            if any(self.display.query_keymap()):
                return self.reject("仍有键盘按键处于按下状态")
            if self.root.query_pointer().mask & ~18:
                return self.reject("仍有鼠标按钮或修饰键处于按下状态")
            if not self.guard():
                return self.reject("本次录音的回填许可已失效")
            # The foreground copy process may exit while awaiting the reader.
            # Recheck immediately before injection, still under the same grab.
            if not self.clipboard.owner_matches(self.display):
                return self.reject("等待监听确认期间复制进程或剪贴板发生变化")
            keys = (self.terminal_keys if self.mode == "terminal"
                    else (self.control, self.v_key))
            for code in keys:
                # An uncertain failed request may already have pressed the key.
                pressed.append(code)
                xtest.fake_input(self.display, X.KeyPress, code)
            while pressed:
                code = pressed[-1]
                xtest.fake_input(self.display, X.KeyRelease, code)
                pressed.pop()
            self.display.sync()
            return True  # Shortcut dispatched, not proof the field accepted it.
        finally:
            try:
                for code in reversed(pressed):
                    try:
                        xtest.fake_input(self.display, X.KeyRelease, code)
                    except Exception:
                        pass  # Always continue with the other key, especially Ctrl.
            finally:
                if grabbed:
                    self.display.ungrab_server()
                    self.display.sync()

    def close(self):
        self.display.close()
