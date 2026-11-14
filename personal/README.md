# 个人中文听写配置

这套配置是 `personal-setup` 分支上的个人层：把「用得习惯」的 Voxtype 设置、
中文后处理脚本和 systemd 服务打包成一条命令可以还原的形态。

上游仓库（`peteonrails/voxtype`）不包含这些内容，因为它们是个人偏好，
不是通用功能。

## 快速开始

```bash
# 1. 先装 voxtype 本体（三选一）
#    Arch:   yay -S voxtype-bin
#    发行版: 下载官方 release 二进制放到 ~/.local/bin/
#    源码:   cargo build --release --features gpu-vulkan

# 2. 克隆并还原个人配置
git clone -b personal-setup https://github.com/benbenlijie/voxtype.git
cd voxtype
./personal/install.sh

# 3. 生效
systemctl --user restart voxtype.service
```

首次安装会下载 whisper 模型（约 1.6G）和标点模型（约 65MB），其余都是小文件。

## 系统依赖

| 依赖 | 用途 | 缺失后果 |
| --- | --- | --- |
| `voxtype` 1.1.x | 本体 | 无法安装 |
| `node` >= 18 | 标点恢复 | 跳过标点，繁转简仍可用 |
| `libopencc` + `t2s.json` | 繁转简 | 跳过转换，原文照出 |
| `python3` | 繁转简适配器 | 跳过繁转简 |
| `npm` | 安装 `sherpa-onnx-node` | 标点恢复不可用 |
| `curl` / `tar` | 下载标点模型 | 需手动放置模型 |

Ubuntu/Debian 上补 OpenCC：

```bash
sudo apt install libopencc1.1 opencc
```

## 装了什么

| 路径 | 内容 |
| --- | --- |
| `~/.config/voxtype/config.toml` | 由 `config.toml.in` 渲染，`@HOME@` 换成实际家目录 |
| `~/.local/bin/voxtype-zh-post` | 繁转简 + 标点恢复，接在 `[output.post_process]` 上 |
| `~/.local/bin/voxtype-t2s` | OpenCC 繁转简（ctypes 调 libopencc） |
| `~/.local/bin/voxtype-polish-zh` | 可选的 ollama 润色，默认不挂在配置里 |
| `~/.local/lib/voxtype-punc/` | `punc.js` + `sherpa-onnx-node` |
| `~/.local/share/voxtype/punct/` | 标点模型 `model.int8.onnx` |
| `~/.local/share/voxtype/models/` | whisper 模型（由 `voxtype setup` 下载） |
| `~/.config/systemd/user/voxtype.service` | 用户服务，默认不写死声卡 |

## 配置与上游默认的差异

| 项 | 值 | 原因 |
| --- | --- | --- |
| `whisper.model` | `large-v3-turbo` | 中文准确率 |
| `whisper.language` | `zh` | 短句不会被误判成英文 |
| `whisper.flash_attention` | `true` | GPU 显存和速度 |
| `output.mode` | `clipboard` | 粘贴交给鼠标配套或手动 |
| `output.paste_keys` | `shift+insert` | 终端里也能粘贴 |
| `output.post_process.command` | `voxtype-zh-post` | 中文标点 |
| `hotkey.enabled` | `false` | 由鼠标配套或外部命令触发 |

其余选项沿用仓库的 `config/default.toml`。

## 选项

```bash
personal/install.sh --with-mouse    # 顺带装鼠标长按配套（X11）
personal/install.sh --skip-models   # 不检查/下载模型
personal/install.sh --no-service    # 只装脚本和配置
personal/install.sh --dry-run       # 先看会做什么
```

## 为什么不把模型和二进制放进仓库

- whisper `large-v3-turbo` 1.6G、标点模型 65MB，GitHub 不适合放大文件。
- 上游 `extras/chinese-postprocess/README.md` 明确不提供、不再分发模型。
- 二进制和 glibc 版本绑定（见下），换机器应该重新编译或装对应发行版包。

所以模型由 `install.sh` 从公开来源下载，二进制由使用者自己解决。

## Ubuntu 22.04 的坑

官方 release 的 `vulkan` 二进制在 Ubuntu 24.04 上构建，需要 glibc 2.38/2.39，
22.04（glibc 2.35）跑不起来。22.04 上需要从源码编译：

```bash
cargo build --release --features gpu-vulkan
```

编译依赖（Vulkan-Headers、glslc）见原机器上的 `BUILD-NOTES.md`。

## 更新

```bash
cd voxtype && git pull && ./personal/install.sh
```

`install.sh` 可以重复执行：配置会先备份成 `config.toml.bak-<时间戳>`，
`node_modules` 已存在时跳过 npm。

## 卸载

```bash
systemctl --user disable --now voxtype.service
rm -f ~/.local/bin/voxtype-{zh-post,t2s,polish-zh}
rm -rf ~/.local/lib/voxtype-punc
rm -f ~/.config/systemd/user/voxtype.service
rm -f ~/.config/voxtype/config.toml   # 想保留就先备份
```

模型可以留着，重装时不用再下 1.6G。

## 相关分支

- `feat/voice-suite`：中文后处理配套、标点模型接入约定、安装脚本
- `feat/mouse-hold`：鼠标长按录音 + 安全回填（X11）
- `dev`：与上游同步的分支
