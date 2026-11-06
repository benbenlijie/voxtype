# Voxtype 鼠标启动与回填配套实施计划

> **给代理开发者：** 必须按任务逐项执行；可使用 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans`。测试先行，保持鼠标监听为独立可选服务；按明确文件清单提交，严禁使用 `git add .`。

**目标：** 将现有鼠标长按助手整理成可从 Voxtype 项目安装的可选 Linux X11 配套服务，保留 0.5 秒启动、20 像素取消、焦点保护、终端粘贴和不自动发送行为。

**架构：** `listener.py` 只监听 X11 输入并编排动作；`gesture.py` 处理纯手势状态；窗口、剪贴板、回填和提示各模块维持分工。服务从用户目录定位 Voxtype 程序和本项目代码，不能写死本机路径。无法确认安全时只保留识别结果或剪贴板，不强制切换焦点。

**技术栈：** Python 3、pytest、python-xlib、X11 RECORD/XTEST、systemd 用户服务、Voxtype 命令行。

---

## 文件职责

- `extras/mouse-hold/listener.py`：X11 事件读取、锁屏和 Voxtype 状态检查、服务主循环。
- `extras/mouse-hold/gesture.py`：0.5 秒与移动阈值的纯状态机。
- `extras/mouse-hold/autofill.py`、`fill_target.py`、`fill_worker.py`：目标控件探测与后台结果回填。
- `extras/mouse-hold/window_target.py`：普通窗口和终端的焦点检查、粘贴按键。
- `extras/mouse-hold/owned_clipboard.py`：核对粘贴板是否仍属于本次识别结果。
- `extras/mouse-hold/indicator.py`：避免提示窗抢走输入焦点。
- `extras/mouse-hold/voxtype-mouse-hold.service.in`：systemd 用户服务模板；由安装器写入实际绝对路径。
- `extras/mouse-hold/requirements.txt`：固定兼容范围的 Python 依赖。
- `extras/mouse-hold/tests/`：复制现有手势、监听、窗口焦点、粘贴板和回填测试；不包含本机日志或识别内容。

## 任务 1：迁移纯手势状态机并保留阈值

**文件：**
- 新建：`extras/mouse-hold/gesture.py`
- 新建：`extras/mouse-hold/tests/test_gesture.py`

- [ ] **步骤 1：迁移并检查已有测试**

从 `outputs/voxtype-mouse-hold/gesture.py` 和 `tests/test_gesture.py` 迁移逻辑与覆盖；设置默认 `delay=0.5`、启动前 `radius=6`、最大录音时间 `120` 秒、录音取消距离 `recording_radius=20` 像素。

- [ ] **步骤 2：运行手势测试**

运行：`python3 -m pytest extras/mouse-hold/tests/test_gesture.py -q`

预期：触发边界、短按、等待时移动、录音中 20 像素取消、松开停止、最大时长取消全部 PASS。

- [ ] **步骤 3：增加边界测试**

明确测试恰好 20 像素不取消、超过 20 像素取消、移动后移回不恢复，以及无效按钮不会启动。

- [ ] **步骤 4：再次运行**

运行同上，预期所有手势测试 PASS。

- [ ] **步骤 5：提交**

```bash
git add extras/mouse-hold/gesture.py extras/mouse-hold/tests/test_gesture.py
git commit -m "feat: package mouse hold gesture state machine"
```

## 任务 2：迁移焦点与剪贴板保护模块

**文件：**
- 新建：`extras/mouse-hold/window_target.py`
- 新建：`extras/mouse-hold/owned_clipboard.py`
- 新建：`extras/mouse-hold/tests/test_window_target.py`
- 新建：`extras/mouse-hold/tests/test_owned_clipboard.py`
- 新建：`extras/mouse-hold/tests/test_paste_barrier.py`

- [ ] **步骤 1：迁移纯规则和替身测试**

从现有项目源码及对应测试迁移窗口 PID 信任、终端专用粘贴键、窗口/焦点变化拒绝、剪贴板拥有者与进程核对。删除所有个人绝对路径、本机 OSD 文件名以外的私人信息和聊天测试文本；保留通用替身或合成字符串。

- [ ] **步骤 2：运行测试确认需本地 X11 才运行的项目有标记**

运行：`python3 -m pytest extras/mouse-hold/tests/test_window_target.py extras/mouse-hold/tests/test_owned_clipboard.py extras/mouse-hold/tests/test_paste_barrier.py -q`

预期：不需要活动桌面的单测通过；需显示桌面的用例标注 `integration` 并默认跳过。

- [ ] **步骤 3：审查粘贴失败保护**

确认任何窗口变更、焦点变更、按键、剪贴板所有者不匹配、锁屏、进程所有权不符时都不发送粘贴键；粘贴至多尝试一次，不执行回车。

- [ ] **步骤 4：运行回归测试**

重复步骤 2 的命令，预期 PASS。

- [ ] **步骤 5：提交**

```bash
git add extras/mouse-hold/window_target.py extras/mouse-hold/owned_clipboard.py extras/mouse-hold/tests/test_window_target.py extras/mouse-hold/tests/test_owned_clipboard.py extras/mouse-hold/tests/test_paste_barrier.py
git commit -m "test: preserve safe window and clipboard paste guards"
```

## 任务 3：迁移回填工作进程与指示器

**文件：**
- 新建：`extras/mouse-hold/autofill.py`
- 新建：`extras/mouse-hold/fill_target.py`
- 新建：`extras/mouse-hold/fill_worker.py`
- 新建：`extras/mouse-hold/indicator.py`
- 新建：`extras/mouse-hold/tests/test_autofill.py`
- 新建：`extras/mouse-hold/tests/test_worker_binding.py`
- 新建：`extras/mouse-hold/tests/test_indicator.py`

- [ ] **步骤 1：迁移状态和安全测试**

迁移对应通用模块及单测；先剔除所有个人绝对路径、本机 OSD 文件名以外的私人信息和聊天测试文本。把运行文件改为每用户私有运行目录（权限 `0700`），结果文件 `0600`；结果文本不进入日志。保持识别结束后先核对窗口、焦点、锁屏和剪贴板，再尝试普通窗口一次 `Ctrl+V`，终端走终端专用快捷键。

- [ ] **步骤 2：测试失败和恢复场景**

用替身测试确认：监听端未确认粘贴屏障时不发送按键；提示窗抢焦点只复制不粘贴；服务异常退出不重放粘贴；复制成功但粘贴动作失败不二次尝试；不自动发送。

- [ ] **步骤 3：运行单测**

运行：`python3 -m pytest extras/mouse-hold/tests/test_autofill.py extras/mouse-hold/tests/test_worker_binding.py extras/mouse-hold/tests/test_indicator.py -q`

预期：全部 PASS。

- [ ] **步骤 4：检查隐私和临时目录清理**

增加测试确保完成后删除每次录音私有文件夹，异常时只在进程退出前执行一次补剪贴板，不写入转写原文日志。

- [ ] **步骤 5：提交**

```bash
git add extras/mouse-hold/autofill.py extras/mouse-hold/fill_target.py extras/mouse-hold/fill_worker.py extras/mouse-hold/indicator.py extras/mouse-hold/tests/test_autofill.py extras/mouse-hold/tests/test_worker_binding.py extras/mouse-hold/tests/test_indicator.py
git commit -m "feat: package guarded transcript autofill worker"
```

## 任务 4：迁移并重构 X11 监听主程序

**文件：**
- 新建：`extras/mouse-hold/listener.py`
- 新建：`extras/mouse-hold/tests/test_listener.py`
- 新建：`extras/mouse-hold/tests/test_global_hold.py`

- [ ] **步骤 1：先增加 Voxtype 命令替身测试**

替身执行器验证启动时调用 `voxtype record start`、松开调用 `voxtype record stop`、越界取消调用 `voxtype record cancel`；原 Voxtype 非 idle、锁屏或无法安全检查时不启动。通过可注入 `--voxtype` 路径和依赖替身测试，不访问系统麦克风。

- [ ] **步骤 2：迁移事件循环**

迁移 RECORD 事件消费者、队列溢出保护、录音看护超时、锁屏轮询、监听线程故障时安全退出和事件屏障；移除测试专用接口、用户私有安装探测和不必要诊断代码。

- [ ] **步骤 3：运行监听单测**

运行：`python3 -m pytest extras/mouse-hold/tests/test_listener.py extras/mouse-hold/tests/test_global_hold.py -q`

预期：无 X11 桌面的单测 PASS；桌面集成项默认跳过。

- [ ] **步骤 4：运行配套整体测试**

运行：`python3 -m pytest extras/mouse-hold/tests -q`

预期：模拟测试通过，真实桌面项明确显示跳过原因。

- [ ] **步骤 5：提交**

```bash
git add extras/mouse-hold/listener.py extras/mouse-hold/tests/test_listener.py extras/mouse-hold/tests/test_global_hold.py
git commit -m "feat: add optional X11 mouse hold listener"
```

## 任务 5：可移植依赖、服务模板和安装验收

**文件：**
- 新建：`extras/mouse-hold/requirements.txt`
- 新建：`extras/mouse-hold/voxtype-mouse-hold.service.in`
- 新建：`extras/mouse-hold/README.md`
- 测试：基础计划 `extras/tests/test_install_scripts.py`

- [ ] **步骤 1：创建依赖清单**

记录 `python-xlib` 最低兼容范围和测试依赖范围。任何 X11 原生系统包写清发行版常用包名；不能假设已存在系统 X11 库。

- [ ] **步骤 2：创建服务模板**

服务 `ExecStart` 使用安装器生成的安装路径；环境通过 `PATH` 或命令参数定位 Voxtype；设 `UMask=0077`、`NoNewPrivileges=true`、`Restart=on-failure`。用户服务默认不写 `WantedBy` 自动启用，除非用户执行安装器显式选择启用。

- [ ] **步骤 3：实现服务安全文档**

解释全局鼠标监听的影响、如何停止 `systemctl --user stop voxtype-mouse-hold.service`、如何禁用 `systemctl --user disable --now voxtype-mouse-hold.service`、兼容限制和如何只保留语音剪贴板而关闭自动回填。

- [ ] **步骤 4：运行干净环境检查**

运行：`python3 -m pytest extras/mouse-hold/tests -q`、`systemd-analyze --user verify <生成后的服务文件>`（无 systemd-analyze 时记录原因）及基础计划的临时 HOME 安装器测试。

预期：单测 PASS；服务模板在生成后语法有效；不影响 Voxtype `config.toml` 和模型目录。

- [ ] **步骤 5：提交**

```bash
git add extras/mouse-hold/requirements.txt extras/mouse-hold/voxtype-mouse-hold.service.in extras/mouse-hold/README.md
git commit -m "docs: package optional mouse listener service"
```

## 真实桌面验收

- [ ] 在 X11 会话中确认安装前后 `voxtype status` 可用，右 Alt 录音未受影响。
- [ ] 以合成识别文本分别测试 GTK 输入框、浏览器输入框和终端，不录制真实对话内容。
- [ ] 明确记录真实测试软件、窗口类型和结果；任何未测软件保持“未验证”。
- [ ] 执行停用与卸载，确认不删除模型、配置和用户已有数据。
