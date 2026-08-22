#!/usr/bin/env bash
# 搭載メモリからプロファイルを決める。
#
# この OS は容量ごとに別物を配らない。起動時にここで一つ選び、
# 以降のすべて（会話AIのモデル、zram のサイズ、コンテナを同時に
# 許すか）がこの結果を参照する。判定はここだけにある。
#
#   ./detect-profile.sh              4g か 8g を出す
#   ./detect-profile.sh --explain    判断の根拠も出す
#   CHIBITARU_FORCE_MB=4096 ...      検証用に搭載量を偽装する
#
set -euo pipefail

# ── しきい値（MB）─────────────────────────────────────────
# Linux が見る MemTotal は、箱に書いてある搭載量より必ず少ない。
# ファームウェア予約と、内蔵GPUが持っていく分が引かれるため:
#   4GB 搭載 → 3600〜3900MB
#   8GB 搭載 → 7000〜7800MB（GPU に 1GB 取られると 7.0GB まで落ちる）
# 8GB 機を 4g と誤判定しないよう、下限は余裕を見て 6144 に置く。
THRESHOLD_8G=6144
THRESHOLD_4G=2800   # これ未満は 2GB/1GB 向けの別プロジェクト

EXPLAIN=false
[ "${1:-}" = "--explain" ] && EXPLAIN=true

# ── 搭載量を読む ──────────────────────────────────────────
CGROUP_MAX=/sys/fs/cgroup/memory.max

if [ -n "${CHIBITARU_FORCE_MB:-}" ]; then
  MEM_MB="$CHIBITARU_FORCE_MB"
  SOURCE="CHIBITARU_FORCE_MB による偽装"

elif [ -r "$CGROUP_MAX" ] && [ "$(cat "$CGROUP_MAX")" != "max" ]; then
  # 開発用の箱の中。実機では上限が "max" なのでこの枝には入らない。
  # /proc/meminfo は名前空間化されないため、ここを見ないと 4GB の箱でも
  # 母艦の 32GB を読んで 8g と誤判定する。
  MEM_MB=$(( $(cat "$CGROUP_MAX") / 1048576 ))
  SOURCE="cgroup の上限（箱の中）"

else
  MEM_MB=$(( $(awk '/^MemTotal:/ {print $2}' /proc/meminfo) / 1024 ))
  SOURCE="/proc/meminfo"
fi

# ── 判定 ──────────────────────────────────────────────────
if   [ "$MEM_MB" -ge "$THRESHOLD_8G" ]; then PROFILE=8g
elif [ "$MEM_MB" -ge "$THRESHOLD_4G" ]; then PROFILE=4g
else
  cat >&2 <<EOF

  この機体は ${MEM_MB}MB。Chibitaru OS の対象は 4GB 以上です。

  2GB / 1GB 機は制約の質が違うため別プロジェクトになっています。
  Firefox だけで 800MB 使うので、そのままでは成立しません。
  母艦に TLS 終端プロキシを置いて軽いブラウザを使う構成が要ります。

EOF
  exit 2
fi

if $EXPLAIN; then
  cat <<EOF
  搭載量   ${MEM_MB} MB  (${SOURCE})
  判定     ${PROFILE}
  しきい値 8g >= ${THRESHOLD_8G} / 4g >= ${THRESHOLD_4G}

  この判定で決まるもの:
EOF
  if [ "$PROFILE" = "8g" ]; then
    cat <<'EOF'
    会話AI     Qwen2.5-1.5B (約1150MB・呼ぶ時だけ起動)
    zram       4096MB
    コンテナ   ブラウザと同時に使える
EOF
  else
    cat <<'EOF'
    会話AI     Qwen2.5-0.5B (約420MB・呼ぶ時だけ起動)
    zram       3072MB
    コンテナ   ブラウザと同時に使える（空き44%まで落ちる）
EOF
  fi
  echo
fi

echo "$PROFILE"
