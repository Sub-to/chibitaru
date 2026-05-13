#!/bin/bash
# 🦠 チビタル ウイルスチェック（USB DBバージョン）

USB_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DB_DIR="$USB_DIR/scan/clamdb"
TARGET="${1:-$HOME}"

echo ""
echo "🦠 ウイルスチェック開始"
echo "対象: $TARGET"
echo "DB:   $DB_DIR （オフライン対応）"
echo ""

# ClamAV探す
for CLAM in clamscan /opt/homebrew/bin/clamscan /usr/local/bin/clamscan; do
    command -v "$CLAM" &>/dev/null && break
done

if ! command -v "$CLAM" &>/dev/null; then
    echo "⚠️  ClamAV未インストール"
    echo "インストール: brew install clamav"
    exit 1
fi

echo "スキャン中... （時間がかかります）"
"$CLAM" -r "$TARGET" \
    --database="$DB_DIR" \
    --exclude-dir="$HOME/Library/Caches" \
    --exclude-dir=".git" \
    --exclude-dir="node_modules" \
    --infected \
    --bell \
    --log=/tmp/clamav_result.txt \
    2>/dev/null

echo ""
echo "✅ スキャン完了"
echo "📋 ログ: /tmp/clamav_result.txt"
grep -E "FOUND|Infected" /tmp/clamav_result.txt 2>/dev/null || echo "感染ファイル: なし ✅"
