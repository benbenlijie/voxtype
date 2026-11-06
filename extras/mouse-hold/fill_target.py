"""Retain one AT-SPI object and metadata, never read existing field text."""
from pathlib import Path
import logging
import time

from indicator import trusted_indicator
LOG = logging.getLogger("voxtype-mouse-hold")


def safe_metadata(*, password, editable, enabled, visible, selections, caret, count):
    return (not password and editable and enabled and visible
            and selections == 0 and 0 <= caret <= count)


def decode_transcript(text, chars):
    if type(chars) is not int or chars <= 0 or "\0" in text:
        return None
    if len(text) == chars:
        return text
    if len(text) == chars + 1 and text.endswith("\n"):
        return text[:-1]
    return None


class Target:
    def __init__(self):
        import gi
        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi, GLib
        from Xlib import display
        self.api = Atspi
        self.context = GLib.MainContext.default()
        Atspi.set_timeout(70, 70)
        self.display = display.Display()
        self.root = self.display.screen().root
        self.node = None
        self.changed = False
        self.listener = Atspi.EventListener.new(self.event)
        self.event_types = ["object:text-changed", "object:text-caret-moved",
                            "object:text-selection-changed",
                            "object:state-changed:focused",
                            "object:state-changed:defunct"]
        for name in self.event_types:
            if not self.listener.register(name):
                raise RuntimeError("无法监测输入框变化")

    def pump(self):
        for _ in range(256):
            if not self.context.pending():
                break
            self.context.iteration(False)
        if self.node is not None and not self.window_allowed():
            self.changed = True

    def event(self, event, *_):
        # Do not access event.any_data (it may contain application text).
        if self.node is None:
            return
        try:
            if event.type.startswith("object:state-changed:focused"):
                if event.detail1 and event.source != self.node:
                    if not trusted_indicator(event.source.get_process_id()):
                        self.changed = True
            elif event.source == self.node:
                self.changed = True
        except Exception:
            self.changed = True

    def property(self, window, name):
        from Xlib import X
        value = window.get_full_property(self.display.intern_atom(name),
                                         X.AnyPropertyType)
        return int(value.value[0]) if value is not None and len(value.value) else 0

    def process_start(self):
        return Path(f"/proc/{self.pid}/stat").read_text().rsplit(")", 1)[1].split()[19]

    def window_allowed(self):
        try:
            active = self.property(self.root, "_NET_ACTIVE_WINDOW")
            if active == self.xid:
                return True
            if not active:
                return False
            window = self.display.create_resource_object("window", active)
            return trusted_indicator(self.property(window, "_NET_WM_PID"))
        except Exception:
            return False

    def metadata(self, node):
        A = self.api
        node.clear_cache()
        states = node.get_state_set()
        contains = lambda name: states.contains(getattr(A.StateType, name))
        parent = node
        password = False
        for _ in range(32):
            if parent is None:
                break
            if parent.get_role() == A.Role.PASSWORD_TEXT:
                password = True
                break
            parent = parent.get_parent()
        else:
            return None
        text = node.get_text_iface()
        interfaces = node.get_interfaces()
        if not text or "EditableText" not in interfaces:
            LOG.info("回填检查：控件未提供可编辑文字接口")
            return None
        caret, count = text.get_caret_offset(), text.get_character_count()
        if not safe_metadata(
                password=password, editable=contains("EDITABLE"),
                enabled=contains("ENABLED") and contains("SENSITIVE"),
                visible=contains("VISIBLE") and contains("SHOWING")
                and not contains("DEFUNCT"),
                selections=text.get_n_selections(), caret=caret, count=count):
            LOG.info("回填检查：密码、不可编辑、不可见、选区或光标状态不符合要求")
            return None
        return caret, count

    def capture(self, x, y):
        A = self.api
        self.xid = self.property(self.root, "_NET_ACTIVE_WINDOW")
        if not self.xid:
            LOG.info("回填检查：没有活动窗口")
            return False
        self.window = self.display.create_resource_object("window", self.xid)
        self.pid = self.property(self.window, "_NET_WM_PID")
        if not self.pid or trusted_indicator(self.pid):
            LOG.info("回填检查：原窗口身份不可确认")
            return False
        self.start = self.process_start()
        deadline = time.monotonic() + .32
        desktop = A.get_desktop(0)
        for i in range(min(desktop.get_child_count(), 128)):
            if time.monotonic() > deadline:
                break
            app = desktop.get_child_at_index(i)
            if app.get_process_id() != self.pid:
                continue
            for j in range(min(app.get_child_count(), 40)):
                if time.monotonic() > deadline:
                    break
                frame = app.get_child_at_index(j)
                states = frame.get_state_set()
                if not states.contains(A.StateType.ACTIVE):
                    LOG.info("回填检查：辅助功能窗口不是活动窗口")
                    continue
                frame.get_relation_set()  # Activate Chromium's lazy tree.
                node = frame
                for _ in range(24):
                    if time.monotonic() > deadline:
                        LOG.info("回填检查：定位输入框超时")
                        return False
                    component = node.get_component_iface()
                    if not component:
                        break
                    child = component.get_accessible_at_point(x, y, A.CoordType.SCREEN)
                    if child is None or child == node:
                        break
                    node = child
                for _ in range(12):
                    if node is None or time.monotonic() > deadline:
                        break
                    states = node.get_state_set()
                    if node.get_role() == A.Role.PASSWORD_TEXT:
                        LOG.info("回填检查：密码框不回填")
                        return False
                    if (states.contains(A.StateType.EDITABLE)
                            and states.contains(A.StateType.FOCUSED)):
                        component = node.get_component_iface()
                        if not component or not component.contains(x, y, A.CoordType.SCREEN):
                            LOG.info("回填检查：鼠标不在输入框范围")
                            return False
                        metadata = self.metadata(node)
                        if metadata is None:
                            return False
                        self.pump()  # Ignore notifications preceding this snapshot.
                        self.node = node
                        self.snapshot = metadata
                        return self.valid()
                    node = node.get_parent()
        LOG.info("回填检查：软件未登记输入框，或此位置不是已聚焦的可编辑控件")
        return False

    def valid(self):
        self.pump()
        if self.changed or self.node is None:
            return False
        if self.process_start() != self.start:
            return False
        if self.property(self.window, "_NET_WM_PID") != self.pid:
            return False
        if self.node.get_process_id() != self.pid:
            return False
        if self.metadata(self.node) != self.snapshot:
            return False
        if self.property(self.root, "_NET_ACTIVE_WINDOW") == self.xid:
            if not self.node.get_state_set().contains(self.api.StateType.FOCUSED):
                return False
        return not self.changed

    def insert(self, text):
        editable = self.node.get_editable_text_iface()
        # AT-SPI position uses characters; length uses UTF-8 bytes.
        # No keyboard shortcuts, focus changes, coordinate clicks, or Enter.
        return bool(editable.insert_text(self.snapshot[0], text,
                                         len(text.encode("utf-8"))))

    def close(self):
        for name in self.event_types:
            self.listener.deregister(name)
        self.display.close()
