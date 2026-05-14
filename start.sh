#!/bin/bash
# ╔══════════════════════════════════════════╗
# ║  🔵 チビタル - USB監視エージェント       ║
# ║     青い三連星セキュリティシステム       ║
# ╚══════════════════════════════════════════╝
# 対応OS: macOS / Linux / Windows (Git Bash / WSL)

USB_DIR="$(cd "$(dirname "$0")" && pwd)"

# ── OS検出 ──────────────────────────────────────────
OS="$(uname -s 2>/dev/null || echo Windows)"
case "$OS" in
  Darwin)  OS_LABEL="macOS" ;;
  Linux)   OS_LABEL="Linux" ;;
  *)       OS_LABEL="Windows" ;;
esac

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║  🔵 チビタル 起動  ($OS_LABEL)          "
echo "╚══════════════════════════════════════════╝"
echo ""
echo "何をしますか？"
echo "  1: 🔵 セキュリティ監視開始（青い三連星）"
echo "  2: 🦠 ウイルスチェック"
echo "  3: 📦 エージェントインストール"
echo "  4: 🔍 Vault品質チェック（蔵丸呼び出し）"
echo "  0: 終了"
echo ""
read -p "選択 > " CHOICE

case $CHOICE in
  1)
    echo ""
    echo "🔵 三連星を展開しますわ..."
    bash "$USB_DIR/aoko/launch.sh"
    sleep 2
    echo ""
    echo "🔵 監視開始..."
    python3 "$USB_DIR/aoko/monitor.py"
    ;;
  2)
    echo ""
    if [ "$OS_LABEL" = "Windows" ]; then
        echo "⚠️  Windows では ClamAV のパスが異なります"
        echo "   clamscan が PATH にある場合は実行します"
    fi
    bash "$USB_DIR/scan/clamscan.sh"
    ;;
  3)
    echo ""
    bash "$USB_DIR/install/install.sh"
    ;;
  4)
    echo ""
    # Vault の蔵丸を探す
    KURAMARU_PATHS=(
        "$HOME/chibitaru-agents/kuramaru.py"
        "$HOME/kuramaru.py"
    )
    KURAMARU=""
    for P in "${KURAMARU_PATHS[@]}"; do
        [ -f "$P" ] && KURAMARU="$P" && break
    done
    if [ -n "$KURAMARU" ]; then
        python3 "$KURAMARU"
    else
        echo "⚠️  蔵丸が見つかりません（先にインストールしてください）"
        echo "   選択 3 → インストール → 蔵丸 を選ぶ"
    fi
    ;;
  0)
    echo "またね！"
    ;;
  *)
    echo "？"
    ;;
esac
