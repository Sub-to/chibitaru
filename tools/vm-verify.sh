#!/usr/bin/env bash
# VM の中で setup.sh を流し、systemd の下で本当に効いているかを確かめる。
#
# 箱で確かめられることはここでは測らない。ここで見るのは
# 「設定ファイルを書いた」ではなく「実際にそうなっている」かどうか。
#
#   ./tools/vm.sh test 4g
#
# ── 検証スクリプト自身が嘘をつかないように ──────────────────
# 最初の版は 6 件を失敗と報告したが、そのうち 5 件はこのスクリプトの
# バグだった。原因は二つとも「取れなかった」を「値が違う」として
# 扱っていたこと:
#   ・sysctl と swapon は /usr/sbin にあり、SSH の非ログインシェルの
#     PATH に入っていない。`|| true` がエラーを飲み込んで空文字になった。
#   ・journalctl は sudo なしだと他ユニットのログを読めず、空になった。
# どちらも「設定が効いていない」ようにしか見えず、実際には効いていた。
# 以降、コマンドの失敗と値の不一致は必ず区別して出す。
#
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TIER="${1:-4g}"
VM_DIR="$REPO/.vm"
SSH_PORT=2222
source /dev/stdin <<<"$(sed -n '/^vm_ssh()/,/^}/p' "$REPO/tools/vm.sh")"

PASS=0; FAIL=0
ok()    { printf "    \033[32m✓\033[0m %s\n" "$*"; PASS=$((PASS+1)); }
ng()    { printf "    \033[31m✗\033[0m %s\n" "$*"; FAIL=$((FAIL+1)); }
bug()   { printf "    \033[35m?\033[0m %s\n" "$*"; FAIL=$((FAIL+1)); }
head_() { printf "\n\033[1m  %s\033[0m\n" "$*"; }

# 値を取る。コマンド自体が失敗した場合は、値の不一致と区別できるように印をつける。
get() {
  local out rc
  out=$(vm_ssh "$1" 2>&1) && rc=0 || rc=$?
  if [ "$rc" -ne 0 ] || printf '%s' "$out" | grep -q "command not found"; then
    printf '__ERR__%s' "$(printf '%s' "$out" | head -1)"
  else
    printf '%s' "$out"
  fi
}

expect() {
  local label="$1" want="$2" got="$3"
  case "$got" in
    __ERR__*) bug "$label — 値を取れなかった: ${got#__ERR__}" ;;
    "$want")  ok  "$label = $got" ;;
    *)        ng  "$label = ${got:-（空）}（期待: $want）" ;;
  esac
}

# ═══════════════════════════════════════════════════════════
head_ "VM を立てる（${TIER}）"
bash "$REPO/tools/vm.sh" up "$TIER"

head_ "リポジトリを送って setup.sh を流す"
vm_ssh "rm -rf /tmp/c && mkdir -p /tmp/c"
tar -C "$REPO" --exclude=.vm --exclude=.git -cf - . \
  | vm_ssh "tar -C /tmp/c -xf - && sudo rm -rf /opt/chibitaru && sudo mv /tmp/c /opt/chibitaru"
vm_ssh "sudo CHIBITARU_USER=chibi bash /opt/chibitaru/install/setup.sh" 2>&1 | tail -8

head_ "再起動（zram と sysctl は起動時に効く）"
vm_ssh "sudo systemctl reboot" >/dev/null 2>&1 || true
sleep 8
for _ in $(seq 60); do vm_ssh true 2>/dev/null && break; sleep 2; done
ok "戻ってきた"

# ═══════════════════════════════════════════════════════════
head_ "zram — 設定ではなく実際にスワップとして有効か"
# swapon は /usr/sbin。PATH に頼らず絶対パスで呼ぶ。
SWAP=$(get '/usr/sbin/swapon --show=NAME,SIZE,PRIO --noheadings')
case "$SWAP" in
  __ERR__*) bug "swapon を実行できなかった: ${SWAP#__ERR__}" ;;
  *zram*)   ok "スワップが zram: $SWAP" ;;
  *)        ng "zram がスワップになっていない（${SWAP:-なし}）" ;;
esac

ALGO=$(get 'cat /sys/block/zram0/comp_algorithm')
case "$ALGO" in
  __ERR__*)  bug "圧縮方式を読めなかった" ;;
  *"[zstd]"*) ok "圧縮は zstd" ;;
  *)         ng "圧縮方式が zstd でない: $ALGO" ;;
esac

expect "zram の大きさ(MB)" "$([ "$TIER" = 8g ] && echo 4096 || echo 3072)" \
       "$(get 'echo $(( $(cat /sys/block/zram0/disksize) / 1048576 ))')"

head_ "sysctl — 再起動後も効いているか"
# /proc から直接読む。sysctl コマンドは /usr/sbin にあって PATH にない。
expect "vm.swappiness"   "150" "$(get 'cat /proc/sys/vm/swappiness')"
expect "vm.page-cluster" "0"   "$(get 'cat /proc/sys/vm/page-cluster')"

head_ "earlyoom — 動いているか、狙いどおり選ぶか"
if vm_ssh "systemctl is-active --quiet earlyoom" 2>/dev/null; then
  ok "earlyoom 稼働中"
  # sudo なしでは他ユニットの journal を読めず、無言で空が返る。
  LOG=$(get 'sudo journalctl -u earlyoom -b --no-pager -o cat | head -20')
  case "$LOG" in
    __ERR__*) bug "journal を読めなかった: ${LOG#__ERR__}" ;;
    *)
      # 設定を読んだだけでなく、狙った名前が実際に規則に入っているかを見る
      printf '%s' "$LOG" | grep -q "Preferring.*firefox-esr" \
        && ok "Firefox を先に捨てる規則が有効" || ng "prefer 規則が反映されていない"
      printf '%s' "$LOG" | grep -q "avoid.*labwc" \
        && ok "labwc を守る規則が有効" || ng "avoid 規則が反映されていない"
      ;;
  esac
else
  ng "earlyoom が動いていない"
  vm_ssh "systemctl status earlyoom --no-pager -l | tail -8" 2>&1 || true
fi

head_ "その他"
vm_ssh "systemctl is-active --quiet ssh" 2>/dev/null && ok "sshd 稼働中" || ng "sshd"
vm_ssh "test -d ~/Vault/日記" 2>/dev/null && ok "Vault ができている" || ng "Vault"

PV=$(get 'podman --version')
case "$PV" in
  __ERR__*) bug "podman がない" ;;
  *) ok "$PV"
     RUN=$(get 'podman run --rm docker.io/library/busybox:latest echo rootless-ok')
     case "$RUN" in
       *rootless-ok*) ok "rootless でコンテナが動く" ;;
       *) ng "rootless でコンテナが動かない: $(printf '%s' "$RUN" | tail -1)" ;;
     esac ;;
esac

head_ "待機時のメモリ（実測）"
# root で走らせないと他ユーザーのプロセスの smaps_rollup が読めず、過少になる
vm_ssh "sudo python3 /opt/chibitaru/tools/measure.py --tier $TIER" 2>/dev/null \
  | sed 's/^/  /' || echo "    （measure.py を実行できず）"

# ═══════════════════════════════════════════════════════════
printf "\n\033[1m  結果: %d 通過 / %d 失敗\033[0m\n" "$PASS" "$FAIL"
printf "  （\033[35m?\033[0m は検証側が値を取れなかった印。設定の問題とは限らない）\n\n"
[ "$FAIL" -eq 0 ]
