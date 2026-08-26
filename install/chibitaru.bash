# chibitaru - bash function for Linux
# ~/.bashrc から読み込まれる。インストール: bash setup.sh
#
# 探索順:
#   1. $CHIBITARU_HOME（setup.sh が書き込む）
#   2. USB の一般的なマウントポイント

function chibitaru() {
    local SRC=""

    if [ -n "${CHIBITARU_HOME:-}" ] && [ -f "$CHIBITARU_HOME/start.sh" ]; then
        SRC="$CHIBITARU_HOME"
    else
        local BASE NAME
        for BASE in "/media/$USER" "/run/media/$USER" "/media" "/mnt"; do
            [ -d "$BASE" ] || continue
            for NAME in "$BASE"/*/チビタル "$BASE"/*/chibitaru "$BASE"/チビタル "$BASE"/chibitaru; do
                [ -f "$NAME/start.sh" ] && SRC="$NAME" && break 2
            done
        done
    fi

    if [ -z "$SRC" ]; then
        echo "chibitaru が見つかりません（USBは挿さっていますか？）"
        echo "  手動指定: export CHIBITARU_HOME=/path/to/chibitaru"
        return 1
    fi

    # USB を挿しっぱなしにしないよう、tmp にコピーしてから実行する
    local RUN="${TMPDIR:-/tmp}/chibitaru_run"
    rm -rf "$RUN" || return 1
    cp -r "$SRC" "$RUN" || return 1
    bash "$RUN/start.sh"
}
