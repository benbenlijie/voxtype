# Voxtype 鼠标长按配套服务

这是一个**可选的 Linux X11 配套服务**：左键按住 `0.5` 秒后开始录音，松开后停止；录音期间鼠标距最初按下位置超过 `100` 像素就取消。

它不会修改 Voxtype 的 Rust 核心或模型目录，也不会自动按回车发送内容。默认不接管右 Alt；下述可选模式需要单独调整服务与热键配置。

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

## 安装接口假设

基础安装器需要把本目录安装到一个用户可读目录，并把 `voxtype-mouse-hold.service.in` 中的三个占位符替换为绝对路径：

- `@PYTHON@`：可用的 Python 解释器，且已安装 `requirements.txt` 中的 `python-xlib`。
- `@INSTALL_DIR@`：本目录安装后的绝对路径。
- `@VOXTYPE@`：实际使用的 Voxtype 可执行文件绝对路径。

生成后的服务文件放入：

```text
~/.config/systemd/user/voxtype-mouse-hold.service
```

模板默认没有 `[Install]` 和 `WantedBy`，所以安装后不会自动启用。只有用户在安装器中明确选择自动启动时，安装器才应追加：

```ini
[Install]
WantedBy=graphical-session.target
```

安装器不应改写 Voxtype 的配置、模型目录或公共安装逻辑；这个服务是独立的可选组件。

## 手动控制

```bash
systemctl --user daemon-reload
systemctl --user start voxtype-mouse-hold.service
systemctl --user stop voxtype-mouse-hold.service
systemctl --user disable --now voxtype-mouse-hold.service
journalctl --user -u voxtype-mouse-hold.service -n 20 --no-pager
```

如果只想保留 Voxtype 的语音剪贴板，不想自动回填，可在服务的 `ExecStart` 末尾加入：

```text
--no-autofill
```

默认鼠标模式下，也可以直接停止该服务；Voxtype 本身和原生右 Alt 录音不受影响。接管右 Alt 后，停用本服务前应恢复原生热键。

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

## 可选：右 Alt 和鼠标共用安全回填

在配套服务的 `ExecStart` 后添加 `--right-alt`，同时将 Voxtype 配置的 `[hotkey] enabled` 设为 `false`，避免两边同时启动录音。输出仍保持 `[output] mode = "clipboard"`；修改后重启两项服务。

- 先点击输入框，再按住右 Alt 说话，松开结束；不自动发送。
- 右 Alt 记录键盘焦点，不要求鼠标停在目标窗口里。捕获目标最多等待半秒，失败仍可正常录音和复制。
- 右 Alt 与鼠标长按互斥；重复按下不重复录音。连续录音超过 60 秒取消，必须松开才能再次启动。
- 使用鼠标方式已有的窗口、焦点、剪贴板归属和监听确认检查；切换窗口、点击或输入其他按键后只复制。
- 普通程序仍使用 `Ctrl+V`，终端仍使用原有专用粘贴键。Voxtype 自带的 `paste` 输出未启用。
- 兼容方式无法确认同一窗口内的具体输入框或密码框，请在按下前确认输入位置。

恢复原来方式：移除服务的 `--right-alt`，把 `[hotkey] enabled` 恢复为 `true`，重启两项服务。安装脚本不应擅自接管用户热键。
