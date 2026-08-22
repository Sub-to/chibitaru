#!/usr/bin/env bash
# Firefox が本当に予算に収まるか測る。
#
# 設計書は 8GB で 900MB / 4GB・2GB で 550MB を前提にしている。
# 母艦の無調整 Firefox は 1359MB（14プロセス）だったので、この前提は
# 放っておいて成り立つものではない。profiles/firefox/*.js が実際に
# どれだけ効くのかを、同じ条件で並べて測る。
#
#   ./tools/firefox-bench.sh              全ティアを順に測る
#   ./tools/firefox-bench.sh 4g           4g だけ測る
#
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="chibitaru-bench"

# 実際に開くページ。ログイン不要で、内容が安定していて、
# 軽いものと重いものを混ぜてある。3 枚は設計書の想定タブ数。
URLS=(
  "https://ja.wikipedia.org/wiki/Linux"
  "https://www.debian.org/"
  "https://news.ycombinator.com/"
)

SETTLE=35     # 読み込みと GC が落ち着くまでの待ち時間（秒）
REPEATS=3     # 同条件でも 40MB 程度ぶれるので繰り返して中央値を取る

# ───────────────────────────────────────────────────────────
# 箱の外：指定されたティアぶんコンテナを回す
# ───────────────────────────────────────────────────────────
if [ "${1:-}" != "--inner" ]; then
  read -ra TIERS <<< "${*:-4g 8g}"

  if ! podman image exists "$IMAGE"; then
    echo "  計測用イメージがない。先に作る:" >&2
    echo "    podman build -t $IMAGE -f tools/Containerfile.bench ." >&2
    exit 1
  fi

  OUT="$(mktemp)"
  trap 'rm -f "$OUT"' EXIT

  TOTAL=$(( ${#TIERS[@]} * 2 * REPEATS ))
  echo
  echo "  Firefox メモリ実測 — ${#URLS[@]}ページ / ${SETTLE}秒待機 / 各条件${REPEATS}回"
  echo "  全 ${TOTAL} 回、おおよそ $(( TOTAL * (SETTLE + 12) / 60 )) 分"
  echo

  N=0
  for tier in "${TIERS[@]}"; do
    # 調整なしとの比較のため、各ティアで 2 条件まわす
    for mode in none "$tier"; do
     for _rep in $(seq "$REPEATS"); do
      N=$(( N + 1 ))
      printf "\r  %d/%d  %s %s ... " "$N" "$TOTAL" "$tier" "$mode"
      podman run --rm -i \
        --memory="$tier" --memory-swap="$tier" \
        --cpus=2 \
        --cap-add=SYS_PTRACE \
        --shm-size=256m \
        -v "$REPO:/chibitaru:z" \
        -e "BENCH_TIER=$tier" -e "BENCH_MODE=$mode" -e "BENCH_SETTLE=$SETTLE" \
        "$IMAGE" bash /chibitaru/tools/firefox-bench.sh --inner \
        2>/dev/null | grep '^RESULT ' >> "$OUT" || true
     done
    done
  done

  printf "\r%*s\r" 40 ""
  python3 "$REPO/tools/_bench_report.py" "$OUT"
  exit 0
fi

# ───────────────────────────────────────────────────────────
# 箱の中：Firefox を起動して測る
# ───────────────────────────────────────────────────────────
TIER="$BENCH_TIER"
MODE="$BENCH_MODE"
PROFILE=/tmp/ffprofile

# Firefox は root で動かすと挙動が変わる。実機と揃えて一般ユーザーで回す。
id bench &>/dev/null || useradd -m -s /bin/bash bench

rm -rf "$PROFILE"
mkdir -p "$PROFILE"

# 初回起動の抑制とテレメトリ停止は「調整なし」側にも入れる。
# これを入れないと調整なしだけウェルカムタブが増えて比較が壊れる。
cat /chibitaru/profiles/firefox/_base.js > "$PROFILE/user.js"

if [ "$MODE" != "none" ]; then
  cat "/chibitaru/profiles/firefox/${MODE}.js" >> "$PROFILE/user.js"
  LABEL="調整あり"
else
  LABEL="調整なし"
fi

chown -R bench:bench "$PROFILE"

# Xvfb 上で起動。ヘッドレスではなく実描画にする。
# ヘッドレスだと描画バッファを持たないぶん実機より小さく出てしまう。
export DISPLAY=:99
Xvfb :99 -screen 0 1366x768x24 -nolisten tcp &
XVFB_PID=$!
sleep 2

# su は既定で環境を捨てるので DISPLAY をコマンド側に書く。
# export しただけでは Firefox が X に繋げず、無言で起動に失敗する。
su bench -c "DISPLAY=$DISPLAY firefox-esr --new-instance --profile $PROFILE ${URLS[*]}" \
  >/tmp/ff.log 2>&1 &

sleep "$BENCH_SETTLE"

# 計測は measure.py に任せる（PSS で数える方の実装をそのまま使う）
if ! pgrep -x firefox-esr >/dev/null; then
  echo "  $TIER  $LABEL  Firefox が起動していない。/tmp/ff.log:" >&2
  tail -5 /tmp/ff.log >&2
  kill "$XVFB_PID" 2>/dev/null || true
  exit 1
fi

python3 /chibitaru/tools/measure.py --json --tier "$TIER" \
  | python3 /chibitaru/tools/_bench_report.py --raw "$TIER" "$MODE" || true

kill "$XVFB_PID" 2>/dev/null || true
pkill -9 firefox-esr 2>/dev/null || true
exit 0
