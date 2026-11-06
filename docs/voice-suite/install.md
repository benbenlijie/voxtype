# 安装与卸载语音配套功能

## 安装

在仓库根目录运行：

```sh
bash scripts/install-voice-suite.sh
```

安装器只把仓库中实际存在的可选配套文件复制到当前用户目录（`~/.local/share/voice-suite`、`~/.local/bin` 和鼠标服务对应的用户级 `systemd` 目录）。它不会构建或替换 Voxtype，也不会改动 `~/.config/voxtype`、`~/.local/share/voxtype` 或系统目录。若目标位置已有同名配套文件，安装器会先在原处留下带 `.bak-日期时间` 后缀的备份。

当前基础目录可能尚未包含中文处理或鼠标服务文件。安装器会跳过缺失的部分；若没有任何可安装内容，会明确报错并退出，不会创建“已安装”的空功能目录。鼠标服务模板缺失时，`--enable-mouse` 会在写入前退出。

鼠标服务默认只安装、不启动。只有明确选择后才会启用：

```sh
bash scripts/install-voice-suite.sh --enable-mouse
```

这需要 Linux 用户会话中的 `systemctl`，且仓库中必须有鼠标服务模板。不要仅为测试而对真实桌面启用服务。

## 卸载

在仓库根目录运行：

```sh
bash scripts/uninstall-voice-suite.sh
```

卸载时会先尝试停止并禁用本项目的鼠标用户服务，然后仅删除安装清单中属于本项目的精确文件。它不会递归清理目录，也不会删除 Voxtype 配置、模型、录音或其他用户文件。只会尝试移除因此变空的配套目录；安装时创建的 `.bak-*` 备份会保留，需由用户自行检查和清理。

如果鼠标功能之后需要单独停用但暂不卸载，可运行：

```sh
systemctl --user disable --now voice-suite-mouse.service
```

## 当前验证范围

安装和卸载行为通过临时用户目录及替身 `systemctl` 测试；这不等同于在真实桌面或每个应用中完成验收。基础阶段尚未包含配套程序时，测试会用临时样例文件验证复制、备份、显式启用和精确卸载行为。
