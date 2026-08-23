#!/usr/bin/env bash
# 音声認識（whisper.cpp）を入れる。
#
# Debian にパッケージがないのでソースから作る。動かす機体で作るのが
# 確実 — 別の機体で作ったものは、その CPU にしか無い命令を使って
# いる場合があり、古い機体で落ちる。
#
#   bash install/whisper.sh            base モデル（142MB・既定）
#   bash install/whisper.sh small      small モデル（466MB・精度重視）
#
# 2 コアの Haswell で 10〜20 分かかる。
#
set -euo pipefail

MODEL="${1:-base}"
ROOT=/opt/chibitaru/whisper
SRC=/usr/local/src/whisper.cpp
# 版を固定する。master を追うと、次に入れた人と挙動が変わる。
TAG="${WHISPER_TAG:-v1.7.4}"

c_head() { printf "\n\033[1m  %s\033[0m\n" "$*"; }
c_ok()   { printf "    \033[32m*\033[0m %s\n" "$*"; }
c_warn() { printf "    \033[33m!\033[0m %s\n" "$*"; }
c_die()  { printf "\n  \033[31mNG: %s\033[0m\n\n" "$*" >&2; exit 1; }

[ "$(id -u)" = 0 ] || c_die "root で実行してください"

c_head "① 作るための道具"
export DEBIAN_FRONTEND=noninteractive
apt-get install -y -qq --no-install-recommends \
  build-essential cmake git ca-certificates >/dev/null
c_ok "build-essential / cmake"

c_head "② ソースを取る（${TAG}）"
if [ -d "$SRC/.git" ]; then
  git -C "$SRC" fetch --quiet --depth 1 origin "$TAG" 2>/dev/null || true
  git -C "$SRC" checkout --quiet "$TAG" 2>/dev/null || c_warn "指定の版に切り替えられず、現状のまま進みます"
else
  git clone --quiet --depth 1 --branch "$TAG" \
    https://github.com/ggerganov/whisper.cpp "$SRC" \
    || git clone --quiet --depth 1 https://github.com/ggerganov/whisper.cpp "$SRC"
fi
c_ok "$SRC ($(git -C "$SRC" describe --tags --always 2>/dev/null || echo 不明))"

c_head "③ ビルド（数分〜20分）"
CORES=$(nproc)
cmake -S "$SRC" -B "$SRC/build" \
      -DCMAKE_BUILD_TYPE=Release \
      -DWHISPER_BUILD_TESTS=OFF \
      -DWHISPER_BUILD_EXAMPLES=ON >/dev/null 2>&1 \
  || c_die "cmake の設定に失敗しました"
cmake --build "$SRC/build" -j "$CORES" >/dev/null 2>&1 \
  || c_die "ビルドに失敗しました（$SRC/build を見てください）"

# 版によって実行ファイルの名前が違う
BIN=""
for cand in "$SRC/build/bin/whisper-cli" "$SRC/build/bin/main"; do
  [ -x "$cand" ] && BIN="$cand" && break
done
[ -n "$BIN" ] || c_die "実行ファイルが見つかりません"
c_ok "$(basename "$BIN") を ${CORES} 並列でビルド"

c_head "④ 置く"
install -d -m 755 "$ROOT/bin" "$ROOT/models"
install -m 755 "$BIN" "$ROOT/bin/whisper-cli"
c_ok "$ROOT/bin/whisper-cli"

c_head "⑤ モデルを取る（${MODEL}）"
MODEL_FILE="$ROOT/models/ggml-${MODEL}.bin"
if [ -s "$MODEL_FILE" ]; then
  c_ok "既にある（$(du -h "$MODEL_FILE" | cut -f1)）"
else
  bash "$SRC/models/download-ggml-model.sh" "$MODEL" "$ROOT/models" >/dev/null 2>&1 \
    || c_die "モデルを取得できませんでした"
  [ -s "$MODEL_FILE" ] || c_die "モデルが見当たりません: $MODEL_FILE"
  c_ok "$(du -h "$MODEL_FILE" | cut -f1)"
fi

# 使う側が探さなくて済むように記録する
install -d -m 755 /etc/chibitaru
cat > /etc/chibitaru/whisper <<EOF
# install/whisper.sh が生成
CHIBITARU_WHISPER_BIN=${ROOT}/bin/whisper-cli
CHIBITARU_WHISPER_MODEL=${MODEL_FILE}
EOF
c_ok "/etc/chibitaru/whisper に記録"

c_head "できあがり"
"$ROOT/bin/whisper-cli" --help 2>&1 | head -2 | sed 's/^/    /'
echo
echo "    試すには:  chibitaru-listen"
echo
