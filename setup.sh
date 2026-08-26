#!/bin/bash
# Chibitaru one-shot bash setup
# 実行: bash setup.sh
#
# ~/.bashrc に chibitaru コマンドを登録する。
# 何度実行しても重複登録されない。

set -u

USB_DIR="$(cd "$(dirname "$0")" && pwd)"
BASHRC="$HOME/.bashrc"
MARK_BEGIN="# >>> chibitaru >>>"
MARK_END="# <<< chibitaru <<<"

[ -f "$BASHRC" ] || touch "$BASHRC"

# ── 既存ブロックを削除（再実行時の重複防止）──────────────────
if grep -qF "$MARK_BEGIN" "$BASHRC"; then
    echo "[*] 既存の設定を更新します"
    TMP="$(mktemp)"
    sed "/$MARK_BEGIN/,/$MARK_END/d" "$BASHRC" > "$TMP" && mv "$TMP" "$BASHRC"
fi

# ── 追記 ────────────────────────────────────────────────────
{
    echo "$MARK_BEGIN"
    echo "export CHIBITARU_HOME=\"$USB_DIR\""
    echo "[ -f \"\$CHIBITARU_HOME/install/chibitaru.bash\" ] && source \"\$CHIBITARU_HOME/install/chibitaru.bash\""
    echo "$MARK_END"
} >> "$BASHRC"

echo "[OK] 登録しました: $BASHRC"
echo "     反映: source ~/.bashrc"
echo "     起動: chibitaru        （通常メニュー）"
echo "           bash \"$USB_DIR/start-lite.sh\"   （軽量モード）"
