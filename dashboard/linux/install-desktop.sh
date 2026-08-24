#!/bin/bash
# ╔══════════════════════════════════════════╗
# ║  🖥 ダッシュボードをデスクトップに登録    ║
# ╚══════════════════════════════════════════╝
# Ubuntu / GNOME 用。
#   bash dashboard/linux/install-desktop.sh            アプリ一覧に追加
#   bash dashboard/linux/install-desktop.sh --autostart ログイン時に自動起動も
#   bash dashboard/linux/install-desktop.sh --remove    取り消し

set -e
DASH_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_DIR="$HOME/.local/share/applications"
AUTO_DIR="$HOME/.config/autostart"
NAME="chibitaru-dashboard.desktop"

if [ "$1" = "--remove" ]; then
    rm -f "$APP_DIR/$NAME" "$AUTO_DIR/$NAME"
    command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APP_DIR" || true
    echo "🗑  登録を解除しました"
    exit 0
fi

mkdir -p "$APP_DIR"
sed "s|%k_DASH_DIR%|$DASH_DIR|g" "$DASH_DIR/linux/$NAME" > "$APP_DIR/$NAME"
chmod +x "$APP_DIR/$NAME"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APP_DIR" || true
echo "✅ アプリ一覧に追加しました（「ちびたる」で検索できます）"

if [ "$1" = "--autostart" ]; then
    mkdir -p "$AUTO_DIR"
    cp "$APP_DIR/$NAME" "$AUTO_DIR/$NAME"
    echo "✅ ログイン時に自動で開くようにしました"
    echo "   やめるときは: bash dashboard/linux/install-desktop.sh --remove"
fi

echo ""
echo "ℹ️  常時表示させるなら、画面が消えない設定もどうぞ:"
echo "   gsettings set org.gnome.desktop.session idle-delay 0"
echo "   gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type 'nothing'"
