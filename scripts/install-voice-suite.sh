#!/usr/bin/env bash
set -euo pipefail

usage() {
  printf '用法：%s [--enable-mouse]\n' "${0##*/}" >&2
}

enable_mouse=false
while (($#)); do
  case "$1" in
    --enable-mouse) enable_mouse=true ;;
    -h|--help) usage; exit 0 ;;
    *) usage; printf '不认识的选项：%s\n' "$1" >&2; exit 2 ;;
  esac
  shift
done

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(cd -- "$script_dir/.." && pwd -P)"
home_dir="${HOME:?HOME must be set}"
share_root="$home_dir/.local/share/voice-suite"
manifest="$share_root/.installed-files"
mouse_service_source="$repo_root/extras/mouse-hold/voice-suite-mouse.service"

has_files() {
  [[ -d "$1" ]] && find "$1" -type f -print -quit | grep -q .
}

if "$enable_mouse"; then
  if [[ ! -f "$mouse_service_source" ]]; then
    printf '鼠标配套服务模板缺失；当前检出未包含该功能，未安装任何内容。\n' >&2
    exit 1
  fi
  if ! command -v systemctl >/dev/null 2>&1; then
    printf '找不到 systemctl，无法启用鼠标服务。\n' >&2
    exit 1
  fi
fi

components=()
for component in chinese-postprocess mouse-hold; do
  if has_files "$repo_root/extras/$component"; then
    components+=("$component")
  fi
done
if ((${#components[@]} == 0)) && [[ ! -f "$mouse_service_source" ]]; then
  printf '当前检出没有可安装的可选配套内容；未安装任何内容。\n' >&2
  exit 1
fi

mkdir -p -- "$share_root"
manifest_tmp="$(mktemp "$share_root/.installed-files.XXXXXX")"
cleanup() { rm -f -- "$manifest_tmp"; }
trap cleanup EXIT
if [[ -f "$manifest" ]]; then
  cat -- "$manifest" > "$manifest_tmp"
fi

record_path() {
  local path="$1"
  if ! grep -Fqx -- "$path" "$manifest_tmp"; then
    printf '%s\n' "$path" >> "$manifest_tmp"
  fi
}

install_file() {
  local source="$1" destination="$2" relative_home="$3" backup
  mkdir -p -- "$(dirname -- "$destination")"
  if [[ -e "$destination" || -L "$destination" ]]; then
    backup="$destination.bak-$(date +%Y%m%d%H%M%S)"
    while [[ -e "$backup" || -L "$backup" ]]; do backup="$backup-$$"; done
    cp -a -- "$destination" "$backup"
    printf '已备份现有文件：%s\n' "$backup"
  fi
  cp -p -- "$source" "$destination"
  record_path "$relative_home"
}

for component in "${components[@]}"; do
  source_dir="$repo_root/extras/$component"
  while IFS= read -r -d '' source_file; do
    relative="${source_file#"$source_dir"/}"
    install_file "$source_file" "$share_root/$component/$relative" ".local/share/voice-suite/$component/$relative"
    if [[ "$component" == chinese-postprocess && "$relative" == bin/* ]]; then
      command_name="${relative#bin/}"
      install_file "$source_file" "$home_dir/.local/bin/$command_name" ".local/bin/$command_name"
    fi
  done < <(find "$source_dir" -type f -print0)
done

if [[ -f "$mouse_service_source" ]]; then
  install_file "$mouse_service_source" \
    "$home_dir/.config/systemd/user/voice-suite-mouse.service" \
    ".config/systemd/user/voice-suite-mouse.service"
  if "$enable_mouse"; then
    systemctl --user enable --now voice-suite-mouse.service
  else
    printf '鼠标服务已安装但未启用；如确认需要，再用 systemctl --user enable --now voice-suite-mouse.service 启用。\n'
  fi
fi

chmod 600 "$manifest_tmp"
mv -f -- "$manifest_tmp" "$manifest"
trap - EXIT
printf '已安装可用的语音配套文件到用户目录。Voxtype 本体、模型和配置均未修改。\n'
