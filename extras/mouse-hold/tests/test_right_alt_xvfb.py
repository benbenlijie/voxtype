"""只向新建的独立 Xvfb 发送按键，绝不向真实桌面发送。"""
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
from Xlib import X, XK, Xatom
from Xlib.ext import xtest
import test_owned_clipboard as owned_tests


class RightAltXvfbTests(owned_tests.PrivateXvfbTests):
    def test_real_alt_release_pastes_once(self):
        self.exercise(False)

    def test_focus_change_keeps_clipboard_without_paste(self):
        self.exercise(True)

    def exercise(self, switch_focus):
        with tempfile.TemporaryDirectory(prefix='alt-isolated-') as temp:
            runtime = Path(temp)
            fake = runtime / 'fake-voxtype'
            fake.write_text('''#!/usr/bin/python3
import os, sys, json
from pathlib import Path
root=Path(os.environ['ALT_TEST_RUNTIME'])
if sys.argv[1:] == ['status']:
    print('idle')
else:
    action=sys.argv[2]
    with (root/'actions').open('a') as f: f.write(action+'\\n')
    if action == 'start':
        result=next((a[7:] for a in sys.argv if a.startswith('--file=')), '')
        (root/'destination').write_text(result)
    elif action == 'stop':
        result=(root/'destination').read_text()
        if result:
            text='右侧按键合成测试'
            Path(result).write_text(text)
            Path(result+'.done').write_text(json.dumps({'status':'ok','chars':len(text)}))
''')
            fake.chmod(0o700)
            root = self.display.screen().root
            target = root.create_window(100, 100, 300, 200, 0,
                                        self.display.screen().root_depth,
                                        event_mask=X.KeyPressMask | X.KeyReleaseMask)
            target.change_property(self.display.intern_atom('_NET_WM_PID'), Xatom.CARDINAL,
                                   32, [os.getpid()])
            target.map()
            target.set_input_focus(X.RevertToParent, X.CurrentTime)
            active = self.display.intern_atom('_NET_ACTIVE_WINDOW')
            root.change_property(active, Xatom.WINDOW, 32, [target.id])
            # 鼠标特意放在目标窗口外，验证右 Alt 不依赖鼠标位置。
            root.warp_pointer(10, 10)
            self.display.sync()
            log = (runtime/'listener.log').open('w+')
            env = dict(os.environ, DISPLAY=self.display_name, XDG_RUNTIME_DIR=temp,
                       ALT_TEST_RUNTIME=temp, XDG_SESSION_TYPE='x11')
            source = Path(__file__).resolve().parents[1]
            process = subprocess.Popen(['/usr/bin/python3', str(source/'listener.py'),
                                        '--right-alt', '--isolated-test', '--voxtype', str(fake)],
                                       env=env, stdout=log, stderr=log, start_new_session=True)
            code = self.display.keysym_to_keycode(XK.string_to_keysym('Alt_R'))
            other = None
            try:
                time.sleep(.4)
                assert process.poll() is None
                xtest.fake_input(self.display, X.KeyPress, code)
                self.display.sync()
                self.wait_until(lambda: (runtime/'destination').exists(), log)
                assert (runtime/'destination').read_text(), self.logs(log)
                # 保持按下超过自动重复延迟，不能重启录音或破坏回填。
                time.sleep(.8)
                if switch_focus:
                    other = root.create_window(420, 100, 100, 100, 0,
                                               self.display.screen().root_depth,
                                               event_mask=X.KeyPressMask | X.KeyReleaseMask)
                    other.map()
                    other.set_input_focus(X.RevertToParent, X.CurrentTime)
                    root.change_property(active, Xatom.WINDOW, 32, [other.id])
                    self.display.sync()
                xtest.fake_input(self.display, X.KeyRelease, code)
                self.display.sync()
                self.wait_until(lambda: '未自动发送' in self.logs(log)
                                or '未自动回填' in self.logs(log), log)
                presses = []
                while self.display.pending_events():
                    event = self.display.next_event()
                    if event.type == X.KeyPress:
                        presses.append(event.detail)
                v = self.display.keysym_to_keycode(XK.string_to_keysym('v'))
                enter = self.display.keysym_to_keycode(XK.string_to_keysym('Return'))
                assert presses.count(v) == (0 if switch_focus else 1), self.logs(log)
                assert enter not in presses
                copied = subprocess.check_output(['xclip', '-selection', 'clipboard', '-out'],
                                                 env=env, timeout=2).decode()
                assert copied == '右侧按键合成测试'
                assert (runtime/'actions').read_text().splitlines() == ['start', 'stop']
            finally:
                xtest.fake_input(self.display, X.KeyRelease, code)
                self.display.sync()
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=5)
                target.destroy()
                if other:
                    other.destroy()
                self.display.sync()
                log.close()

    @staticmethod
    def logs(log):
        log.flush()
        return Path(log.name).read_text()

    def wait_until(self, condition, log):
        end = time.monotonic() + 8
        while time.monotonic() < end:
            if condition():
                return
            time.sleep(.03)
        raise AssertionError(self.logs(log))
