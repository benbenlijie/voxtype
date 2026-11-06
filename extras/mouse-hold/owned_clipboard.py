"""一次识别结果的剪贴板复制及拥有者证明；不读取剪贴板内容。

copy() 为 True 仅表示完整文本已交给仍存活的 xclip，不表示允许粘贴。
调用方必须另行检查 owner_matches(display)，并在最终注入的服务器锁内
再次检查。copy() 必须在服务器锁外调用：只有复制阶段会打开查询连接。
close() 只撤销本地证明，不清空剪贴板、不结束持有剪贴板的 xclip。
"""

import ctypes
import ctypes.util
import math
import os
from pathlib import Path
import select
import subprocess
import sys
import time


MAX_BYTES = 1024 * 1024
_PID_MASK = 2


class _ClientIdSpec(ctypes.Structure):
    _fields_ = [("client", ctypes.c_ulong), ("mask", ctypes.c_uint)]


class _ClientIdValue(ctypes.Structure):
    _fields_ = [
        ("spec", _ClientIdSpec),
        ("length", ctypes.c_long),
        ("value", ctypes.c_void_p),
    ]


def _load_xres():
    """只加载库，不连接桌面；缺库或符号不完整时拒绝提供证明。"""
    try:
        x11_name = ctypes.util.find_library("X11")
        xres_name = ctypes.util.find_library("XRes")
        if not x11_name or not xres_name:
            return None
        x11, xres = ctypes.CDLL(x11_name), ctypes.CDLL(xres_name)
        display = ctypes.c_void_p
        integer = ctypes.POINTER(ctypes.c_int)
        values = ctypes.POINTER(_ClientIdValue)
        signatures = (
            (x11.XOpenDisplay, [ctypes.c_char_p], display),
            (x11.XCloseDisplay, [display], ctypes.c_int),
            (xres.XResQueryExtension, [display, integer, integer], ctypes.c_int),
            (xres.XResQueryVersion, [display, integer, integer], ctypes.c_int),
            (xres.XResQueryClientIds,
             [display, ctypes.c_long, ctypes.POINTER(_ClientIdSpec),
              ctypes.POINTER(ctypes.c_long), ctypes.POINTER(values)],
             ctypes.c_int),
            (xres.XResGetClientPid, [values], ctypes.c_int),
            (xres.XResClientIdsDestroy, [ctypes.c_long, values], None),
        )
        for function, args, result in signatures:
            function.argtypes, function.restype = args, result
        return x11, xres
    except (OSError, AttributeError):
        return None


def _native_client_pid(display_name, owner_id):
    """只在隔离的限时查询进程中调用，防止原生库错误影响调用方。"""
    libraries = _load_xres()
    if libraries is None:
        return None
    x11, xres = libraries
    connection = None
    values = ctypes.POINTER(_ClientIdValue)()
    count = ctypes.c_long()
    try:
        connection = x11.XOpenDisplay(display_name.encode("utf-8"))
        if not connection:
            return None
        event_base, error_base = ctypes.c_int(), ctypes.c_int()
        if not xres.XResQueryExtension(
                connection, ctypes.byref(event_base), ctypes.byref(error_base)):
            return None
        major, minor = ctypes.c_int(), ctypes.c_int()
        if not xres.XResQueryVersion(
                connection, ctypes.byref(major), ctypes.byref(minor)):
            return None
        if (major.value, minor.value) < (1, 2):
            return None
        spec = _ClientIdSpec(owner_id, _PID_MASK)
        # 此函数成功返回 0，和 XResQueryVersion 的成功返回值不同。
        status = xres.XResQueryClientIds(
            connection, 1, ctypes.byref(spec),
            ctypes.byref(count), ctypes.byref(values))
        if status != 0 or not values or count.value != 1:
            return None
        value = values[0]
        if (value.spec.mask != _PID_MASK or value.length != 4
                or not value.value):
            return None
        pid = xres.XResGetClientPid(values)
        return pid if type(pid) is int and pid > 0 else None
    except Exception:
        return None
    finally:
        if values:
            xres.XResClientIdsDestroy(count.value, values)
        if connection:
            x11.XCloseDisplay(connection)


def query_client_pid(display, owner_id, timeout=.3):
    """通过 XRes 查询窗口所属客户进程；不信任窗口自行声明的 PID 属性。"""
    try:
        if (type(owner_id) is not int or not 0 < owner_id <= 0xffffffff
                or not math.isfinite(timeout) or timeout <= 0):
            return None
        name = display.get_display_name()
        if not isinstance(name, str) or not name or "\0" in name:
            return None
        result = subprocess.run(
            [sys.executable, "-B", str(Path(__file__).resolve()),
             "--owner-pid", name, str(owner_id)],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, timeout=timeout,
            check=False, close_fds=True)
        output = result.stdout.strip()
        if result.returncode != 0 or not output.isascii() or not output.isdecimal():
            return None
        pid = int(output)
        return pid if 0 < pid <= 0x7fffffff else None
    except Exception:
        return None


def _write_stdin(stream, payload, deadline):
    """有界写入并关闭标准输入；管道堵塞也不结束剪贴板进程。"""
    success = False
    try:
        fd = stream.fileno()
        os.set_blocking(fd, False)
        remaining = memoryview(payload)
        while remaining:
            wait = deadline - time.monotonic()
            if wait <= 0 or not select.select([], [fd], [], wait)[1]:
                break
            try:
                written = os.write(fd, remaining)
            except (BlockingIOError, InterruptedError):
                continue
            if written <= 0:
                break
            remaining = remaining[written:]
        success = not remaining
    except Exception:
        success = False
    finally:
        if stream is not None:
            try:
                stream.close()
            except Exception:
                success = False
    return success


class OwnedClipboard:
    """每个实例仅可复制一次；拥有者证明失效后不能重新绑定。

    同一实例由单个工作线程使用。owner_matches 不另开连接、不调用
    XRes；它只在原连接上读取拥有者 ID，并检查缓存证明和子进程存活。
    """

    def __init__(self, display, *, xclip="xclip", timeout=1.0,
                 popen=None, owner_pid=None):
        self._display = display
        self._xclip = xclip
        self._timeout = timeout
        self._popen = subprocess.Popen if popen is None else popen
        self._owner_pid = query_client_pid if owner_pid is None else owner_pid
        self._process = None
        self._atom = None
        self._used = False
        self._closed = False
        self._owner_id = None
        self._expected_pid = None

    @property
    def owner_id(self):
        return self._owner_id

    @property
    def expected_pid(self):
        return self._expected_pid

    def _current_owner(self):
        owner = self._display.get_selection_owner(self._atom)
        xid = getattr(owner, "id", owner)
        return xid if type(xid) is int and 0 < xid <= 0xffffffff else None

    def copy(self, text):
        self._owner_id = None
        if self._used or self._closed:
            return False
        self._used = True
        try:
            if (not isinstance(text, str) or not text.strip() or "\0" in text
                    or len(text) > MAX_BYTES):
                return False
            payload = text.encode("utf-8")
            if len(payload) > MAX_BYTES:
                return False
            if not math.isfinite(self._timeout) or self._timeout <= 0:
                return False
            name = self._display.get_display_name()
            if not isinstance(name, str) or not name or "\0" in name:
                return False
            deadline = time.monotonic() + self._timeout
            self._process = self._popen(
                [self._xclip, "-quiet", "-selection", "clipboard", "-in",
                 "-loops", "0", "-display", name],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, start_new_session=True,
                close_fds=True, bufsize=0)
            self._expected_pid = self._process.pid
            if not _write_stdin(self._process.stdin, payload, deadline):
                return False
            if self._process.poll() is not None:
                return False
        except Exception:
            if self._process is not None:
                try:
                    self._process.stdin.close()
                except Exception:
                    pass
            return False

        # 复制与绑定不是原子操作：必须证明当前拥有者确为这次启动的
        # 前台 xclip，绝不能把复制后碰巧出现的其他拥有者当作本次结果。
        try:
            self._atom = self._display.intern_atom("CLIPBOARD")
            while time.monotonic() < deadline:
                if self._process.poll() is not None:
                    return False
                owner = self._current_owner()
                if owner:
                    pid = self._owner_pid(
                        self._display, owner,
                        timeout=max(.001, deadline - time.monotonic()))
                    if pid == self._expected_pid and type(pid) is int:
                        if (self._current_owner() == owner
                                and self._process.poll() is None
                                and time.monotonic() < deadline):
                            self._owner_id = owner
                        break
                time.sleep(min(.01, max(0, deadline - time.monotonic())))
        except Exception:
            self._owner_id = None
        return True

    def owner_matches(self, display):
        try:
            matches = (
                not self._closed and display is self._display
                and self._owner_id is not None
                and self._process is not None
                and self._process.pid == self._expected_pid
                and self._process.poll() is None
                and self._current_owner() == self._owner_id
                and self._process.poll() is None)
        except Exception:
            matches = False
        if not matches:
            self._owner_id = None
        return bool(matches)

    def close(self):
        self._closed = True
        self._owner_id = None


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--owner-pid":
        try:
            owner = int(sys.argv[3])
            pid = (_native_client_pid(sys.argv[2], owner)
                   if 0 < owner <= 0xffffffff else None)
        except Exception:
            pid = None
        if pid is not None:
            print(pid)
            sys.exit(0)
    sys.exit(1)
