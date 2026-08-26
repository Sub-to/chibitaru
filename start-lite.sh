#!/bin/bash
# ╔══════════════════════════════════════════════════╗
# ║  ⚡ チビタル 軽量モード（低スペックLinux向け）   ║
# ║     LLM不要 / モデル不要 / GPU不要 / 依存ゼロ    ║
# ╚══════════════════════════════════════════════════╝
#
# llama-server も 940MB の GGUF モデルも使わず、
# MYLN-FRAME だけで監視する軽量版。
# 必要なのは python3 だけ。
#
# 使い方:
#   bash start-lite.sh            # 常駐監視
#   bash start-lite.sh --once     # 1回だけスキャンして終了（cron向き）
#   bash start-lite.sh --selftest # 判定エンジンの動作確認

set -u

USB_DIR="$(cd "$(dirname "$0")" && pwd)"
AOKO_DIR="$USB_DIR/aoko"

# ── python3 の確認（これだけが必須依存）──────────────────────
PY=""
for CAND in python3 python; do
    command -v "$CAND" >/dev/null 2>&1 && PY="$CAND" && break
done
if [ -z "$PY" ]; then
    echo "❌ python3 が見つかりません"
    echo "   Debian/Ubuntu : sudo apt install python3"
    echo "   Arch/CachyOS  : sudo pacman -S python"
    echo "   Alpine        : sudo apk add python3"
    exit 1
fi

# ── エンジン指定（未指定なら auto = native→純Python）─────────
export CHIBITARU_ENGINE="${CHIBITARU_ENGINE:-auto}"
if [ "$CHIBITARU_ENGINE" = "llm" ]; then
    echo "⚠️  軽量モードでは CHIBITARU_ENGINE=llm は使えません → auto に戻します"
    export CHIBITARU_ENGINE="auto"
fi

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║  ⚡ チビタル 軽量モード                          ║"
echo "╚══════════════════════════════════════════════════╝"
echo "  Python  : $($PY -V 2>&1)"
echo "  Vault   : ${CHIBITARU_VAULT:-$HOME/ObsidianVault}"
echo "  モデル  : 不要（MYLN-FRAME）"
echo ""

case "${1:-}" in
  --selftest)
    echo "🔍 判定エンジンの動作確認..."
    echo ""
    "$PY" "$AOKO_DIR/myln_py.py" || exit 1
    echo ""
    "$PY" "$AOKO_DIR/myln_conductor.py" || exit 1
    ;;
  --once)
    "$PY" "$AOKO_DIR/monitor.py" --once
    ;;
  *)
    "$PY" "$AOKO_DIR/monitor.py"
    ;;
esac
