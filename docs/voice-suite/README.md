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

中文处理尚未由基础阶段提供。等中文配套程序确实包含在项目并安装后，才可在 Voxtype 配置中启用示例：

```toml
[output.post_process]
command = "voxtype-zh-post"
timeout_ms = 30000
trim = true
fallback_on_empty = true
```

上述字段均属于 Voxtype 已有的后处理设置。该命令接收标准输入中的识别文字，并把处理结果写到标准输出；Voxtype 在超时、命令失败或空结果时按配置回退原文。没有安装 `voxtype-zh-post` 时，不要启用这段配置。

鼠标助手仅限 Linux X11，并且必须由用户明确启用：

```sh
bash scripts/install-voice-suite.sh --enable-mouse
```

若鼠标服务模板尚未包含，安装器会在写入前拒绝该选项。不要手动添加猜测的鼠标字段到 Voxtype 的 `config.toml`；鼠标设置应由该配套自己的配置负责，具体字段和位置以实际提供的鼠标配套文档为准。

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

基础阶段的公开文件边界测试和安装器测试使用本地文件、临时用户目录及替身 `systemctl`；这只验证文件范围和脚本行为，不代表真实桌面、鼠标手势或具体应用已验收。基础阶段未包含中文处理程序或鼠标服务实现，相关命令只有在对应配套实际提供后才可使用。

当前环境的 Cargo 版本为 1.75，无法读取仓库使用的 v4 锁文件格式，因此本阶段没有把 `cargo test config:: --lib` 记为通过。配置示例和说明尚未证明通过该 Rust 配置测试；在支持该锁文件格式的 Cargo 环境中仍需补跑。
