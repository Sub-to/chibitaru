#!/usr/bin/env bash
# 会話AI のモデルを落とす。
#
#   sudo install/qwen.sh            プロファイルに合ったものを落とす
#   sudo install/qwen.sh --list     選べるものを見る
#
# モデルはリポジトリに入れていない（1.1GB あるため）。この機体で
# 落として置く。
#
# 実行ファイル（llama-server）のほうは bin/linux-x64 に入っている。
# whisper と違って作り直さない — あれは古い CPU に無い命令を使って
# 落ちることがあるので現地で作るが、こちらは実行時に CPU を見て
# 適した部品（libggml-cpu-*.so）を自分で選ぶ。T440s では haswell 用が
# 選ばれるのを確認した。
set -euo pipefail

ROOT="${CHIBITARU_ROOT:-/opt/chibitaru}"
DEST="$ROOT/models"
BASE=https://huggingface.co

# プロファイル → モデル。載る大きさが機体で違う。
#   8g … 1.5B。会話らしい返事ができる下限
#   4g … 0.5B。設定を触るだけならこれで足りる
list() {
  cat <<EOF
  8g  Qwen2.5-1.5B-Instruct-Q4_K_M   約1.1GB  使用時 +850MB
  4g  Qwen2.5-0.5B-Instruct-Q4_K_M   約400MB  使用時 +330MB
EOF
}

url_for() {
  case "$1" in
    8g) echo "$BASE/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf" ;;
    4g) echo "$BASE/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf" ;;
    *)  return 1 ;;
  esac
}

if [ "${1:-}" = "--list" ]; then list; exit 0; fi

profile=8g
if [ -r /etc/chibitaru/profile ]; then
  profile=$(awk -F= '/^CHIBITARU_PROFILE=/{print $2}' /etc/chibitaru/profile)
fi
url=$(url_for "$profile") || {
  echo "プロファイル $profile に合うモデルがありません" >&2; exit 1; }
name=$(basename "$url")

mkdir -p "$DEST"
if [ -s "$DEST/$name" ]; then
  echo "既にあります: $DEST/$name"
  exit 0
fi

echo "落とします: $name"
echo "  置き場所: $DEST"
# -C - で途中から。テザリングでは切れることがある。
curl -fL --retry 5 --retry-delay 3 -C - --progress-bar \
  -o "$DEST/$name.part" "$url"

# 大きさを本家と突き合わせる。途中で切れたものを置くと、
# llama-server は起動して壊れた答えを返す。落ちてくれない分たちが悪い。
want=$(curl -sIL "$url" | awk 'tolower($1)=="content-length:"{n=$2} END{gsub(/\r/,"",n); print n}')
got=$(stat -c%s "$DEST/$name.part")
if [ -n "$want" ] && [ "$want" != "$got" ]; then
  echo "大きさが合いません（本家 $want / 手元 $got）。消します。" >&2
  rm -f "$DEST/$name.part"
  exit 1
fi

mv "$DEST/$name.part" "$DEST/$name"
chmod 644 "$DEST/$name"
echo "できました: $DEST/$name"
echo
echo "  確かめる:   chibitaru-ai --status"
echo "  訊いてみる: chibitaru-ai \"まぶしい\""
