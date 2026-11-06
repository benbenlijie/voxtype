#!/usr/bin/python3
"""X11-only, passive mouse-hold companion for Voxtype."""
import argparse
import fcntl
import logging
import os
from pathlib import Path
import queue
import signal
import subprocess
import threading
import time

from gesture import Gesture
from autofill import Autofill
from indicator import prepare_indicator

LOG = logging.getLogger("voxtype-mouse-hold")
FORBIDDEN_MASK = 1 | 4 | 8 | 32 | 64 | 128 | 512 | 1024 | 2048 | 4096


class Companion:
    def __init__(self, voxtype, dry_run=False, require_unlock=True, autofill=True, right_alt=False):
        from Xlib import display
        self.display = display.Display()
        self.root = self.display.screen().root
        self.voxtype = voxtype
        self.dry_run = dry_run
        self.require_unlock = require_unlock
        self.gesture = Gesture()
        self.alt_state = None
        self.alt_blocked = False
        self.alt_started = 0
        self.alt_codes = set()
        if right_alt:
            from Xlib import XK
            self.alt_codes = {self.display.keysym_to_keycode(XK.string_to_keysym(name))
                              for name in ("Alt_R", "ISO_Level3_Shift")}
            self.alt_codes.discard(0)
            if not self.alt_codes:
                raise RuntimeError("无法找到右侧 Alt，保留原设置后重试")
            LOG.info("右侧 Alt 已接入安全回填；按键编号=%s", sorted(self.alt_codes))
        self.events = queue.Queue(maxsize=4096)
        self.overflow = threading.Event()
        self.reader_failed = threading.Event()
        self.running = True
        self.last_check = 0
        self.owns_recording = False
        # Unmapped private window: receives only the paste synchronization marker.
        self.barrier_window = self.root.create_window(
            0, 0, 1, 1, 0, self.display.screen().root_depth)
        self.barrier_atom = self.display.intern_atom("_VOXTYPE_PASTE_BARRIER")
        self.display.sync()
        self.autofill = (Autofill(require_unlock=require_unlock,
                                 barrier_window=self.barrier_window.id)
                         if autofill and not dry_run else None)
        if not self.dry_run:
            self.protect_indicator()

    def protect_indicator(self):
        # Fix the indicator itself, never restore focus or weaken target checks.
        # The installed helper ignores every window not owned by our known OSD.
        try:
            if prepare_indicator(self.display, self.root):
                LOG.info("已将语音提示窗口设为不接收键盘焦点")
        except Exception as exc:
            LOG.warning("语音提示窗口防抢焦点检查失败：%s；保留回填安全检查",
                        type(exc).__name__)

    def fill(self, method, *args):
        manager = getattr(self, "autofill", None)
        if manager:
            try:
                return getattr(manager, method)(*args)
            except Exception as exc:
                LOG.warning("回填助手不可用：%s；不影响全局录音",
                            type(exc).__name__)
        return None

    def command(self, action):
        if not action:
            return
        if action == "start":
            # A timed-out command may already have signalled Voxtype.
            self.owns_recording = True
        if self.dry_run:
            LOG.info("试运行：%s", action)
        else:
            if action in {"start", "stop"}:
                self.protect_indicator()
            extra = (self.fill("start_args") or []) if action == "start" else []
            subprocess.run([self.voxtype, "record", action] + extra, check=True,
                           timeout=1, stdout=subprocess.DEVNULL)
            LOG.info("辅助录音：%s", action)
        if action in {"stop", "cancel"}:
            self.owns_recording = False
            self.fill("action", action)

    def move(self, x, y):
        action = self.gesture.move(x, y)
        if action == "cancel":
            LOG.info("取消原因：鼠标距最初按下位置超过 %s 像素",
                     self.gesture.recording_radius)
        self.command(action)

    def idle(self):
        try:
            return subprocess.check_output(
                [self.voxtype, "status"], text=True, timeout=.5,
                stderr=subprocess.DEVNULL,
            ).strip() == "idle"
        except (OSError, subprocess.SubprocessError):
            return False

    def unlocked(self):
        if not self.require_unlock:
            return True
        try:
            result = subprocess.check_output([
                "gdbus", "call", "--session", "--dest", "org.gnome.ScreenSaver",
                "--object-path", "/org/gnome/ScreenSaver",
                "--method", "org.gnome.ScreenSaver.GetActive",
            ], timeout=1.0, text=True, stderr=subprocess.DEVNULL)
            return result.strip() == "(false,)"
        except subprocess.TimeoutExpired:
            LOG.warning("锁屏检查超时：1 秒内未收到系统回复")
            # 临时的 D-Bus 延迟不等于屏幕已锁定。录音继续进行；结束时
            # 的安全检查仍要求重新确认当前会话确实处于解锁状态。
            return None
        except (OSError, subprocess.SubprocessError) as exc:
            LOG.warning("锁屏检查失败：%s", type(exc).__name__)
            return None

    def cancel(self, reason="安全检查未通过"):
        if self.gesture.recording:
            LOG.info("取消原因：%s", reason)
        self.command(self.gesture.abort())

    def alt_down(self):
        keys = self.display.query_keymap()
        return any(keys[code // 8] & (1 << (code % 8)) for code in self.alt_codes)

    def alt_press(self, now):
        if self.alt_state or getattr(self, "alt_blocked", False):
            return
        if self.gesture.pending or self.gesture.recording:
            self.alt_blocked = True
            return
        self.alt_state = "pending"
        self.alt_started = now
        self.fill("press_focused")

    def alt_release(self):
        self.alt_blocked = False
        state = self.alt_state
        self.alt_state = None
        if state == "recording":
            self.command("stop")
        elif state == "pending":
            self.fill("discard_pending")

    def alt_tick(self, now):
        if not getattr(self, "alt_state", None):
            return
        if not self.alt_down():
            self.alt_release()
            return
        if self.alt_state == "pending":
            # Let the private worker capture keyboard focus before recording.
            if not self.fill("prepared") and now - self.alt_started < .5:
                return
            if not self.idle() or self.unlocked() is not True:
                self.alt_release()
                self.alt_blocked = True
                return
            # Queries above can be slow; never start after physical release.
            if not self.alt_down():
                self.alt_release()
                return
            self.command("start")
            self.alt_state = "recording"
            self.alt_started = time.monotonic()
            self.last_check = self.alt_started
        elif now - self.alt_started >= 60:
            self.alt_blocked = True
            self.alt_state = None
            self.command("cancel")
        elif now - self.last_check >= .45:
            if self.unlocked() is False:
                self.alt_blocked = True
                self.alt_state = None
                self.command("cancel")
            self.last_check = time.monotonic()

    def drain(self):
        while True:
            try:
                kind, button, x, y, timestamp = self.events.get_nowait()
            except queue.Empty:
                return
            if kind == "alt_press":
                self.alt_press(timestamp)
            elif kind == "alt_release":
                # X11 auto-repeat emits release/press while physically held.
                if not self.alt_down():
                    self.alt_release()
            elif kind == "press":
                self.fill("invalidate")
                if getattr(self, "alt_state", None):
                    continue
                self.command(self.gesture.press(button, x, y, timestamp))
                if button == 1 and self.gesture.pending:
                    self.fill("press", x, y)
            elif kind == "key":
                # Observe only that a key was pressed, never its code or text.
                self.fill("invalidate")
            elif kind == "move":
                self.move(x, y)
            elif kind == "release" and button == 1:
                self.finish(x, y)

    def finish(self, x, y):
        # Physical state can update before the RECORD reader queues release.
        # Both routes must produce one normal stop, not discard the audio.
        self.move(x, y)
        self.command(self.gesture.release(1))

    def tick(self, now):
        """Global gesture checks; no focus or accessibility queries."""
        self.alt_tick(now)
        if getattr(self, "alt_state", None):
            return
        self.command(self.gesture.watchdog(now))
        if self.gesture.pending or self.gesture.recording:
            pointer = self.root.query_pointer()
            self.move(pointer.root_x, pointer.root_y)
            if pointer.mask & FORBIDDEN_MASK:
                self.cancel("检测到其他按键；状态=%s" % pointer.mask)
            elif not pointer.mask & 256:
                self.finish(pointer.root_x, pointer.root_y)
        if self.gesture.due(now):
            if not self.idle():
                LOG.info("长按未启动：原语音程序并非空闲")
                self.gesture.reject()
                return
            if self.unlocked() is not True:
                LOG.info("长按未启动：屏幕已锁定或无法确认锁屏状态")
                self.gesture.reject()
                return
            # Status/lock queries can take time; drain releases and drags
            # before starting, then require the physical button still down.
            self.drain()
            pointer = self.root.query_pointer()
            self.move(pointer.root_x, pointer.root_y)
            if (self.gesture.due(time.monotonic()) and pointer.mask & 256
                    and not pointer.mask & FORBIDDEN_MASK):
                self.command("start")
                self.gesture.started(time.monotonic())
                self.last_check = time.monotonic()
            else:
                LOG.info("长按未启动：检查期间已松开、移动或按下其他键")
                self.gesture.reject()
        elif self.gesture.recording and now - self.last_check >= .45:
            lock_check = self.unlocked()
            if lock_check is False:
                self.cancel("录音期间确认屏幕已锁定")
            elif lock_check is None:
                LOG.info("录音期间锁屏检查暂不可用；继续录音，结束时重新检查")
            self.last_check = time.monotonic()

    def read_events(self):
        from Xlib import X, display
        from Xlib.ext import record
        from Xlib.protocol import rq
        try:
            connection = display.Display()
            if not connection.has_extension("RECORD"):
                raise RuntimeError("桌面不支持 RECORD")
            context = connection.record_create_context(0, [record.AllClients], [{
                "core_requests": (0, 0), "core_replies": (0, 0),
                "ext_requests": (0, 0, 0, 0), "ext_replies": (0, 0, 0, 0),
                "delivered_events": (X.ClientMessage, X.ClientMessage),
                # Key presses invalidate auto-fill; no key identity is retained.
                "device_events": (X.KeyPress, X.MotionNotify),
                "errors": (0, 0), "client_started": False, "client_died": False,
            }])

            def callback(reply):
                if reply.category != record.FromServer or reply.client_swapped:
                    return
                data = reply.data
                while data:
                    event, data = rq.EventField(None).parse_binary_value(
                        data, connection.display, None, None)
                    if event.type == X.ClientMessage:
                        if (event.client_type == self.barrier_atom
                                and event.window.id == self.barrier_window.id
                                and event.data[0] == 32):
                            self.fill("ack_barrier", int(event.data[1][0]))
                        continue
                    if (event.type in {X.KeyPress, X.KeyRelease}
                            and event.detail in getattr(self, "alt_codes", set())):
                        kind = "alt_press" if event.type == X.KeyPress else "alt_release"
                        if kind == "alt_press" and not self.alt_state:
                            self.fill("invalidate")
                        try:
                            self.events.put_nowait((kind, 0, 0, 0, time.monotonic()))
                        except queue.Full:
                            self.overflow.set()
                        continue
                    if event.type == X.KeyPress:
                        self.fill("invalidate")
                        try:
                            self.events.put_nowait(("key", 0, 0, 0, time.monotonic()))
                        except queue.Full:
                            self.overflow.set()
                        continue
                    kind = {
                        X.ButtonPress: "press", X.ButtonRelease: "release",
                        X.MotionNotify: "move",
                    }.get(event.type)
                    if kind:
                        if kind == "press":
                            self.fill("invalidate")
                        try:
                            self.events.put_nowait((
                                kind, event.detail, event.root_x, event.root_y,
                                time.monotonic(),
                            ))
                        except queue.Full:
                            self.overflow.set()

            connection.record_enable_context(context, callback)
        except Exception:
            LOG.exception("鼠标监听停止，禁用本次运行")
        finally:
            self.reader_failed.set()

    def run(self):
        threading.Thread(target=self.read_events, daemon=True).start()
        LOG.info("已启动：任意位置左键原地长按 0.5 秒；启动前移动取消；录音中距按下位置超过 100 像素取消；松开结束；回填=%s",
                 "启用" if self.autofill else "关闭")
        try:
            while self.running and not self.reader_failed.is_set():
                if self.overflow.is_set():
                    raise RuntimeError("鼠标事件过多，安全退出")
                self.drain()
                while self.display.pending_events():
                    self.display.next_event()  # Consume our synchronization markers.
                self.fill("poll")
                self.tick(time.monotonic())
                if (not self.gesture.pending and not self.gesture.recording
                        and not getattr(self, "alt_state", None)):
                    self.fill("discard_pending")
                time.sleep(.01)
        finally:
            try:
                if self.owns_recording:
                    self.command("cancel")
            finally:
                self.fill("close")
                self.barrier_window.destroy()
                self.display.close()
        if self.reader_failed.is_set() and self.running:
            raise RuntimeError("鼠标监听线程意外退出")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--voxtype", default=str(Path.home() / ".local/bin/voxtype"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--right-alt", action="store_true", help="右侧 Alt 复用安全回填")
    parser.add_argument("--no-autofill", action="store_true",
                        help="保留半秒长按录音，关闭自动回填")
    parser.add_argument("--isolated-test", action="store_true",
                        help="仅用于 Xvfb 中的隔离测试，不要求 GNOME 锁屏服务")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    if os.environ.get("XDG_SESSION_TYPE", "x11") != "x11":
        raise SystemExit("仅支持 X11；未启动鼠标语音输入")
    if args.isolated_test and not args.dry_run:
        # Test mode must never invoke the user's real Voxtype binary.
        candidate = Path(args.voxtype).resolve()
        if candidate == (Path.home() / ".local/bin/voxtype").resolve():
            raise SystemExit("隔离测试禁止连接真实 Voxtype")
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))
    with (runtime / f"voxtype-mouse-hold-{os.getuid()}.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        companion = Companion(args.voxtype, args.dry_run, not args.isolated_test,
                              not args.no_autofill, args.right_alt)
        def shutdown(*_):
            companion.running = False
        signal.signal(signal.SIGTERM, shutdown)
        signal.signal(signal.SIGINT, shutdown)
        companion.run()


if __name__ == "__main__":
    main()
