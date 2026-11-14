#!/usr/bin/env bash
# 在另一台机器上还原这套 Voxtype 中文听写配置。
#
# 前置条件：voxtype 本体已经装好（AUR voxtype-bin、官方 release 二进制，
# 或者按 docs 自行编译）。本脚本只负责个人层：配置、后处理脚本、标点模型、
# X11 自动粘贴助手、systemd 用户服务。
set -euo pipefail

usage() {
  cat <<'EOF'
用法：personal/install.sh [选项]

  --with-mouse     顺带安装并启用鼠标长按配套（X11，可选）
  --skip-models    跳过模型检查与下载
  --no-service     只装脚本和配置，不碰 systemd
  --dry-run        只打印将要执行的动作
  -h, --help       显示本帮助

可用环境变量：
  VOXTYPE_WHISPER_MODEL  要检查的 whisper 模型名（默认 large-v3-turbo）
EOF
}

with_mouse=false
skip_models=false
no_service=false
dry_run=false

while (($#)); do
  case "$1" in
    --with-mouse) with_mouse=true ;;
    --skip-models) skip_models=true ;;
    --no-service) no_service=true ;;
    --dry-run) dry_run=true ;;
    -h|--help) usage; exit 0 ;;
    *) usage; printf '不认识的选项：%s\n' "$1" >&2; exit 2 ;;
  esac
  shift
done

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(cd -- "$script_dir/.." && pwd -P)"
home_dir="${HOME:?HOME must be set}"

bin_dir="$home_dir/.local/bin"
lib_dir="$home_dir/.local/lib/voxtype-punc"
conf_dir="$home_dir/.config/voxtype"
unit_dir="$home_dir/.config/systemd/user"
data_dir="$home_dir/.local/share/voxtype"
punct_model_dir="$data_dir/punct"
whisper_model="${VOXTYPE_WHISPER_MODEL:-large-v3-turbo}"

PUNCT_TARBALL_URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/punctuation-models/sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12-int8.tar.bz2"

say() { printf '==> %s\n' "$*"; }
warn() { printf '警告：%s\n' "$*" >&2; }

run() {
  if "$dry_run"; then
    printf '[dry-run] %s\n' "$*"
  else
    "$@"
  fi
}

# ---------------------------------------------------------------- 1. 依赖检查

say "检查依赖"
missing=0
voxtype_bin="$(command -v voxtype 2>/dev/null || true)"
if [[ -z "$voxtype_bin" && -x "$bin_dir/voxtype" ]]; then
  voxtype_bin="$bin_dir/voxtype"
fi
if [[ -z "$voxtype_bin" ]]; then
  warn "找不到 voxtype 可执行文件。请先安装 voxtype 本体，本脚本不会替你编译。"
  missing=1
else
  voxtype_version="$("$voxtype_bin" --version 2>/dev/null | awk '{print $2}' || true)"
  if [[ -n "$voxtype_version" && ! "$voxtype_version" =~ ^1\. ]]; then
    warn "检测到 voxtype $voxtype_version；personal 配置以 1.1.x 为目标，部分选项可能被忽略。"
  fi
fi
if ! command -v node >/dev/null 2>&1; then
  warn "找不到 node。标点恢复会被跳过，繁转简仍然可用（装好 node 后重跑本脚本即可）。"
fi
if ! command -v python3 >/dev/null 2>&1; then
  warn "找不到 python3。繁转简（voxtype-t2s）会被跳过。"
fi
if ! command -v curl >/dev/null 2>&1; then
  warn "找不到 curl。标点模型需要手动下载。"
fi
if ! command -v xdotool >/dev/null 2>&1 || ! command -v xprop >/dev/null 2>&1; then
  warn "找不到 xdotool/xprop。X11 自动粘贴助手不可用，仍可手动粘贴剪贴板内容。"
fi
if ((missing)); then
  exit 1
fi

# ---------------------------------------------------- 2. 可选：鼠标长按配套
#
# 必须放在安装个人脚本之前：配套安装器会把自己的 voxtype-zh-post 放到
# ~/.local/bin，随后个人版覆盖回来才是想要的结果。

if "$with_mouse"; then
  say "安装鼠标长按配套"
  if [[ -x "$repo_root/scripts/install-voice-suite.sh" ]]; then
    run bash "$repo_root/scripts/install-voice-suite.sh" --enable-mouse
  else
    warn "仓库里找不到 scripts/install-voice-suite.sh，跳过鼠标配套。"
  fi
fi

# ------------------------------------------------------------ 3. 安装脚本本体

say "安装后处理脚本到 $bin_dir"
run mkdir -p "$bin_dir"
for name in voxtype-zh-post voxtype-t2s voxtype-polish-zh voxtype-paste-x11; do
  run install -m 0755 "$script_dir/bin/$name" "$bin_dir/$name"
done

# ------------------------------------------------------- 3. 标点恢复运行时

say "安装标点恢复脚本与 node 依赖到 $lib_dir"
run mkdir -p "$lib_dir"
run install -m 0644 "$script_dir/lib/punc.js" "$lib_dir/punc.js"
run install -m 0644 "$script_dir/lib/package.json" "$lib_dir/package.json"

if command -v npm >/dev/null 2>&1; then
  if [[ -d "$lib_dir/node_modules/sherpa-onnx-node" ]] && ! "$dry_run"; then
    say "sherpa-onnx-node 已存在，跳过 npm install"
  else
    say "npm install（首次约 30MB）"
    run npm --prefix "$lib_dir" install --omit=dev --no-audit --no-fund
  fi
else
  warn "找不到 npm，跳过 node 依赖安装；标点恢复不可用。"
fi

# --------------------------------------------------------------- 4. 写配置

say "渲染配置模板到 $conf_dir/config.toml"
run mkdir -p "$conf_dir"
if [[ -f "$conf_dir/config.toml" && "$dry_run" == false ]]; then
  backup="$conf_dir/config.toml.bak-$(date +%Y%m%d%H%M%S)"
  cp -a -- "$conf_dir/config.toml" "$backup"
  say "已备份原配置到 $backup"
fi

rendered="$(mktemp)"
while IFS= read -r line || [[ -n "$line" ]]; do
  printf '%s\n' "${line//@HOME@/$home_dir}"
done < "$script_dir/config.toml.in" > "$rendered"
if "$dry_run"; then
  printf '[dry-run] 写入 %s（%s 行）\n' "$conf_dir/config.toml" "$(wc -l < "$rendered")"
  rm -f -- "$rendered"
else
  install -m 0644 "$rendered" "$conf_dir/config.toml"
  rm -f -- "$rendered"
fi

# ---------------------------------------------------------- 5. systemd 服务

if "$no_service"; then
  say "按 --no-service 跳过 systemd 安装"
else
  say "安装 systemd 用户服务"
  run mkdir -p "$unit_dir"
  run install -m 0644 "$script_dir/systemd/voxtype.service.in" "$unit_dir/voxtype.service"

  if command -v systemctl >/dev/null 2>&1 && [[ -n "${XDG_RUNTIME_DIR:-}" ]]; then
    run systemctl --user daemon-reload
    run systemctl --user enable --now voxtype.service
  else
    warn "当前环境没有可用的 systemd 用户会话，跳过启用。登录图形会话后手动执行："
    warn "  systemctl --user daemon-reload && systemctl --user enable --now voxtype.service"
  fi
fi

# --------------------------------------------------------------- 6. 模型

if "$skip_models"; then
  say "按 --skip-models 跳过模型检查"
else
  say "检查 whisper 模型（$whisper_model）"
  if [[ -n "$voxtype_bin" ]]; then
    if [[ "$whisper_model" == /* ]]; then
      whisper_model_file="$whisper_model"
    else
      whisper_model_file="$data_dir/models/ggml-${whisper_model}.bin"
    fi
    if [[ -f "$whisper_model_file" ]]; then
      say "whisper 模型已安装（$whisper_model_file）"
    elif "$voxtype_bin" info models 2>/dev/null | grep -qE "^[[:space:]]*installed[[:space:]]+${whisper_model}[[:space:]]*$"; then
      say "whisper 模型已安装"
    else
      say "下载 whisper 模型（约 1.6G）"
      run "$voxtype_bin" setup --download --model "$whisper_model"
    fi
  else
    warn "找不到 voxtype，无法自动下载模型。装好后执行：voxtype setup --download --model $whisper_model"
  fi

  say "检查标点模型"
  if [[ -f "$punct_model_dir/model.int8.onnx" || -f "$punct_model_dir/model.onnx" ]]; then
    say "标点模型已存在"
  elif command -v curl >/dev/null 2>&1 && command -v tar >/dev/null 2>&1; then
    if "$dry_run"; then
      say "下载标点模型（约 65MB）：$PUNCT_TARBALL_URL"
    else
      say "下载标点模型（约 65MB）"
      tmp_dir="$(mktemp -d)"
      # shellcheck disable=SC2064
      trap "rm -rf -- '$tmp_dir'" EXIT
      if curl -fL --retry 3 --progress-bar -o "$tmp_dir/punct.tar.bz2" "$PUNCT_TARBALL_URL"; then
        tar -xjf "$tmp_dir/punct.tar.bz2" -C "$tmp_dir"
        model_path="$(find "$tmp_dir" -name 'model.int8.onnx' -print -quit)"
        if [[ -z "$model_path" ]]; then
          model_path="$(find "$tmp_dir" -name 'model.onnx' -print -quit)"
        fi
        if [[ -n "$model_path" ]]; then
          mkdir -p "$punct_model_dir"
          install -m 0644 "$model_path" "$punct_model_dir/model.int8.onnx"
          say "标点模型已安装到 $punct_model_dir/model.int8.onnx"
        else
          warn "压缩包里没找到 onnx 模型，标点恢复将不可用。"
        fi
      else
        warn "标点模型下载失败，可稍后重跑本脚本。"
      fi
      rm -rf -- "$tmp_dir"
      trap - EXIT
    fi
  else
    warn "缺少 curl/tar，标点模型需要手动下载：$PUNCT_TARBALL_URL"
  fi
fi

# ------------------------------------------------------------- 7. 冒烟测试

if "$dry_run"; then
  say "跳过冒烟测试（dry-run）"
else
  say "冒烟测试：繁转简 + 标点"
  sample='我們今天測試一下中文聽寫的標點恢復'
  result="$(printf '%s' "$sample" | "$bin_dir/voxtype-zh-post" 2>/dev/null || true)"
  printf '   输入：%s\n' "$sample"
  printf '   输出：%s\n' "${result:-（空）}"
  if [[ -z "$result" ]]; then
    warn "后处理没有输出，检查 node 和标点模型。"
  fi

  if [[ -x "$bin_dir/voxtype-paste-x11" ]]; then
    paste_keys="$("$bin_dir/voxtype-paste-x11" --dry-run --class google-chrome | sed -n 's/^keys=//p' || true)"
    printf '   普通窗口粘贴键：%s\n' "$paste_keys"
    [[ "$paste_keys" == "ctrl+v" ]] || warn "普通窗口粘贴键映射异常。"
  fi
fi

say "完成。重启服务让配置生效： systemctl --user restart voxtype.service"
