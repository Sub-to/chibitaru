#!/usr/bin/env bash
# 開発用の箱 — Debian 13 を指定容量のメモリ制限つきで立てる。
#
# 8GB や 2GB の実機を用意しなくても、ここで設計どおりに収まるかを検証できる。
# --memory-swap を --memory と同値にしてスワップを殺してあるので、
# 「本当に物理メモリに収まるか」の厳しいほうのテストになる。
#
#   ./tools/box.sh 2g          2GB の箱に入る
#   ./tools/box.sh 4g          4GB の箱に入る
#   ./tools/box.sh 8g setup    8GB の箱で setup.sh を流す
#
set -euo pipefail

TIER="${1:-4g}"
ACTION="${2:-shell}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="debian:13-slim"

case "$TIER" in
  4g) MEM=4g ;;
  8g) MEM=8g ;;
  2g|1g)
    echo "  2GB / 1GB は別プロジェクト（実機で検証する）。" >&2
    exit 1 ;;
  *)  echo "使えるのは 4g / 8g のどちらか（指定: $TIER）" >&2; exit 1 ;;
esac

echo
echo "  ┌────────────────────────────────────────┐"
printf "  │  Debian 13 / メモリ上限 %-3s / swap なし  │\n" "$MEM"
echo "  └────────────────────────────────────────┘"
echo

# CPU も絞っておく。対象機は 2〜4 コアで、開発機の 16 コアで
# 測ると起動時間や whisper の所要が現実離れするため。
case "$TIER" in
  4g) CPUS=2 ;;
  8g) CPUS=4 ;;
esac

# 端末から実行された時だけ -t を付ける。CI やスクリプト経由でも動くように。
TTY_FLAGS=(-i)
[ -t 0 ] && TTY_FLAGS=(-i -t)

RUN=(
  podman run --rm "${TTY_FLAGS[@]}"
  --memory="$MEM"
  --memory-swap="$MEM"
  # smaps_rollup を読むのに要る。rootless podman は既定で落とす。
  --cap-add=SYS_PTRACE
  --cpus="$CPUS"
  --hostname="chibitaru-$TIER"
  -e "CHIBITARU_TIER=$TIER"
  -e "DEBIAN_FRONTEND=noninteractive"
  -v "$REPO:/chibitaru:z"
  -w /chibitaru
  "$IMAGE"
)

case "$ACTION" in
  shell)
    exec "${RUN[@]}" bash -c '
      apt-get update -qq && apt-get install -y -qq python3 procps >/dev/null
      echo "  python3 と procps を入れた。計測は:"
      echo "    ./tools/measure.py --tier $CHIBITARU_TIER"
      echo
      exec bash
    '
    ;;
  setup)
    exec "${RUN[@]}" bash /chibitaru/install/setup.sh
    ;;
  measure)
    exec "${RUN[@]}" bash -c '
      apt-get update -qq && apt-get install -y -qq python3 procps >/dev/null
      ./tools/measure.py --tier "$CHIBITARU_TIER"
    '
    ;;
  *)
    echo "使えるのは shell / setup / measure（指定: $ACTION）" >&2
    exit 1
    ;;
esac
