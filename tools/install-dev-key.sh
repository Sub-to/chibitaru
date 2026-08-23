#!/usr/bin/env bash
# 母艦の公開鍵を実機に入れる。
#
# コンソールで長いパスや base64 を手打ちすると、空白の混入や打ち間違いで
# 何度も失敗する（実際に 3 回失敗した）。ここに固めて 1 コマンドにする。
#
#   bash tools/install-dev-key.sh
#
# 開発が終わったら tools/README-dev-key.md の手順で消すこと。
set -eu

KEY_FILE="$(cd "$(dirname "$0")" && pwd)/dev-key.pub"

if [ "$(id -u)" != 0 ]; then
  echo "Run as root:  su -   then try again" >&2
  exit 1
fi

[ -f "$KEY_FILE" ] || { echo "Key not found: $KEY_FILE" >&2; exit 1; }

cd /root
mkdir -p .ssh
chmod 700 .ssh

# 既に入っていれば足さない（何度流しても同じ結果になるように）
if [ -f .ssh/authorized_keys ] && grep -qF "$(cat "$KEY_FILE")" .ssh/authorized_keys; then
  echo "Key already installed."
else
  cat "$KEY_FILE" >> .ssh/authorized_keys
  echo "Key added."
fi

chmod 600 .ssh/authorized_keys

echo "---"
echo "bytes: $(wc -c < .ssh/authorized_keys)   (100 = one key, correct)"
echo "sshd : $(systemctl is-active ssh 2>/dev/null || echo unknown)"
echo "ip   : $(ip -4 -br addr show scope global | awk '{print $1, $3}' | tr '\n' ' ')"
echo "---"
echo "Done. Tell the assistant the IP above."
