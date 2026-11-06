#!/usr/bin/env bash
set -euo pipefail

root=$(cd -- "$(dirname -- "$0")/.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
mkdir "$tmp/bin"
cat > "$tmp/bin/node" <<'NODE_STUB'
#!/usr/bin/env bash
set -u
cat >/dev/null
case "${POSTPROCESS_TEST_MODE:-success}" in
  success) printf '%s' '处理后的示例文本' ;;
  empty) : ;;
  failure) printf '%s' '不应采用的结果'; exit 9 ;;
esac
NODE_STUB
chmod +x "$tmp/bin/node"

input='合成测试用的示例转写'
output=$(printf '%s' "$input" | PATH="$tmp/bin:$PATH" "$root/voxtype-zh-post" 2>"$tmp/stderr")
[[ "$output" == '处理后的示例文本' ]]
[[ ! -s "$tmp/stderr" ]]

for mode in failure empty; do
  output=$(printf '%s' "$input" | POSTPROCESS_TEST_MODE="$mode" PATH="$tmp/bin:$PATH" "$root/voxtype-zh-post" 2>"$tmp/stderr")
  [[ "$output" == "$input" ]]
  ! grep -Fq "$input" "$tmp/stderr"
done

: >"$tmp/called"
cat > "$tmp/bin/node" <<NODE_STUB
#!/usr/bin/env bash
printf called >> '$tmp/called'
cat >/dev/null
printf unexpected
NODE_STUB
chmod +x "$tmp/bin/node"
output=$(printf '  \n\t' | PATH="$tmp/bin:$PATH" "$root/voxtype-zh-post" 2>"$tmp/stderr")
[[ "$output" == $'  \n\t' ]]
[[ ! -s "$tmp/called" ]]
[[ ! -s "$tmp/stderr" ]]

# Keep the portable bundle free of copied workstation paths and private directories.
scan_files=(
  "$root/README.md"
  "$root/model-source.md"
  "$root/package.json"
  "$root/package-lock.json"
  "$root/punc.js"
  "$root/voxtype-zh-post"
)
if grep -nHE '(/home/[^[:space:]"'"'"']+|/Users/[^[:space:]"'"'"']+|[A-Za-z]:[\\/]Users[\\/]|\.hermes)' "${scan_files[@]}"; then
  printf 'portable bundle contains a workstation path\n' >&2
  exit 1
fi

printf 'CLI contract tests passed\n'
