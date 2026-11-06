"""Pure gesture decisions. No keyboard/mouse interception or audio here."""


class Gesture:
    def __init__(self, delay=0.5, radius=6, max_recording=120,
                 recording_radius=100):
        self.delay = delay
        self.radius = radius
        self.max_recording = max_recording
        self.recording_radius = recording_radius
        self.pending = False
        self.recording = False
        self.origin = (0, 0)
        self.pressed_at = 0
        self.started_at = 0

    def press(self, button, x, y, now):
        if button != 1:
            return self.abort()
        action = self.abort()
        self.origin = (x, y)
        self.pressed_at = now
        self.pending = True
        return action

    def move(self, x, y):
        # 启动前保留原来的小范围限制；录音后允许自然漂移，
        # 但距最初按下位置超过 100 像素就取消，不累计移动路程。
        radius = self.recording_radius if self.recording else self.radius
        ox, oy = self.origin
        if (x - ox) ** 2 + (y - oy) ** 2 > radius ** 2:
            return self.abort()
        return None

    def due(self, now):
        return self.pending and now - self.pressed_at >= self.delay

    def started(self, now):
        self.pending = False
        self.recording = True
        self.started_at = now

    def reject(self):
        self.pending = False

    def release(self, button):
        if button != 1:
            return None
        self.pending = False
        was_recording = self.recording
        self.recording = False
        return "stop" if was_recording else None

    def abort(self):
        self.pending = False
        was_recording = self.recording
        self.recording = False
        return "cancel" if was_recording else None

    def watchdog(self, now):
        if self.recording and now - self.started_at >= self.max_recording:
            return self.abort()
        return None
