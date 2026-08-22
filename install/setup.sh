#!/usr/bin/env bash
# Chibitaru OS — Debian 13 minimal を土台に仕立てる。
#
# 何度流しても同じ結果になるように書いてある（冪等）。設定を変えて
# 流し直す使い方を想定している。
#
#   sudo bash install/setup.sh                 全部やる
#   sudo bash install/setup.sh --only zram     一段だけやり直す
#   sudo bash install/setup.sh --list          段の一覧
#
# systemd が動いていない環境（開発用の箱など）では、設定ファイルは
# 書くがサービスの有効化だけ飛ばす。箱で中身を検証できるようにするため。
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$HERE")"

STEPS=(preflight profile packages zram sysctl earlyoom firefox podman vault report)

# ── 表示 ──────────────────────────────────────────────────
c_head() { printf "\n\033[1m  %s\033[0m\n" "$*"; }
c_ok()   { printf "    \033[32m✓\033[0m %s\n" "$*"; }
c_skip() { printf "    \033[33m–\033[0m %s\n" "$*"; }
c_warn() { printf "    \033[33m!\033[0m %s\n" "$*"; }
c_die()  { printf "\n  \033[31m✗ %s\033[0m\n\n" "$*" >&2; exit 1; }

# ── systemd があるか ──────────────────────────────────────
# 箱の中には systemd がない。設定は書けるがサービス操作はできない。
HAS_SYSTEMD=false
[ -d /run/systemd/system ] && HAS_SYSTEMD=true

svc() {
  if $HAS_SYSTEMD; then
    systemctl "$@" && c_ok "systemctl $*"
  else
    c_skip "systemctl $* （systemd なし。実機で有効になる）"
  fi
}

# ═══════════════════════════════════════════════════════════
step_preflight() {
  c_head "前提を確認"

  [ "$(id -u)" = 0 ] || c_die "root で実行してください（sudo bash install/setup.sh）"

  if [ -r /etc/os-release ]; then
    . /etc/os-release
    if [ "${ID:-}" != "debian" ]; then
      c_warn "Debian 以外（${PRETTY_NAME:-不明}）。動くかもしれないが検証していない"
    else
      c_ok "${PRETTY_NAME}"
    fi
  fi

  # 対象ユーザー。sudo 経由なら呼び出した本人、直 root なら最初の一般ユーザー。
  TARGET_USER="${CHIBITARU_USER:-${SUDO_USER:-}}"
  if [ -z "$TARGET_USER" ] || [ "$TARGET_USER" = root ]; then
    TARGET_USER=$(awk -F: '$3>=1000 && $3<65534 {print $1; exit}' /etc/passwd || true)
  fi
  [ -n "$TARGET_USER" ] || c_die "対象ユーザーが決まりません。CHIBITARU_USER=名前 を指定してください"
  TARGET_HOME=$(getent passwd "$TARGET_USER" | cut -d: -f6)
  c_ok "対象ユーザー: ${TARGET_USER} (${TARGET_HOME})"

  $HAS_SYSTEMD && c_ok "systemd あり" || c_warn "systemd なし。設定は書くがサービス操作は飛ばす"
}

# ═══════════════════════════════════════════════════════════
step_profile() {
  c_head "プロファイルを判定"
  PROFILE=$(bash "$HERE/detect-profile.sh")   # 対象外なら exit 2 でここで止まる
  case "$PROFILE" in
    8g) ZRAM_MB=4096; LLM_MODEL="Qwen2.5-1.5B-Instruct-Q4_K_M" ;;
    4g) ZRAM_MB=3072; LLM_MODEL="Qwen2.5-0.5B-Instruct-Q4_K_M" ;;
  esac
  c_ok "プロファイル ${PROFILE} / zram ${ZRAM_MB}MB / 会話AI ${LLM_MODEL}"

  # 以降の段と、起動後の各機能がここを読む。判定はこの一箇所だけ。
  install -d -m 755 /etc/chibitaru
  cat > /etc/chibitaru/profile <<EOF
# install/setup.sh が生成。手で書き換えず setup.sh を流し直すこと。
CHIBITARU_PROFILE=${PROFILE}
CHIBITARU_ZRAM_MB=${ZRAM_MB}
CHIBITARU_LLM_MODEL=${LLM_MODEL}
CHIBITARU_USER=${TARGET_USER}
CHIBITARU_VAULT=${TARGET_HOME}/Vault
EOF
  c_ok "/etc/chibitaru/profile に記録"
}

# ═══════════════════════════════════════════════════════════
step_packages() {
  c_head "パッケージを導入"
  export DEBIAN_FRONTEND=noninteractive

  local pkgs=(
    # 土台
    systemd-zram-generator earlyoom
    # 画面
    labwc foot seatd
    # 音
    pipewire pipewire-pulse wireplumber
    # 見る・聴く
    firefox-esr mpv yt-dlp mpd mpc
    # コンテナと遠隔
    #
    # podman の Recommends を --no-install-recommends で切っているため、
    # rootless に要るものを自分で並べる必要がある。VM で 2 回踏んだ:
    #   uidmap なし → "command required for rootless mode with multiple IDs"
    #   passt なし  → "could not find pasta, the network namespace can't be configured"
    # どちらも podman 自体は入って --version も通るので、実際に
    # コンテナを起動するまで気づけない。
    podman podman-compose openssh-server
    uidmap              # newuidmap/newgidmap（UID 割り当て）
    passt               # pasta（podman 5 の既定の rootless ネットワーク）
    slirp4netns         # 古い環境向けのネットワーク代替
    netavark aardvark-dns  # コンテナ間ネットワークと名前解決
    catatonit           # コンテナ内の init
    containers-storage
    dbus-user-session   # ユーザーセッションのバス（pipewire も使う）
    # 道具
    python3 python3-venv python3-pip git curl rsync ripgrep micro
    # 日本語
    fonts-noto-cjk
  )

  apt-get update -qq
  apt-get install -y -qq --no-install-recommends "${pkgs[@]}"
  c_ok "${#pkgs[@]} 個を導入"
}

# ═══════════════════════════════════════════════════════════
step_zram() {
  c_head "zram（圧縮スワップ）"
  # 予算そのものを増やす仕掛け。物理RAMの一部をスワップに切り出し、
  # そこに置くページを zstd で圧縮する。ディスクには触らないので速い。
  install -D -m 644 /dev/stdin /etc/systemd/zram-generator.conf <<EOF
# install/setup.sh が生成（プロファイル ${PROFILE}）
[zram0]
zram-size = ${ZRAM_MB}
compression-algorithm = zstd
swap-priority = 100
EOF
  c_ok "zram0 を ${ZRAM_MB}MB / zstd で設定"
  svc daemon-reload
  svc start systemd-zram-setup@zram0.service
}

# ═══════════════════════════════════════════════════════════
step_sysctl() {
  c_head "カーネルの調整"
  install -D -m 644 /dev/stdin /etc/sysctl.d/99-chibitaru.conf <<'EOF'
# install/setup.sh が生成

# スワップ先が遅いディスクではなく圧縮RAMなので、キャッシュを捨てるより
# 積極的にスワップしたほうが速い。既定の 60 から上げる。
vm.swappiness = 150

# zram には先読みの意味がない。既定の 3 は一度に 8 ページ読むが、
# シーク待ちのない zram では無駄に展開するだけ。0 にして 1 ページずつ。
vm.page-cluster = 0

# 空きが減り始めた時に、早めに回収を始めて詰まりを避ける。
vm.watermark_boost_factor = 0
vm.watermark_scale_factor = 125

# 遅いディスクの機体で、書き戻しが溜まって固まるのを防ぐ。
vm.dirty_background_ratio = 5
vm.dirty_ratio = 15
EOF
  c_ok "/etc/sysctl.d/99-chibitaru.conf"
  if $HAS_SYSTEMD; then
    sysctl -q --load=/etc/sysctl.d/99-chibitaru.conf && c_ok "即時反映"
  else
    c_skip "反映は実機で"
  fi
}

# ═══════════════════════════════════════════════════════════
step_earlyoom() {
  c_head "earlyoom（枯渇前に一番太いのを落とす）"
  # 何を守り、何を先に捨てるかがこの OS の性格を決める。
  #
  # 守る: コンポジタ・端末・TUI・sshd。これらが落ちると操作不能になり、
  #       利用者から見て「フリーズした」のと区別がつかない。
  # 捨てる: ブラウザと会話AI。どちらも開き直せば戻り、Vault は
  #         ディスク上にあるので失うものがない。
  #
  # プロセス名は comm で照合され 15 文字で切られるため、長い名前は書けない。
  install -D -m 644 /dev/stdin /etc/default/earlyoom <<'EOF'
# install/setup.sh が生成
EARLYOOM_ARGS="-m 6 -s 10 -r 3600 \
--avoid '^(systemd|labwc|foot|sshd|chibitaru-tui|login|bash)$' \
--prefer '^(firefox-esr|Web Content|Isolated Web|llama-server|mpv)$'"
EOF
  c_ok "守る: labwc / foot / TUI / sshd"
  c_ok "先に捨てる: Firefox / 会話AI / mpv"
  svc enable earlyoom
}

# ═══════════════════════════════════════════════════════════
step_firefox() {
  c_head "Firefox"
  local dest=/usr/lib/firefox-esr/browser/defaults/preferences/chibitaru.js
  [ -d "$(dirname "$dest")" ] || { c_warn "Firefox の設定置き場がない。飛ばす"; return 0; }

  # 全ティア共通。実測の結果、ティアごとに変える意味がなかった。
  # サイト分離は切らない（30MB のために防御を落とす取引は成立しない）。
  { cat "$REPO/profiles/firefox/_base.js"
    cat "$REPO/profiles/firefox/${PROFILE}.js"
    cat "$REPO/profiles/firefox/_hardware.js"
  } > "$dest.new"

  # 構文が壊れていると Firefox はそこで読むのをやめ、以降の設定が
  # 黙って外れる。起動はするので気づけない。置き換える前に見ておく。
  local bad
  bad=$(grep -vE '^\s*(//|$)' "$dest.new" | grep -cvE '^user_pref\(".+",\s*.+\);\s*$' || true)
  if [ "$bad" -gt 0 ]; then
    rm -f "$dest.new"
    c_die "設定ファイルの構文が壊れています（${bad} 行）。profiles/firefox/ を確認してください"
  fi

  mv "$dest.new" "$dest"
  c_ok "$(grep -c '^user_pref' "$dest") 項目を $dest に（構文確認済み）"

  # この置き場は firefox-esr の更新で消える。消えたら黙って設定が
  # 外れるので、apt の後に置き直す。
  install -D -m 644 /dev/stdin /etc/apt/apt.conf.d/99chibitaru-firefox <<EOF
// install/setup.sh が生成。firefox-esr の更新で消える設定を置き直す。
DPkg::Post-Invoke { "[ -x ${HERE}/setup.sh ] && bash ${HERE}/setup.sh --only firefox --quiet || true"; };
EOF
  c_ok "更新後に置き直す apt フックを設置"
}

# ═══════════════════════════════════════════════════════════
step_podman() {
  c_head "Podman"
  # rootless で動かすには、ユーザーに割り当てる UID/GID の範囲が要る。
  for f in /etc/subuid /etc/subgid; do
    if grep -q "^${TARGET_USER}:" "$f" 2>/dev/null; then
      c_ok "$f に ${TARGET_USER} の範囲あり"
    else
      echo "${TARGET_USER}:100000:65536" >> "$f"
      c_ok "$f に範囲を追加"
    fi
  done

  # Docker のつもりで打っても通るように
  install -D -m 644 /dev/stdin /etc/profile.d/chibitaru-podman.sh <<'EOF'
# docker と打っても podman が動く。既存の手順書がそのまま通る。
command -v podman >/dev/null && ! command -v docker >/dev/null && alias docker=podman
EOF
  c_ok "docker → podman の別名を設定"
}

# ═══════════════════════════════════════════════════════════
step_vault() {
  c_head "Vault"
  # この OS で起きたことは全部ここに Markdown で残る。
  # ただのフォルダなので母艦の Obsidian でそのまま開ける。
  local v="${TARGET_HOME}/Vault"
  for d in 日記 ノート 会話 音声 web ops; do
    install -d -o "$TARGET_USER" -g "$TARGET_USER" -m 755 "$v/$d"
  done
  install -d -o "$TARGET_USER" -g "$TARGET_USER" -m 755 "$v"
  c_ok "$v （日記 / ノート / 会話 / 音声 / web / ops）"
}

# ═══════════════════════════════════════════════════════════
step_report() {
  c_head "できあがり"
  printf "    プロファイル  %s\n" "$PROFILE"
  printf "    zram          %s MB (zstd)\n" "$ZRAM_MB"
  printf "    会話AI        %s\n" "$LLM_MODEL"
  printf "    Vault         %s/Vault\n" "$TARGET_HOME"
  echo
  if $HAS_SYSTEMD; then
    echo "    再起動してから確認してください:"
    echo "      swapon --show          zram が出るか"
    echo "      sysctl vm.swappiness   150 になっているか"
  else
    echo "    systemd がないため設定を書いただけです。実機で流し直してください。"
  fi
  echo
  echo "    まだ入っていないもの: TUI シェル / 会話AI 本体 / 音声認識"
  echo "    （Phase 2 以降）"
  echo
}

# ═══════════════════════════════════════════════════════════
main() {
  local only="" quiet=false
  while [ $# -gt 0 ]; do
    case "$1" in
      --only)  only="$2"; shift 2 ;;
      --quiet) quiet=true; shift ;;
      --list)  printf '%s\n' "${STEPS[@]}"; exit 0 ;;
      *) c_die "知らない引数: $1" ;;
    esac
  done

  $quiet && exec >/dev/null

  # --only でも前提とプロファイルは要る（他の段がその変数を使うため）
  if [ -n "$only" ]; then
    step_preflight
    step_profile
    case " ${STEPS[*]} " in *" $only "*) ;; *) c_die "そんな段はない: $only" ;; esac
    [ "$only" = preflight ] || [ "$only" = profile ] || "step_$only"
  else
    for s in "${STEPS[@]}"; do "step_$s"; done
  fi
}

main "$@"
