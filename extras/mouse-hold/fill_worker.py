"""Private per-recording results; direct fill or guarded window paste."""
import argparse
import json
import logging
import os
from pathlib import Path
import subprocess
import struct
import time

from fill_target import Target, decode_transcript
from window_target import WindowTarget

LOG = logging.getLogger("voxtype-mouse-hold")
LIMIT = 1024 * 1024


def listener_barrier(directory, connection):
    """Wait for the RECORD reader to process all input preceding our marker."""
    from Xlib import X
    from Xlib.protocol import event
    try:
        if (directory / "invalid").exists() or (directory / "cancelled").exists():
            LOG.info("监听确认未通过：本次回填已经失效或取消")
            return False
        xid = int((directory / "barrier-window").read_text())
        token = int((directory / "barrier-token").read_text())
        window = connection.create_resource_object("window", xid)
        marker = event.ClientMessage(
            window=xid, client_type=connection.intern_atom("_VOXTYPE_PASTE_BARRIER"),
            data=(32, [token, 0, 0, 0, 0]))
        window.send_event(marker, event_mask=X.NoEventMask)
        connection.sync()
        end = time.monotonic() + .25
        while time.monotonic() < end:
            if (directory / "invalid").exists() or (directory / "cancelled").exists():
                LOG.info("监听确认未通过：等待期间检测到操作或取消")
                return False
            ack = directory / "barrier-ack"
            if ack.exists() and ack.read_text() == str(token):
                return True
            time.sleep(.002)
    # An unavailable or malformed marker never permits an unverified paste.
        LOG.info("监听确认未通过：等待回应超过 0.25 秒")
    except (OSError, ValueError, TypeError, struct.error) as exc:
        LOG.info("监听确认未通过：%s", type(exc).__name__)
    return False


def read_result(path):
    done = path.with_name(path.name + ".done")
    if not done.exists():
        return None
    try:
        # Voxtype creates this file. Tighten its permissions before reading or
        # delivering it; the containing runtime directory is private as well.
        path.chmod(0o600)
        if done.stat().st_size > 4096:
            return "skip", ""
        result = json.loads(done.read_text())
        if (result.get("status") != "ok"
                or path.stat().st_size > LIMIT):
            return "skip", ""
        text = decode_transcript(path.read_text(), result.get("chars"))
        return ("ok", text) if text and text.strip() else ("skip", "")
    except (OSError, ValueError, AttributeError, TypeError):
        return "skip", ""


def copy_clipboard(text):
    try:
        subprocess.run(["xclip", "-selection", "clipboard", "-in"],
                       input=text.encode("utf-8"), timeout=1, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def deliver(text, target, copy, safe, *, clipboard=None):
    if not copy(text):
        return "copy_failed"
    try:
        if getattr(target, "mode", None) in {"window", "generic", "terminal"}:
            if not target.bind_clipboard(clipboard):
                LOG.info("回填未执行：剪贴板归属未确认")
                return "copied"
        if not safe():
            LOG.info("回填未执行：第一次安全检查未通过")
            return "copied"
        if not target.valid():
            LOG.info("回填未执行：目标检查未通过：%s",
                     getattr(target, "rejection_reason", "原输入框不可确认"))
            return "copied"
        if not safe():
            LOG.info("回填未执行：第二次安全检查未通过")
            return "copied"
        if target.insert(text):
            return "filled"
        LOG.info("回填未执行：粘贴前检查未通过：%s",
                 getattr(target, "rejection_reason", "原输入框不可确认"))
    except Exception as exc:
        # Never retry a possibly already-applied insertion.
        LOG.warning("粘贴检查异常：%s；不会重试", type(exc).__name__)
    return "copied"


def capture_target(x, y, focused=False):
    if focused:
        target = WindowTarget()
        try:
            if target.capture(x, y, focused=True):
                return target
        except Exception:
            pass
        target.close()
        return None

    # Compatibility paste records the original focused window when AT-SPI
    # cannot reliably identify an editable field.
    compat = WindowTarget()
    generic = None
    try:
        if compat.capture(x, y):
            if compat.mode != "generic":
                return compat
            generic = compat
        else:
            compat.close()
    except Exception:
        compat.close()
    direct = Target()
    try:
        if direct.capture(x, y):
            if generic is not None:
                generic.close()
            return direct
    except Exception:
        direct.close()
        if generic is not None:
            return generic
        raise
    direct.close()
    return generic


def unlocked():
    try:
        return subprocess.check_output([
            "gdbus", "call", "--session", "--dest", "org.gnome.ScreenSaver",
            "--object-path", "/org/gnome/ScreenSaver",
            "--method", "org.gnome.ScreenSaver.GetActive"],
            timeout=1, text=True, stderr=subprocess.DEVNULL).strip() == "(false,)"
    except (OSError, subprocess.SubprocessError):
        return False


def rescue(directory, end):
    """Copy this exact stopped recording, never consult the desktop target."""
    while time.monotonic() < end:
        if (directory / "cancelled").exists():
            return 0
        if (directory / "stopped").exists():
            result = read_result(directory / "transcript")
            if result is not None:
                if result[0] != "ok":
                    return 0
                if copy_clipboard(result[1]):
                    LOG.info("本次识别结果已补复制；未尝试回填")
                    return 0
                return 1
        time.sleep(.05)
    return 1


def run(directory, x, y, isolated=False, focused=False):
    # The only persistent content is this recording's own transcript in a
    # private runtime directory. Existing field text is never retrieved.
    os.umask(0o077)
    target = None
    clipboard = None
    end = time.monotonic() + 210
    try:
        time.sleep(.04)  # Let the original mouse-down set its insertion point.
        target = (capture_target(x, y, focused=True) if focused
                  else capture_target(x, y))
        if target is None:
            LOG.info("未确认可回填输入框；本次只复制")
            return 0
        mode = getattr(target, "mode", "direct")
        if mode in {"window", "generic", "terminal"}:
            from owned_clipboard import OwnedClipboard
            clipboard = OwnedClipboard(target.display)
            # Both compatibility paths need the same listener acknowledgement.
            # Leaving the ChatGPT path unbound keeps WindowTarget's deny default.
            target.guard = lambda: (
                not (directory / "invalid").exists()
                and not (directory / "cancelled").exists())
            target.barrier = lambda: listener_barrier(directory, target.display)
        (directory / "ready").write_text(mode)
        if mode == "window":
            LOG.info("已记住 ChatGPT 原窗口；启用兼容粘贴，不自动发送")
        elif mode == "generic":
            LOG.info("已记住普通程序原窗口和焦点；识别后尝试一次 Ctrl+V，不自动发送")
        elif mode == "terminal":
            LOG.info("已记住终端原窗口；使用终端兼容粘贴快捷键")
        while time.monotonic() < end:
            if (directory / "cancelled").exists():
                return 0
            target.pump()
            if (directory / "stopped").exists():
                result = read_result(directory / "transcript")
                if result is not None:
                    if result[0] != "ok":
                        LOG.info("本次无可回填结果或识别失败；不写入输入框")
                        return 0
                    def safe():
                        # The lock query can take a second. Recheck user input
                        # AFTER it returns, never use a pre-query snapshot.
                        if not isolated and not unlocked():
                            LOG.info("安全检查未通过：屏幕已锁定或锁屏查询失败")
                            return False
                        target.pump()
                        pointer = target.root.query_pointer()
                        reasons = []
                        if (directory / "invalid").exists():
                            reasons.append("捕获目标后检测到按键或点击，或助手曾中断")
                        if (directory / "cancelled").exists():
                            reasons.append("本次录音已取消")
                        if target.changed:
                            reasons.append(getattr(target, "change_reason", None)
                                           or "原输入框状态发生变化")
                        # Ignore Caps/Num Lock, as before.
                        if pointer.mask & ~18:
                            reasons.append("仍有鼠标按钮或修饰键处于按下状态")
                        if reasons:
                            LOG.info("安全检查未通过：%s", "；".join(reasons))
                        return not reasons
                    copy = clipboard.copy if clipboard else copy_clipboard
                    outcome = deliver(result[1], target, copy, safe,
                                      clipboard=clipboard)
                    filled_message = (
                        "已向原 ChatGPT 窗口发出一次兼容粘贴；未自动发送"
                        if mode == "window" else
                        "已向原普通程序窗口发出一次 Ctrl+V；未自动发送"
                        if mode == "generic" else
                        "已向原终端窗口发出一次终端粘贴；未自动发送"
                        if mode == "terminal" else
                        "识别结果已复制，并回填到原输入框光标处")
                    LOG.info({"filled": filled_message,
                              "copied": "识别结果已复制；目标变化或不可确认，未自动回填",
                              "copy_failed": "复制未成功；保留本次私有识别文件，未回填"}[outcome])
                    return 1 if outcome == "copy_failed" else 0
            time.sleep(.025)
        LOG.warning("等待本次识别完成超时；不回填，保留本次私有识别文件")
        return 1
    except Exception as exc:
        LOG.warning("回填检查不可用：%s；不写入输入框", type(exc).__name__)
        # If file output was selected, still rescue this exact result.
        if (directory / "started").exists():
            return rescue(directory, end)
        return 0
    finally:
        if clipboard:
            clipboard.close()
        if target:
            try:
                target.close()
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("x", type=int)
    parser.add_argument("y", type=int)
    parser.add_argument("--isolated-test", action="store_true")
    parser.add_argument("--copy-only", action="store_true")
    parser.add_argument("--focused", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    code = (rescue(args.directory, time.monotonic() + 90) if args.copy_only
            else run(args.directory, args.x, args.y, args.isolated_test, args.focused))
    if code == 0:
        (args.directory / "finished").touch()
    raise SystemExit(code)


if __name__ == "__main__":
    main()
