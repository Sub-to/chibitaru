#!/bin/bash
# 🦠 チビタル ウイルスチェック（USB DBバージョン）

set -u

USB_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DB_DIR="$USB_DIR/scan/clamdb"
TARGET="${1:-$HOME}"
OS="$(uname -s 2>/dev/null || echo Windows)"

echo ""
echo "🦠 ウイルスチェック開始"
echo "対象: $TARGET"
echo "DB:   $DB_DIR （オフライン対応）"
echo ""

# ── ClamAV を探す ────────────────────────────────────────────
CLAM=""
for CAND in clamscan /usr/bin/clamscan /usr/local/bin/clamscan /opt/homebrew/bin/clamscan; do
    command -v "$CAND" >/dev/null 2>&1 && CLAM="$CAND" && break
done

if [ -z "$CLAM" ]; then
    echo "⚠️  ClamAV が見つかりません"
    case "$OS" in
      Darwin) echo "   インストール: brew install clamav" ;;
      Linux)
        echo "   Debian/Ubuntu : sudo apt install clamav"
        echo "   Arch/CachyOS  : sudo pacman -S clamav"
        echo "   Fedora        : sudo dnf install clamav"
        echo "   Alpine        : sudo apk add clamav"
        ;;
      *) echo "   https://www.clamav.net/downloads からインストールしてください" ;;
    esac
    exit 1
fi

# ── オフラインDBの確認 ───────────────────────────────────────
if ! ls "$DB_DIR"/*.cvd "$DB_DIR"/*.cld >/dev/null 2>&1; then
    echo "⚠️  ウイルス定義が $DB_DIR にありません"
    echo "   取得: freshclam --datadir=\"$DB_DIR\""
    exit 1
fi

# ── OS別の除外ディレクトリ ───────────────────────────────────
EXCLUDES=(--exclude-dir="^/proc" --exclude-dir="^/sys" --exclude-dir="\.git" --exclude-dir="node_modules")
if [ "$OS" = "Darwin" ]; then
    EXCLUDES+=(--exclude-dir="$HOME/Library/Caches")
else
    EXCLUDES+=(--exclude-dir="$HOME/\.cache")
fi

LOG="${TMPDIR:-/tmp}/clamav_result.txt"

echo "スキャン中... （時間がかかります）"
"$CLAM" -r "$TARGET" \
    --database="$DB_DIR" \
    "${EXCLUDES[@]}" \
    --infected \
    --bell \
    --log="$LOG" \
    2>/dev/null

echo ""
echo "✅ スキャン完了"
echo "📋 ログ: $LOG"
grep -E "FOUND|Infected" "$LOG" 2>/dev/null || echo "感染ファイル: なし ✅"
