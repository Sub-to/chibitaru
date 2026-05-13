#!/usr/bin/env bash
# 🐣 タルっ子AI ─ Step 4: 起動！

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="/opt/homebrew/bin/python3"

echo ""
echo "🐣 タルっ子AI 起動中..."
echo ""

exec "$PYTHON" "$SCRIPT_DIR/../chat.py" --tarukko
