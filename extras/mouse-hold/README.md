# Voxtype 鼠标长按配套服务

这是一个**可选的 Linux X11 配套服务**：左键按住 `0.5` 秒后开始录音，松开后停止；录音期间鼠标距最初按下位置超过 `100` 像素就取消。

它不会修改 Voxtype 的 Rust 核心、`config.toml`、模型目录或右 Alt 快捷键，也不会自动按回车发送内容。

## 安全行为

- 只支持 X11；Wayland 不在范围内。
- 启动前只接受左键，并允许最多 `6` 像素的小抖动。
- 启动前会确认 Voxtype 当前是 `idle`，锁屏或状态无法确认时不启动。
- 录音期间确认屏幕已锁定会取消本次鼠标录音；临时锁屏查询失败不会强行打断录音，但结束时仍不允许在无法确认安全的情况下回填。
- 识别结果先进入本次运行的私有目录和剪贴板。运行目录权限为 `0700`，结果文件权限为 `0600`，日志不记录识别原文。
- 普通应用最多尝试一次 `Ctrl+V`；终端使用终端专用粘贴快捷键。窗口、焦点、按键状态、剪贴板归属或监听确认发生变化时，只保留剪贴板，不发送粘贴键。
- 不切回窗口、不重新点击、不自动发送；粘贴失败不重试。
- 提示窗口只做身份确认和防抢焦点处理，不主动恢复焦点。

“普通应用”只表示当前用户拥有、且能通过 X11 进程信息确认的窗口。兼容粘贴无法识别同一窗口里的具体输入框、密码框或网页状态；使用前请确认焦点确实在目标输入框。

## 安装

在项目根目录运行安装器。它会把本目录安装到用户目录，并把 `voxtype-mouse-hold.service.in` 中的三个占位符替换为绝对路径：

- `@PYTHON@`：可用的 Python 解释器，且已安装 `requirements.txt` 中的 `python-xlib`。
- `@INSTALL_DIR@`：本目录安装后的绝对路径。
- `@VOXTYPE@`：实际使用的 Voxtype 可执行文件绝对路径。

安装器会把模板中的 `@PYTHON@`、`@INSTALL_DIR@` 和 `@VOXTYPE@` 替换为当前机器的实际路径，并生成：

```text
~/.config/systemd/user/voice-suite-mouse.service
```

模板默认没有 `[Install]` 和 `WantedBy`，所以安装后不会自动启用。只有用户运行安装器并明确加上 `--enable-mouse` 时，安装器才会追加：

```ini
[Install]
WantedBy=graphical-session.target
```

安装器不会改写 Voxtype 的配置或模型目录；这个服务是独立的可选组件。

## 手动控制

```bash
systemctl --user daemon-reload
systemctl --user start voice-suite-mouse.service
systemctl --user stop voice-suite-mouse.service
systemctl --user disable --now voice-suite-mouse.service
journalctl --user -u voice-suite-mouse.service -n 20 --no-pager
```

如果只想保留 Voxtype 的语音剪贴板，不想自动回填，可在服务的 `ExecStart` 末尾加入：

```text
--no-autofill
```

也可以直接停止该服务；Voxtype 本身和右 Alt 录音不受影响。

## 系统依赖

Python 依赖见 `requirements.txt`。常见发行版还需要 X11 运行库和工具：

- Debian、Ubuntu：`python3`, `python3-pip`, `python3-xlib`, `xclip`, `gdbus`。
- Fedora：`python3`, `python3-pip`, `python3-xlib`, `xclip`, `glib2`。
- Arch Linux：`python`, `python-pip`, `python-xlib`, `xclip`, `glib2`。

包名会随发行版变化，安装前请用本发行版的软件包搜索确认。`xclip` 用于拥有者可核对的剪贴板写入；缺失时仍可保留 Voxtype 自己的输出，但自动回填会拒绝。

## 兼容限制与验证边界

- 这是 X11 专用功能；Wayland 会直接退出，不会假装已经工作。
- 本目录单元测试使用替身，不需要真实麦克风，也不会把识别文本写入日志。
- 需要真实 X11 显示服务器的测试默认跳过；没有真实桌面时不能声称 GTK、浏览器或终端已经验证。
- 真实应用可能有自己的粘贴策略、权限限制或焦点行为；单元测试通过不等于所有应用都能接受粘贴。
