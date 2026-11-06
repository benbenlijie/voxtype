#!/usr/bin/env bash
set -euo pipefail

home_dir="${HOME:?HOME must be set}"
share_root="$home_dir/.local/share/voice-suite"
manifest="$share_root/.installed-files"
service_file="$home_dir/.config/systemd/user/voice-suite-mouse.service"

if [[ -f "$service_file" ]] && command -v systemctl >/dev/null 2>&1; then
  systemctl --user stop voice-suite-mouse.service || true
  systemctl --user disable voice-suite-mouse.service || true
fi

if [[ -f "$manifest" ]]; then
  while IFS= read -r relative || [[ -n "$relative" ]]; do
    case "$relative" in
      *../*|*/..|../*) printf '跳过清单中含有路径回退的条目。\n' >&2 ;;
      .local/share/voice-suite/*|.local/bin/voice-suite-*|.local/bin/voxtype-zh-post|.config/systemd/user/voice-suite-mouse.service)
        target="$home_dir/$relative"
        if [[ -f "$target" || -L "$target" ]]; then
          rm -f -- "$target"
        fi
        ;;
      '') ;;
      *) printf '跳过清单中不在允许范围内的路径：%s\n' "$relative" >&2 ;;
    esac
  done < "$manifest"
  rm -f -- "$manifest"
fi
if command -v systemctl >/dev/null 2>&1; then
  systemctl --user daemon-reload || true
fi

# Remove only empty directories created for the optional suite.
for directory in \
  "$home_dir/.local/bin" \
  "$home_dir/.local/share/voice-suite/chinese-postprocess" \
  "$home_dir/.local/share/voice-suite/mouse-hold" \
  "$share_root" \
  "$home_dir/.config/systemd/user"; do
  rmdir -- "$directory" 2>/dev/null || true
done
printf '已移除语音配套文件；Voxtype 配置、模型和其他用户数据均保留。\n'
