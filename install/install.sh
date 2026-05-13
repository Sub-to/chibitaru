#!/bin/bash
# 📦 チビタル インストーラー
# 新しいMacに鬼丸・蔵丸・青っ子をセットアップ

USB_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo ""
echo "📦 チビタル インストーラー"
echo "何をインストールしますか？"
echo "  1: 🔵 青っ子（セキュリティ監視）"
echo "  2: 👁️  蔵丸（Vault品質管理）"
echo "  3: 👹 鬼丸（ファイル改ざん検知）"
echo "  4: 全部まとめて"
echo ""
read -p "選択 > " CHOICE

INSTALL_DIR="$HOME/ランドセル"
mkdir -p "$INSTALL_DIR"

install_aoko() {
    echo "🔵 青っ子をインストール中..."
    cp -r "$USB_DIR/aoko" "$INSTALL_DIR/"
    echo "  ✅ $INSTALL_DIR/aoko/"
    echo "  起動: bash $INSTALL_DIR/aoko/launch.sh"
}

install_kuramaru() {
    echo "👁️  蔵丸をインストール中..."
    if [ -f "$USB_DIR/install/kuramaru.py" ]; then
        cp "$USB_DIR/install/kuramaru.py" "$INSTALL_DIR/"
    else
        echo "  ⚠️  蔵丸はUSBに含まれていません（Macから直接コピーしてください）"
    fi
}

install_onimaru() {
    echo "👹 鬼丸をインストール中..."
    if [ -d "$USB_DIR/install/onimaru" ]; then
        cp -r "$USB_DIR/install/onimaru" "$INSTALL_DIR/"
    else
        echo "  ⚠️  鬼丸はUSBに含まれていません"
    fi
}

case $CHOICE in
  1) install_aoko ;;
  2) install_kuramaru ;;
  3) install_onimaru ;;
  4) install_aoko; install_kuramaru; install_onimaru ;;
esac

echo ""
echo "✅ インストール完了！"
