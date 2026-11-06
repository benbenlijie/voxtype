# Voxtype 配套功能整合基础实施计划

> **给代理开发者：** 必须按任务逐项执行；可使用 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans`。测试先行，按每个任务明确的文件清单提交；不得使用 `git add .`。

**目标：** 在保留 Voxtype 上游代码和右 Alt 录音行为的前提下，为中文处理和鼠标助手建立可移植、可选启用、能从干净检出安装的项目结构。

**架构：** Voxtype 继续负责录音、识别和默认输出；新增的中文处理器通过现有 `[output.post_process]` 命令接口接入，鼠标助手作为独立的 Linux X11 可选服务，通过 `voxtype record start/stop/cancel` 调用核心。项目文档、依赖、安装和卸载方式统一整理，两个配套功能各自保持可单独启用。

**技术栈：** Rust/Cargo（Voxtype）；Python 3、pytest、python-xlib（鼠标服务）；Node.js 与 sherpa-onnx-node（中文标点处理，最终依赖方案须经下一子计划确认）；systemd 用户服务。

---

## 文件职责

- `extras/chinese-postprocess/`：中文转写后处理程序、依赖清单、模型获取说明和针对本地文字处理的测试。
- `extras/mouse-hold/`：鼠标手势监听、焦点保护、剪贴板与回填模块、systemd 用户服务模板及 pytest 测试。
- `scripts/install-voice-suite.sh`、`scripts/uninstall-voice-suite.sh`：按用户目录安装或移除配套程序；不构建、不覆盖 Voxtype 核心，不删除用户模型和配置。
- `docs/voice-suite/`：中文快速开始、权限与安全边界、X11 和应用兼容性说明、排错和卸载说明。
- `config/default.toml`：只更新可复制使用的配套配置示例，不写入本机绝对路径，也不改变 Voxtype 默认快捷键。
- 项目 `.gitignore`：排除模型权重、缓存、运行时转写文件、覆盖测试输出和用户私有日志。

## 执行顺序

先完成本计划的可移植目录、安装与文档骨架，再按独立子计划实施中文处理和鼠标助手。两个配套子计划必须通过本计划定义的干净检出安装和卸载验收后才算整合完成。

### 任务 1：确定新增目录和公开文件边界

**文件：**
- 新建：`extras/chinese-postprocess/`
- 新建：`extras/mouse-hold/`
- 新建：`docs/voice-suite/`
- 修改：`.gitignore`

- [ ] **步骤 1：添加文件边界检查测试**

创建 `extras/tests/test_public_tree.py`，测试仓库树不包含 `*.onnx`、`*.bin`、`*.wav`、`*.pyc`、`__pycache__`、`.pytest_cache`、运行时 `transcript` 文件，以及含 `/home/`、`/Users/` 的安装脚本或服务模板。测试使用 `pathlib.Path(".").rglob("*")`，跳过 `.git`、`target` 和 `node_modules`。

- [ ] **步骤 2：确认测试先失败**

运行：`python3 -m pytest extras/tests/test_public_tree.py -q`

预期：因测试文件存在而通过；随后临时在测试夹具目录生成被禁止扩展名样例，确认断言能够指出违规相对路径；删除该夹具。

- [ ] **步骤 3：添加公开树忽略规则**

只添加明确的运行产物规则，不得忽略整个 `extras/`：

```gitignore
**/__pycache__/
**/.pytest_cache/
**/node_modules/
**/*.py[cod]
**/*.onnx
**/*.bin
**/*.wav
**/transcript
**/transcript.tmp
```

- [ ] **步骤 4：运行边界测试并检查差异**

运行：`python3 -m pytest extras/tests/test_public_tree.py -q`

预期：PASS；运行 `git diff --check`，预期无空白错误。

- [ ] **步骤 5：提交**

```bash
git add .gitignore extras/tests/test_public_tree.py
git commit -m "test: define public voice suite file boundaries"
```

### 任务 2：定义安装器输入与安全行为

**文件：**
- 新建：`scripts/install-voice-suite.sh`
- 新建：`scripts/uninstall-voice-suite.sh`
- 新建：`extras/tests/test_install_scripts.py`
- 新建：`docs/voice-suite/install.md`

- [ ] **步骤 1：写 shell 行为测试**

`extras/tests/test_install_scripts.py` 用临时 `HOME` 和替身 `systemctl` 检查：
1. 安装脚本安装目录只能落在 `${HOME}/.local/` 下；
2. 脚本不能对 `config.toml`、`models/` 或系统目录执行删除；
3. `--enable-mouse` 缺省不自动启用服务；
4. 卸载先停用、移除服务和脚本，不删除 `~/.local/share/voxtype`、`~/.config/voxtype`；
5. `bash -n` 对两个脚本返回 0。

- [ ] **步骤 2：确认行为测试先失败**

运行：`python3 -m pytest extras/tests/test_install_scripts.py -q`

预期：失败，提示脚本尚不存在。

- [ ] **步骤 3：实现最小安装和卸载脚本**

脚本使用 `set -euo pipefail`；从脚本自身路径解析仓库根目录；所有目标路径通过 `HOME` 拼接；安装覆盖文件前将旧的同名配套文件保存为带日期后缀的 `.bak-*`；卸载仅移除本项目安装的精确文件清单。鼠标服务只在明确传入 `--enable-mouse` 时执行 `systemctl --user enable --now`。

- [ ] **步骤 4：安装到临时目录并验证**

运行：
`python3 -m pytest extras/tests/test_install_scripts.py -q`

预期：PASS；替身 `systemctl` 只在 `--enable-mouse` 时记录 enable/start；临时 HOME 外无文件变化。

- [ ] **步骤 5：提交**

```bash
git add scripts/install-voice-suite.sh scripts/uninstall-voice-suite.sh extras/tests/test_install_scripts.py docs/voice-suite/install.md
git commit -m "feat: add safe per-user voice suite installer"
```

### 任务 3：提供项目级配置示例与功能边界说明

**文件：**
- 修改：`config/default.toml`
- 新建：`docs/voice-suite/README.md`
- 新建：`docs/voice-suite/safety-and-compatibility.md`

- [ ] **步骤 1：先核对现有配置入口**

检查 `config/default.toml` 中 `[hotkey]`、`[output]`、`[output.post_process]` 段落及 `src/config/profile.rs` 的默认和覆盖规则；不得添加 Voxtype 不支持的配置字段。

- [ ] **步骤 2：整理配置示例**

示例保留 `key = "RIGHTALT"` 和核心默认输出；后处理命令使用安装器提供的命令名，不含个人绝对路径。鼠标配置只写入其独立配置文件，并说明该功能当前限 X11。

- [ ] **步骤 3：写边界说明**

明确说明：鼠标左键长按 0.5 秒；录音中超过 100 像素取消；松开结束；不自动发送；普通应用一次 `Ctrl+V`，终端使用适配方式；目标焦点不安全时只留剪贴板；Wayland、macOS、Windows 及每个真实应用尚未验证，均不能宣称支持。

- [ ] **步骤 4：检查配置和文档**

运行：`cargo test config:: --lib`

预期：配置相关测试 PASS；人工扫描新文件确保不出现个人绝对路径、Hermes 私有目录、聊天内容或语音模型权重。

- [ ] **步骤 5：提交**

```bash
git add config/default.toml docs/voice-suite/README.md docs/voice-suite/safety-and-compatibility.md
git commit -m "docs: explain voice suite setup and safety boundaries"
```

### 任务 4：干净检出安装、卸载和上游核对

**文件：**
- 测试：`extras/tests/test_public_tree.py`
- 测试：`extras/tests/test_install_scripts.py`
- 验证：`Cargo.toml`、`Cargo.lock`、`.gitignore`

- [ ] **步骤 1：检查公开变更范围**

运行：`git status --short`、`git diff origin/dev...HEAD --stat`、`git diff --check`。

预期：只有明确列出的配套文件；不得带入本机 `Cargo.toml`/`Cargo.lock` 临时 OpenVINO 调整、`BUILD-NOTES.md`、`target/` 或语音模型。

- [ ] **步骤 2：从临时干净副本运行套件检查**

运行：
```bash
tmp="$(mktemp -d)"
git archive HEAD | tar -x -C "$tmp"
cd "$tmp"
python3 -m pytest extras/tests -q
bash -n scripts/install-voice-suite.sh scripts/uninstall-voice-suite.sh
cargo test config:: --lib
```

预期：公开树与安装器测试 PASS，TOML 相关测试 PASS；若缺少操作系统依赖，记录依赖名称，不从当前机器路径伪装通过。

- [ ] **步骤 3：检查上游来源**

运行：`git remote -v`、`git log -1 --format='%H %s'`。

预期：`origin` 指向用户的 `benbenlijie/voxtype`，上游远程仍可追踪 `peteonrails/voxtype`；不得将分支或推送目标改为上游仓库。

- [ ] **步骤 4：提交验收记录**

在 `docs/voice-suite/README.md` 增加实际可复现的安装、停用、卸载命令及已验证范围；不把模拟桌面测试说成真实应用验收。

运行：`git diff --check`，预期无输出。

- [ ] **步骤 5：提交**

```bash
git add docs/voice-suite/README.md
git commit -m "docs: record clean checkout validation"
```
