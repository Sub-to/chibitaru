#!/usr/bin/env bash
# 実機に入れる前に、systemd の下で本当に動くか確かめるための VM。
#
# 箱（podman）では systemd がないため、zram が実際に有効になるか、
# earlyoom が狙いどおりのプロセスを選ぶかを確かめられない。
# そこだけは VM が要る。
#
#   ./tools/vm.sh test 4g     VM を立てて setup.sh を流し、検証まで
#   ./tools/vm.sh up 4g       立てるだけ（SSH は localhost:2222）
#   ./tools/vm.sh ssh         入る
#   ./tools/vm.sh down        止める
#   ./tools/vm.sh clean       ディスクを捨ててやり直す
#
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VM_DIR="$REPO/.vm"
IMAGE="chibitaru-vm"
SSH_PORT=2222

BASE_URL="https://cloud.debian.org/images/cloud/trixie/latest"
BASE_IMG="debian-13-genericcloud-amd64.qcow2"

c_head() { printf "\n\033[1m  %s\033[0m\n" "$*"; }
c_ok()   { printf "    \033[32m✓\033[0m %s\n" "$*"; }
c_warn() { printf "    \033[33m!\033[0m %s\n" "$*"; }
c_die()  { printf "\n  \033[31m✗ %s\033[0m\n\n" "$*" >&2; exit 1; }

# 箱の中で qemu を動かす。--device /dev/kvm がないと 20 倍以上遅くなる。
in_box() {
  local tty=(-i); [ -t 0 ] && tty=(-i -t)
  podman run --rm "${tty[@]}" \
    --device /dev/kvm \
    -v "$VM_DIR:/vm:z" -v "$REPO:/chibitaru:z" \
    -p "127.0.0.1:${SSH_PORT}:${SSH_PORT}" \
    -w /vm "$IMAGE" "$@"
}

# ═══════════════════════════════════════════════════════════
cmd_prepare() {
  c_head "下ごしらえ"
  mkdir -p "$VM_DIR"

  if ! podman image exists "$IMAGE"; then
    podman build -q -t "$IMAGE" -f "$REPO/tools/Containerfile.vm" "$REPO" >/dev/null
  fi
  c_ok "qemu の箱"

  if [ ! -f "$VM_DIR/$BASE_IMG" ]; then
    echo "    Debian 13 のクラウドイメージを取得中（約350MB）..."
    echo "      $BASE_URL/$BASE_IMG"
    in_box curl -fsSL -o "/vm/$BASE_IMG.part" "$BASE_URL/$BASE_IMG"
    mv "$VM_DIR/$BASE_IMG.part" "$VM_DIR/$BASE_IMG"
  fi
  c_ok "$BASE_IMG ($(du -h "$VM_DIR/$BASE_IMG" | cut -f1))"

  # VM に入るための鍵。この VM 専用で、他では使わない。
  if [ ! -f "$VM_DIR/id_vm" ]; then
    ssh-keygen -q -t ed25519 -N "" -C "chibitaru-vm" -f "$VM_DIR/id_vm"
  fi
  c_ok "VM 専用の鍵"
}

# ═══════════════════════════════════════════════════════════
cmd_up() {
  local tier="${1:-4g}"
  case "$tier" in 4g) MEM=4096; CPUS=2 ;; 8g) MEM=8192; CPUS=4 ;;
    *) c_die "4g か 8g（指定: $tier）" ;; esac

  cmd_prepare

  # 既に動いていると 2222 を掴んだままで 2 台目が上がらない。
  # 上げ直しは日常的にやるので、黙って引き取る。
  if podman container exists chibitaru-vm 2>/dev/null; then
    podman rm -f chibitaru-vm >/dev/null 2>&1 || true
    c_ok "動いていた VM を止めた"
  fi

  c_head "VM を用意（${tier} = ${MEM}MB / ${CPUS}コア）"

  # 元イメージは触らず、差分ディスクを重ねる。やり直しが一瞬で済む。
  if [ ! -f "$VM_DIR/disk.qcow2" ]; then
    in_box qemu-img create -q -f qcow2 -F qcow2 \
      -b "/vm/$BASE_IMG" /vm/disk.qcow2 16G
    c_ok "差分ディスク 16G"
  else
    c_ok "既存のディスクを使う（作り直すなら ./tools/vm.sh clean）"
  fi

  # cloud-init に渡す初期設定
  cat > "$VM_DIR/user-data" <<EOF
#cloud-config
hostname: chibitaru-${tier}
users:
  - name: chibi
    sudo: "ALL=(ALL) NOPASSWD:ALL"
    shell: /bin/bash
    ssh_authorized_keys:
      - $(cat "$VM_DIR/id_vm.pub")
ssh_pwauth: false
EOF
  printf 'instance-id: chibitaru\nlocal-hostname: chibitaru-%s\n' "$tier" \
    > "$VM_DIR/meta-data"
  in_box cloud-localds /vm/seed.iso /vm/user-data /vm/meta-data
  c_ok "cloud-init の種"

  c_head "起動"
  # 画面は出さず SSH だけで操作する。-nographic だと serial が stdout に
  # 向いてしまい console.log に残らないので -display none を使う。
  podman run -d --rm --name chibitaru-vm \
    --device /dev/kvm \
    -v "$VM_DIR:/vm:z" -v "$REPO:/chibitaru:z" \
    -p "127.0.0.1:${SSH_PORT}:2222" \
    -w /vm "$IMAGE" \
    qemu-system-x86_64 -enable-kvm \
      -m "$MEM" -smp "$CPUS" \
      -drive file=/vm/disk.qcow2,if=virtio,format=qcow2 \
      -drive file=/vm/seed.iso,if=virtio,format=raw \
      -netdev "user,id=n0,hostfwd=tcp::2222-:22" \
      -device virtio-net-pci,netdev=n0 \
      -display none -serial file:/vm/console.log >/dev/null
  c_ok "qemu 起動"

  printf "    cloud-init を待っています"
  for i in $(seq 90); do
    if vm_ssh true 2>/dev/null; then
      printf "\n"; c_ok "SSH 疎通（${i}秒）"
      return 0
    fi
    printf "."; sleep 2
  done
  printf "\n"
  c_warn "SSH が上がりません。コンソール:"
  tail -20 "$VM_DIR/console.log" 2>/dev/null || true
  return 1
}

# SSH は母艦から直接つなぐ。別コンテナから 10.0.2.2 は届かない
# （あれはゲストの中から見た qemu のゲートウェイなので）。
# qemu が転送した 2222 は podman が母艦の 127.0.0.1 に出している。
vm_ssh() {
  ssh -q -i "$VM_DIR/id_vm" \
    -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -o ConnectTimeout=4 -o LogLevel=ERROR \
    -p "$SSH_PORT" chibi@127.0.0.1 "$@"
}

vm_scp() {
  scp -q -i "$VM_DIR/id_vm" \
    -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -o LogLevel=ERROR -P "$SSH_PORT" "$@"
}

# ═══════════════════════════════════════════════════════════
cmd_down() {
  podman stop -t 2 chibitaru-vm >/dev/null 2>&1 && c_ok "VM 停止" || c_warn "動いていない"
}

cmd_clean() {
  cmd_down
  rm -f "$VM_DIR/disk.qcow2" "$VM_DIR/seed.iso" "$VM_DIR/console.log"
  c_ok "ディスクを削除（元イメージと鍵は残す）"
}

case "${1:-test}" in
  prepare) cmd_prepare ;;
  up)      cmd_up "${2:-4g}" ;;
  down)    cmd_down ;;
  clean)   cmd_clean ;;
  ssh)     shift; vm_ssh "$@" ;;
  test)    shift; bash "$REPO/tools/vm-verify.sh" "${1:-4g}" ;;
  *)       c_die "使えるのは prepare / up / ssh / down / clean / test" ;;
esac
