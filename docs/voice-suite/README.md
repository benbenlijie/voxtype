# Voxtype 语音配套功能

## 这是什么

Voxtype 仍负责录音、语音识别和输出。中文文字处理和鼠标启动是可选配套，不替换 Voxtype 核心，也不改变它的录音流程。未安装可选配套时，Voxtype 按现有配置工作。

当前配置示例保留 `RIGHTALT` 作为热键名称，但内置热键仍是关闭状态（`enabled = false`）；因此它不会擅自接管按键。普通输出仍使用 Voxtype 的 `type` 模式。

## 安装和启用

安装器只处理当前检出中实际存在的可选文件：

```sh
bash scripts/install-voice-suite.sh
```

基础目录尚无可安装功能时，安装器会明确退出，不会创建空目录并宣称安装成功。安装器行为和保留范围见[安装说明](install.md)。

中文处理程序已随项目提供。安装后，先按[安装说明](install.md)安装固定版本的运行依赖，再在 Voxtype 配置中启用：

```toml
[output.post_process]
command = "voxtype-zh-post"
timeout_ms = 30000
trim = true
fallback_on_empty = true
```

上述字段均属于 Voxtype 已有的后处理设置。该命令接收标准输入中的识别文字，并把处理结果写到标准输出；Voxtype 在超时、命令失败或空结果时按配置回退原文。默认进行繁体转简体和保守空格修整。用户自行选择和安装模型后，可通过 `VOXTYPE_PUNCTUATION_COMMAND` 指定自己的标点适配程序；项目不提供、不下载或打包模型。接入约定见[中文处理说明](../../extras/chinese-postprocess/model-source.md)。

鼠标助手仅限 Linux X11。安装时默认不启动；只有在安装 Python 依赖并确认 Voxtype 路径后，才明确启用：

```sh
bash scripts/install-voice-suite.sh --enable-mouse
```

安装器会根据模板生成用户级服务文件。不要手动添加鼠标字段到 Voxtype 的 `config.toml`。

## 录音与日常使用

Voxtype 的录音控制仍使用其现有命令，例如：

```sh
voxtype record start
voxtype record stop
voxtype record cancel
```

鼠标助手若已提供并启用，则按[安全与兼容性说明](safety-and-compatibility.md)中的手势约定触发录音。鼠标助手不会自动发送识别结果。遇到焦点不确定时，结果应只留在剪贴板，交由用户自行决定粘贴位置。

## 停用和卸载

暂时停止鼠标服务：

```sh
systemctl --user stop voice-suite-mouse.service
```

同时禁止它再次启动：

```sh
systemctl --user disable --now voice-suite-mouse.service
```

移除本项目已安装的配套文件：

```sh
bash scripts/uninstall-voice-suite.sh
```

卸载不会删除 Voxtype 配置、模型或其他用户数据；安装时生成的备份会保留。详见[安装说明](install.md)。

## 已验证范围

公开文件边界和安装器测试使用本地文件、临时用户目录及替身 `systemctl`；配套单元测试验证了手势状态机、窗口与剪贴板保护，但没有真实桌面、浏览器、聊天软件或终端验收。具体应用兼容性仍需在目标机器上逐项实测。

当前环境的 Cargo 版本为 1.75，无法读取仓库使用的 v4 锁文件格式，因此本阶段没有把 `cargo test config:: --lib` 记为通过；需在较新的 Cargo 环境中补跑。
