#!/bin/bash
# ╔══════════════════════════════════════════╗
# ║  🖥 ちびたるダッシュボード（常時表示）    ║
# ╚══════════════════════════════════════════╝
# Surface Pro 3 + Ubuntu のような「情報表示専用機」向け。
# サーバーを立ち上げ、ブラウザを枠なし全画面で開く。
# 終了すると（Alt+F4 など）サーバーも一緒に止まる。
#
#   bash dashboard/kiosk.sh            全画面で起動
#   bash dashboard/kiosk.sh --window   枠付きウィンドウで起動

DASH_DIR="$(cd "$(dirname "$0")" && pwd)"
PORT="${CHIBITARU_DASH_PORT:-8787}"
URL="http://127.0.0.1:${PORT}/"

MODE="kiosk"
[ "$1" = "--window" ] && MODE="window"

PY=""
for c in python3 python; do
    command -v "$c" >/dev/null 2>&1 && PY="$c" && break
done
[ -z "$PY" ] && { echo "❌ Python が見つかりません"; exit 1; }

# ── サーバーを裏で起動 ─────────────────────
echo "🖥 サーバーを起動しています..."
CHIBITARU_DASH_NO_BROWSER=1 "$PY" "$DASH_DIR/server.py" --port "$PORT" --no-browser &
SERVER_PID=$!

# 終了時に必ずサーバーも止める
cleanup() {
    echo ""
    echo "👋 終了します"
    kill "$SERVER_PID" 2>/dev/null
    wait "$SERVER_PID" 2>/dev/null
}
trap cleanup EXIT INT TERM

# ── 立ち上がるのを待つ ─────────────────────
for i in $(seq 1 30); do
    if command -v curl >/dev/null 2>&1; then
        curl -s --noproxy '*' --max-time 2 "${URL}api/health" >/dev/null 2>&1 && break
    else
        "$PY" - "$URL" <<'PYCHK' >/dev/null 2>&1 && break
import sys, urllib.request
urllib.request.urlopen(sys.argv[1] + "api/health", timeout=2)
PYCHK
    fi
    sleep 0.5
done

# ── ブラウザを探して開く ───────────────────
# Chromium系はアプリモードが綺麗。無ければ Firefox、最後は既定のブラウザ。
BROWSER=""
for b in chromium chromium-browser google-chrome google-chrome-stable microsoft-edge brave-browser; do
    command -v "$b" >/dev/null 2>&1 && BROWSER="$b" && break
done

echo "🌐 $URL を開きます"

if [ -n "$BROWSER" ]; then
    ARGS=()
    if [ "$MODE" = "kiosk" ]; then
        ARGS+=(--kiosk)
    else
        ARGS+=("--app=$URL" --window-size=1440,960)
    fi
    # Wayland（Ubuntu 22.04以降の既定）で綺麗に出す
    [ -n "$WAYLAND_DISPLAY" ] && ARGS+=(--ozone-platform-hint=auto)
    # 情報表示専用なので、余計な機能は切っておく
    ARGS+=(--noerrdialogs --disable-infobars --disable-session-crashed-bubble
           --disable-features=TranslateUI --check-for-update-interval=31536000)
    "$BROWSER" "${ARGS[@]}" "$URL" 2>/dev/null
elif command -v firefox >/dev/null 2>&1; then
    if [ "$MODE" = "kiosk" ]; then
        firefox --kiosk "$URL"
    else
        firefox "$URL"
    fi
else
    echo "⚠️  ブラウザを自動で見つけられませんでした。手動で開いてください: $URL"
    xdg-open "$URL" 2>/dev/null
    echo "（Ctrl+C で終了）"
    wait "$SERVER_PID"
fi
