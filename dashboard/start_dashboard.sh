#!/bin/bash
# ╔══════════════════════════════════════════╗
# ║  🖥 ちびたるダッシュボード               ║
# ╚══════════════════════════════════════════╝
# 使い方:
#   bash dashboard/start_dashboard.sh          起動
#   bash dashboard/start_dashboard.sh --check  情報源チェック
#   bash dashboard/start_dashboard.sh --once   1回だけ取得してVaultに記録

DASH_DIR="$(cd "$(dirname "$0")" && pwd)"

PY=""
for c in python3 python; do
    command -v "$c" >/dev/null 2>&1 && PY="$c" && break
done
if [ -z "$PY" ]; then
    echo "❌ Python が見つかりません（python3 を入れてください）"
    exit 1
fi

# Vault の場所（未設定なら既定値を案内）
if [ -z "$CHIBITARU_VAULT" ]; then
    echo "ℹ️  CHIBITARU_VAULT が未設定です。既定: \$HOME/ObsidianVault"
    echo "   別の場所なら: export CHIBITARU_VAULT=\"/path/to/YourVault\""
fi

exec "$PY" "$DASH_DIR/server.py" "$@"
