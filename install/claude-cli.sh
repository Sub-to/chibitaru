#!/usr/bin/env bash
# Claude Code を入れる。
#
#   install/claude-cli.sh          入れる（root では実行しない）
#   install/claude-cli.sh --check  入っているか見る
#
# node は要らない。公式の入れ方に「native」があり、単体で動く実行
# ファイルが置かれる。node を入れると 100MB 以上増えるうえ、この OS
# では他に使い道がない。
#
# ログインはしない。合言葉や鍵をこちらで扱わない。入れたあと
# 自分で `claude` と打って、画面の案内どおりに進めること。
set -euo pipefail

BIN="$HOME/.local/bin/claude"

if [ "$(id -u)" = 0 ]; then
  echo "root では入れないこと。使う人の権限で実行してください。" >&2
  echo "  例: su - subrigun -c 'bash /opt/chibitaru/install/claude-cli.sh'" >&2
  exit 1
fi

if [ "${1:-}" = "--check" ]; then
  if [ -x "$BIN" ]; then
    echo "あります: $("$BIN" --version 2>&1 | head -1)"
    echo "  場所: $BIN"
    command -v claude >/dev/null \
      && echo "  PATH: 通っています" \
      || echo "  PATH: 通っていません（下の注意を読んでください）"
  else
    echo "入っていません"
  fi
  exit 0
fi

if [ -x "$BIN" ]; then
  echo "既に入っています: $("$BIN" --version 2>&1 | head -1)"
else
  echo "入れます（200MB ほど落とします）"
  curl -fsSL https://claude.ai/install.sh | bash
fi

# ここが肝心。
#
# bash は ~/.bash_profile があると ~/.profile を読まない。Debian が
# PATH に ~/.local/bin を足しているのは ~/.profile のほうなので、
# 画面を起こすために ~/.bash_profile を置いたこの OS では、入れても
# 「コマンドが見つかりません」になる。実機でそうなった。入っている
# のに居ないように見えるので、原因が分かりにくい。
prof="$HOME/.bash_profile"
if [ -f "$prof" ] && ! grep -q '\.profile' "$prof"; then
  echo "  ~/.bash_profile が ~/.profile を読んでいないので直します"
  tmp=$(mktemp)
  {
    echo '# bash は ~/.bash_profile があると ~/.profile を読まない。'
    echo '# PATH に ~/.local/bin を足しているのは ~/.profile のほう。'
    echo '[ -r "$HOME/.profile" ] && . "$HOME/.profile"'
    echo
    cat "$prof"
  } > "$tmp"
  mv "$tmp" "$prof"
fi

echo
echo "  確かめる:  claude --version   （一度ログインし直してから）"
echo "  始める:    claude"
echo
echo "  ログインはこちらではしません。上の案内どおり自分で進めてください。"
