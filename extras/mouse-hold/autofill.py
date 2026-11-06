"""Non-blocking per-gesture workers. Never gates the global recording gesture."""
from dataclasses import dataclass
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import secrets

LOG = logging.getLogger("voxtype-mouse-hold")


@dataclass
class Job:
    directory: Path
    process: object
    created: float
    started: bool = False
    stopped: bool = False
    rescued: bool = False
    barrier_token: int = 0


class Autofill:
    def __init__(self, runtime=None, require_unlock=True, barrier_window=None):
        self.runtime = Path(runtime or os.environ["XDG_RUNTIME_DIR"])
        self.require_unlock = require_unlock
        self.jobs = []
        self.current = None
        self.barrier_window = barrier_window

    def invalidate(self):
        # The RECORD reader may invalidate before the main event queue drains.
        for job in self.jobs[:]:
            try:
                if job.process.poll() is None:
                    (job.directory / "invalid").touch()
            except FileNotFoundError:
                pass  # Main thread already completed and removed this job.

    def ack_barrier(self, token):
        for job in self.jobs[:]:
            if job.barrier_token and job.barrier_token == token:
                try:
                    (job.directory / "barrier-ack").write_text(str(token))
                except FileNotFoundError:
                    pass
                return

    def discard_pending(self):
        if self.current and not self.current.started:
            (self.current.directory / "cancelled").touch()
            self.current.process.terminate()
            self.current = None

    def press(self, x, y):
        self.invalidate()
        self.discard_pending()
        directory = Path(tempfile.mkdtemp(prefix="voxtype-fill-", dir=self.runtime))
        token = secrets.randbits(32) or 1
        if self.barrier_window:
            (directory / "barrier-window").write_text(str(self.barrier_window))
            (directory / "barrier-token").write_text(str(token))
        args = [sys.executable, str(Path(__file__).with_name("fill_worker.py")),
                str(directory), str(x), str(y)]
        if not self.require_unlock:
            args.append("--isolated-test")
        try:
            process = subprocess.Popen(args, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.DEVNULL)
        except OSError:
            shutil.rmtree(directory)
            LOG.warning("无法启动回填检查；本次只复制")
            return
        self.current = Job(directory, process, time.monotonic(), barrier_token=token)
        self.jobs.append(self.current)

    def start_args(self):
        job = self.current
        if (job and job.process.poll() is None
                and (job.directory / "ready").exists()
                and not (job.directory / "invalid").exists()
                and not (job.directory / "finished").exists()):
            job.started = True
            (job.directory / "started").touch()
            mode = (job.directory / "ready").read_text()
            destinations = {
                "window": "ChatGPT 原窗口（兼容粘贴）",
                "generic": "普通程序原窗口和焦点（兼容粘贴）",
                "terminal": "终端原窗口（兼容粘贴）",
            }
            LOG.info("本次鼠标录音已记住%s；识别后再次核对",
                     destinations.get(mode, "原输入框"))
            return ["--file=" + str(job.directory / "transcript"),
                    "--no-auto-submit", "--no-smart-auto-submit"]
        self.discard_pending()
        LOG.info("本次未确认原输入框；正常录音，只复制")
        return []

    def action(self, action):
        job = self.current
        if not job:
            return
        if action == "stop" and job.started:
            job.stopped = True
            (job.directory / "stopped").touch()
            self.current = None
        elif action == "cancel":
            (job.directory / "cancelled").touch()
            if not job.started:
                job.process.terminate()
            self.current = None

    def poll(self):
        for job in self.jobs[:]:
            code = job.process.poll()
            if code is None and time.monotonic() - job.created > 215:
                (job.directory / "invalid").touch()
                job.process.terminate()
            elif code is not None:
                cancelled = (job.directory / "cancelled").exists()
                finished = (job.directory / "finished").exists()
                # Keep the recording's destination until release/cancel even
                # if its worker dies early. Release must still mark stopped.
                if job.started and not job.stopped and not cancelled:
                    (job.directory / "invalid").touch()
                    continue
                if (job.started and job.stopped and not cancelled
                        and not job.rescued and (code != 0 or not finished)):
                    (job.directory / "invalid").touch()
                    job.rescued = True
                    try:
                        job.process = subprocess.Popen([
                            sys.executable, str(Path(__file__).with_name("fill_worker.py")),
                            str(job.directory), "0", "0", "--copy-only"],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
                        job.created = time.monotonic()
                        LOG.warning("回填助手中断；只补复制本次结果，不再尝试回填")
                        continue
                    except OSError:
                        pass
                # Failed/late deliveries are retained privately, not replayed.
                if not job.started or cancelled or (code == 0 and finished):
                    shutil.rmtree(job.directory, ignore_errors=True)
                else:
                    LOG.warning("本次识别交付未完成；保留私有识别文件，不自动回填")
                self.jobs.remove(job)
                if self.current is job:
                    self.current = None

    def close(self):
        self.invalidate()
        self.discard_pending()
        for job in self.jobs:
            if not job.stopped:
                (job.directory / "cancelled").touch()
            if job.process.poll() is None:
                job.process.terminate()
            try:
                job.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                job.process.kill()
                job.process.wait(timeout=1)
            # A daemon may still be writing a stopped recording: preserve
            # its private file, never remove its destination during shutdown.
            if not job.started:
                shutil.rmtree(job.directory, ignore_errors=True)
        self.jobs.clear()
