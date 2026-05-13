#!/bin/bash
# 🔵 青っ子 USB版 起動スクリプト（macOS / Linux / Windows Git Bash 対応）
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MODEL="$SCRIPT_DIR/model/Qwen2.5-1.5B-Instruct-Q4_K_M.gguf"

# ── OS検出 ──────────────────────────────────────────
OS="$(uname -s 2>/dev/null || echo Windows)"
case "$OS" in
  Darwin)  BIN_SUBDIR="mac"      ;;
  Linux)   BIN_SUBDIR="linux-x64" ;;
  *)       BIN_SUBDIR="win-x64"   ;;
esac

# ── llama-server 探索順：USB優先 ─────────────────────
if [ "$BIN_SUBDIR" = "win-x64" ]; then
    SERVER_EXE="llama-server.exe"
else
    SERVER_EXE="llama-server"
fi

if [ -f "$SCRIPT_DIR/../bin/$BIN_SUBDIR/$SERVER_EXE" ]; then
    LLAMA="$SCRIPT_DIR/../bin/$BIN_SUBDIR/$SERVER_EXE"
    # Linux: .so が隣にあるのでLD_LIBRARY_PATHを通す
    if [ "$BIN_SUBDIR" = "linux-x64" ]; then
        export LD_LIBRARY_PATH="$SCRIPT_DIR/../bin/$BIN_SUBDIR:${LD_LIBRARY_PATH}"
    fi
elif [ -f "$SCRIPT_DIR/../bin/$SERVER_EXE" ]; then
    # 旧レイアウト (Mac ARM 直置き)
    LLAMA="$SCRIPT_DIR/../bin/$SERVER_EXE"
elif command -v llama-server &>/dev/null; then
    LLAMA="llama-server"
else
    echo "❌ llama-server が見つかりません"
    echo "   確認場所: $SCRIPT_DIR/../bin/$BIN_SUBDIR/$SERVER_EXE"
    exit 1
fi

echo "🔵🔵🔵 青い三連星 展開中... ($OS / $BIN_SUBDIR)"

for PORT in 11201 11202 11203; do
    "$LLAMA" --model "$MODEL" --port $PORT --ctx-size 512 --threads 2 \
        > /tmp/aoko_$(echo $PORT | tail -c 2).log 2>&1 &
done

echo "起動待機中（20秒）..."
sleep 20

OK=0
for PORT in 11201 11202 11203; do
    curl -s "http://localhost:$PORT/health" > /dev/null 2>&1 && OK=$((OK+1))
done
echo "✅ $OK/3 号機 起動完了"
[ $OK -eq 3 ] && echo "🔵 三連星 完全展開！" || echo "⚠️ 一部未起動（ログ: /tmp/aoko_?.log）"
