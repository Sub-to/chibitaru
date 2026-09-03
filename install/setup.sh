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

STEPS=(preflight profile packages gpu usb zram sysctl earlyoom firefox podman sudo backlight install theme vault music ime session report)

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


# install -d は最後の階層にしか -o/-g を適用しない。
# 親を root 所有のまま残すと、そこに書こうとしたアプリが
# "permission denied" で落ちる。VM で micro が実際に落ちた。
mkuserdir() {
  local d="$1"
  install -d -m 755 "$d"
  # ホーム配下は全階層をそのユーザーの持ち物にする
  local p="$d"
  while [ "$p" != "/" ] && [ "$p" != "." ]; do
    case "$p" in
      "$TARGET_HOME"|"$TARGET_HOME"/*)
        chown "$TARGET_USER:$TARGET_USER" "$p" ;;
      *) break ;;
    esac
    p=$(dirname "$p")
  done
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
    # 音の道具。これがないとマイクの有無すら確かめられない。
    # 実機で arecord がなく「録音デバイス0件」と誤判定した。
    alsa-utils pipewire-audio
    # 見る・聴く
    firefox-esr mpv yt-dlp mpd mpc
    # 動画のハードウェアデコード。世代ごとに使うドライバが違う:
    #   Gen7.5 以前（Haswell / T440s など）→ i965
    #   Gen8 以降（Broadwell 以降）        → intel-media
    #   AMD / その他                       → mesa
    # PCI ID から世代を当てる表は壊れやすいので書かない。3つとも入れて
    # libva に選ばせる。ディスクは 50MB 増えるが、読み込まれるのは
    # 実際に使う 1 つだけなので RAM は増えない。
    i965-va-driver intel-media-va-driver mesa-va-drivers vainfo
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
    # sudo は入れておく。Debian のインストーラは root パスワードを
    # 設定すると sudo を入れないため、実機で「sudo: command not found」に
    # なった。この OS は普段使いを想定するので必要。
    sudo
    python3 python3-venv python3-pip git curl rsync ripgrep micro pciutils util-linux
    # TUI シェル。端末エミュレータは自前で持たず tmux に任せるので、
    # 下のペインでは vim も htop も普通に動く。
    python3-textual tmux
    # 日本語入力。この OS は日本語で書くためのものなので、
    # 打てないままでは成立しない。実測 45MB（fcitx5 28 + mozc 17）。
    fcitx5 fcitx5-mozc fcitx5-frontend-gtk3
    # 日本語と記号
    # fonts-noto-cjk に絵文字は入っていない。入れないと 🎤 や 🔵 が
    # 豆腐になる（VM の画面で確認）。ウェブページにも絵文字は出るので
    # ブラウザのためにも要る。
    fonts-noto-cjk fonts-noto-color-emoji
  )

  apt-get update -qq
  apt-get install -y -qq --no-install-recommends "${pkgs[@]}"
  c_ok "${#pkgs[@]} 個を導入"
}

# ═══════════════════════════════════════════════════════════
step_gpu() {
  c_head "動画のハードウェアデコード"
  # ここが効かないと再生が CPU に落ち、発熱と消費電力が跳ね上がる。
  # 「エコな OS」を名乗る以上、効いているかどうかを黙って仮定しない。

  if [ ! -e /dev/dri/renderD128 ]; then
    c_warn "/dev/dri がない。GPU を使えていない"
    c_warn "  仮想環境ならこれが普通。実機なら linux-image-amd64 と firmware を確認"
    return 0
  fi

  local gpu
  gpu=$(lspci 2>/dev/null | grep -iE "VGA|Display" | head -1 | cut -d: -f3- | sed 's/^ //')
  [ -n "$gpu" ] && c_ok "GPU: ${gpu}"

  if ! command -v vainfo >/dev/null; then
    c_warn "vainfo がない。確認できない"
    return 0
  fi

  local info drv
  info=$(vainfo 2>&1 || true)
  drv=$(printf '%s' "$info" | grep -m1 -oE "[a-z0-9_]+_drv_video\.so" || true)
  [ -n "$drv" ] && c_ok "使うドライバ: ${drv}"

  # どのドライバなら実際に H.264 が降りるかを試して決める。
  # PCI ID の表は書かない。実機（Haswell）で libva が iHD を先に試して
  # 失敗し、i965 に落ちてから動いていた。動くには動くが毎回エラーを
  # 吐くので、正解が分かっているなら最初から指定したほうがよい。
  local works=""
  for cand in i965 iHD; do
    if LIBVA_DRIVER_NAME="$cand" vainfo 2>/dev/null \
       | grep -q "VAProfileH264High.*VAEntrypointVLD"; then
      works="$cand"; break
    fi
  done
  if [ -n "$works" ]; then
    install -D -m 644 /dev/stdin /etc/profile.d/chibitaru-vaapi.sh <<EOF
# install/setup.sh が生成
# 実際に H.264 が降りることを確かめたドライバを指定する。
# 自動選択でも動くが、合わないドライバを先に試して失敗ログを出すため。
export LIBVA_DRIVER_NAME=${works}
EOF
    c_ok "VA-API ドライバを ${works} に固定（実際に試して確認）"
  fi

  # H.264 が降りれば、実用上の動画はほぼ GPU で再生される
  if printf '%s' "$info" | grep -q "VAProfileH264.*VAEntrypointVLD"; then
    c_ok "H.264 のハードウェアデコードが有効"
  else
    c_warn "H.264 のハードウェアデコードが効いていない"
    c_warn "  mpv は動くが CPU で再生され、発熱と電池消費が増える"
    printf '%s\n' "$info" | grep -iE "error|fail" | head -3 | sed 's/^/      /'
  fi
}

# ═══════════════════════════════════════════════════════════
step_usb() {
  c_head "USB 起動なら書き込みを減らす"
  # USB メモリの書き込み回数には限りがある。放っておくと数か月で
  # 壊れる。ここで効くのは主にログと atime の 2 つ。
  #
  # なお、この OS はスワップを zram（メモリ内）に置いているので、
  # 一番書き込みが多くなるスワップは最初からディスクに触れていない。

  # 根っこがどのデバイスに載っているかを調べる
  local rootsrc rootdisk removable=0
  rootsrc=$(findmnt -no SOURCE / 2>/dev/null || true)
  rootdisk=$(lsblk -no PKNAME "$rootsrc" 2>/dev/null | head -1 || true)
  [ -z "$rootdisk" ] && rootdisk=$(basename "$rootsrc" 2>/dev/null | sed 's/[0-9]*$//')

  if [ -r "/sys/block/${rootdisk}/removable" ]; then
    removable=$(cat "/sys/block/${rootdisk}/removable")
  fi
  # USB 接続かどうかも見る（removable=0 の USB SSD もあるため）
  if readlink -f "/sys/block/${rootdisk}" 2>/dev/null | grep -q "/usb[0-9]"; then
    removable=1
  fi

  if [ "$removable" != "1" ]; then
    c_skip "内蔵ディスクから起動している。何もしない"
    return 0
  fi

  c_ok "USB から起動している（/dev/${rootdisk}）"

  # ── ログをメモリに置く ──────────────────────────────
  # 一番書き込みが多いのはこれ。再起動で消えるが、残したいものは
  # Vault に書く設計なので困らない。
  install -D -m 644 /dev/stdin /etc/systemd/journald.conf.d/chibitaru-usb.conf <<'EOF'
# install/setup.sh が生成（USB 起動のため）
[Journal]
Storage=volatile
RuntimeMaxUse=32M
EOF
  c_ok "ログはメモリに置く（USB に書かない）"

  # ── 書き戻しの間隔を延ばす ──────────────────────────
  install -D -m 644 /dev/stdin /etc/sysctl.d/98-chibitaru-usb.conf <<'EOF'
# install/setup.sh が生成（USB 起動のため）
# 書き戻しをまとめて回数を減らす。落ちた時に失う量は増えるが、
# USB の寿命とのつり合いでこちらを取る。
vm.dirty_writeback_centisecs = 6000
vm.dirty_expire_centisecs = 6000
EOF
  c_ok "書き戻しをまとめる"

  # ── USB 上のスワップ領域を止める ────────────────────
  # インストーラは既定でスワップ領域を切る。USB 上にあると、
  # メモリが逼迫したときに一番書き込みの多い処理が USB へ流れる。
  # この OS は zram（メモリ内）にスワップを持つので、ディスク側は要らない。
  # 実機で /dev/sdb5 が優先度 -2 で有効になっているのを見つけた。
  local diskswap
  diskswap=$(/usr/sbin/swapon --show=NAME --noheadings 2>/dev/null \
             | grep -v zram || true)
  if [ -n "$diskswap" ]; then
    for sw in $diskswap; do
      /usr/sbin/swapoff "$sw" 2>/dev/null && c_ok "スワップを止めた: $sw" \
        || c_warn "止められなかった: $sw"
    done
    # 休止状態からの復帰先も消す。ここを消し忘れると、initramfs が
    # 存在しないスワップを探して 30 秒待ってから諦める。実機で
    # 起動が 36 秒かかり、そのうち 31 秒がこれだった。
    if grep -rqs "^RESUME=" /etc/initramfs-tools/conf.d/ 2>/dev/null; then
      install -D -m 644 /dev/stdin /etc/initramfs-tools/conf.d/resume <<'EOF'
# install/setup.sh が生成
# スワップは zram（メモリ内）にしかない。休止状態からの復帰先は無い。
# 存在しない領域を指したままだと、起動のたびに 30 秒待たされる。
RESUME=none
EOF
      update-initramfs -u >/dev/null 2>&1 \
        && c_ok "休止状態の復帰先を無効化（起動の30秒待ちを解消）" \
        || c_warn "initramfs の更新に失敗"
    fi

    # 再起動後に戻らないよう fstab からも外す。控えを取ってから。
    if grep -qE "^[^#].*\sswap\s" /etc/fstab; then
      cp -a /etc/fstab /etc/fstab.chibitaru-swap.bak
      sed -i -E 's|^([^#].*[[:space:]]swap[[:space:]].*)$|# chibitaru: USB書き込みを避けるため無効化\n#\1|' /etc/fstab
      if findmnt --verify --tab-file /etc/fstab >/dev/null 2>&1; then
        c_ok "fstab からも外した（控え: /etc/fstab.chibitaru-swap.bak）"
      else
        cp -a /etc/fstab.chibitaru-swap.bak /etc/fstab
        c_warn "fstab の検証に通らなかったので戻した"
      fi
    fi
  else
    c_ok "ディスク上のスワップはない"
  fi

  # ── atime を止める ──────────────────────────────────
  # ファイルを読むだけで書き込みが起きるのを止める。
  # fstab を壊すと起動しなくなるので、控えを取って検証してから入れ替える。
  if findmnt -no OPTIONS / | grep -qE "noatime|relatime"; then
    local cur
    cur=$(findmnt -no OPTIONS / | grep -o "noatime" || true)
    if [ -n "$cur" ]; then
      c_ok "atime は既に止まっている"
      return 0
    fi
  fi

  if grep -qE "^[^#].*\s/\s" /etc/fstab; then
    cp -a /etc/fstab /etc/fstab.chibitaru.bak
    awk '
      /^[[:space:]]*#/ { print; next }
      $2 == "/" && $4 !~ /noatime/ { sub(/^/, "noatime,", $4); print $1,$2,$3,$4,$5,$6; next }
      { print }
    ' OFS="\t" /etc/fstab > /etc/fstab.new

    if findmnt --verify --tab-file /etc/fstab.new >/dev/null 2>&1; then
      mv /etc/fstab.new /etc/fstab
      c_ok "noatime を追加（控え: /etc/fstab.chibitaru.bak）"
    else
      rm -f /etc/fstab.new
      c_warn "fstab の検証に通らなかったので触っていない"
      c_warn "  手で / の行に noatime を足してください"
    fi
  fi
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
DPkg::Post-Invoke { "[ -x /opt/chibitaru/install/setup.sh ] && bash /opt/chibitaru/install/setup.sh --only firefox --quiet || true"; };
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

  # chibitaru-theme などを PATH から呼べるようにする。
  # bin/ の中身を無条件に通すと、昔の名残（別の機種向けに作られた
  # 実行ファイルなど）まで PATH に並ぶ。実機で /usr/local/bin に
  # 動きもしない llama-server が置かれていた。名前で絞る。
  for b in /opt/chibitaru/bin/chibitaru-*; do
    [ -x "$b" ] || continue
    ln -sf "$b" "/usr/local/bin/$(basename "$b")"
  done
  # 昔の版が通した、chibitaru- で始まらないものを片づける
  for l in /usr/local/bin/*; do
    [ -L "$l" ] || continue
    case "$(readlink "$l")" in
      /opt/chibitaru/bin/chibitaru-*) ;;
      /opt/chibitaru/bin/*) rm -f "$l" ;;
    esac
  done
  c_ok "/usr/local/bin に chibitaru-* を通した"
}

# ═══════════════════════════════════════════════════════════
step_backlight() {
  c_head "画面の明るさを利用者に開ける"
  # 明るさは古い機体で電池が一番もつ効き所だが、既定では root しか
  # 書けない。画面は root で動かさないので、ここを開けないと
  # 「暗くして」と言われて何もできない。
  #
  # 開けるのは brightness だけ。video グループはもともと画面まわりを
  # 触るための入れもので、ここに明るさを足しても増える権限は無い。
  install -D -m 644 /dev/stdin /etc/udev/rules.d/90-chibitaru-backlight.rules <<'EOF'
# install/setup.sh が生成。画面の明るさを video グループに開ける。
ACTION=="add", SUBSYSTEM=="backlight", RUN+="/bin/chgrp video /sys/class/backlight/%k/brightness", RUN+="/bin/chmod g+w /sys/class/backlight/%k/brightness"
EOF
  udevadm control --reload 2>/dev/null || true

  # 規則は次の起動から効く。いま動いているものにも当てておく。
  local found=0
  for d in /sys/class/backlight/*/; do
    [ -w "$d/brightness" ] || [ -e "$d/brightness" ] || continue
    chgrp video "$d/brightness" 2>/dev/null || true
    chmod g+w   "$d/brightness" 2>/dev/null || true
    found=1
  done

  if [ "$found" = 1 ]; then
    c_ok "明るさを $TARGET_USER から変えられるようにした"
  else
    # 明るさを持たない機体（据え置き機など）もある。異常ではない。
    c_warn "明るさを変えられる画面が見つからない（据え置き機なら正常）"
  fi
}

# ═══════════════════════════════════════════════════════════
step_sudo() {
  c_head "sudo を使えるようにする"
  # パッケージがあっても、ユーザーが sudo グループに入っていなければ
  # 「is not in the sudoers file」で弾かれる。実機で踏んだ。
  if ! command -v sudo >/dev/null; then
    c_warn "sudo が入っていない（packages 段を先に流してください）"
    return 0
  fi
  if id -nG "$TARGET_USER" | tr ' ' '\n' | grep -qx sudo; then
    c_ok "${TARGET_USER} は既に sudo を使える"
  else
    usermod -aG sudo "$TARGET_USER"
    c_ok "${TARGET_USER} を sudo グループに追加"
    c_warn "反映は次のログインから（今の画面では効かない）"
  fi

  # shutdown や sysctl は /usr/sbin にあり、一般ユーザーの PATH に入らない。
  # フルパスを覚えさせるより PATH を通すほうが早い。
  install -D -m 644 /dev/stdin /etc/profile.d/chibitaru-path.sh <<'EOF'
# install/setup.sh が生成
# shutdown / sysctl / swapon などは /usr/sbin にある。
# 一般ユーザーの PATH には入らないので、sudo 越しに使う前提でも
# 補完が効くように通しておく。
case ":$PATH:" in
  *:/usr/sbin:*) ;;
  *) PATH="$PATH:/usr/sbin:/sbin" ;;
esac
EOF
  c_ok "/usr/sbin を PATH に通した"
}

# ═══════════════════════════════════════════════════════════
step_install() {
  c_head "実行ファイルを /opt/chibitaru に置く"
  # リポジトリをどこに clone したかに依存しないようにする。
  #
  # ここが抜けていて実機で画面が出なかった。autostart は
  # /opt/chibitaru/bin/chibitaru-session を見るのに、そこへ何も
  # 置いていなかった。VM では検証スクリプトが手でコピーしていたため
  # 穴が塞がって見えていた。テスト側が本番と違うことをしていた例。

  if [ "$REPO" = "/opt/chibitaru" ]; then
    c_ok "既に /opt/chibitaru から動いている"
    return 0
  fi

  install -d -m 755 /opt/chibitaru
  for d in bin lib tui tools profiles install docs; do
    [ -d "$REPO/$d" ] || continue
    rm -rf "/opt/chibitaru/$d"
    cp -a "$REPO/$d" /opt/chibitaru/
  done

  chmod +x /opt/chibitaru/bin/* 2>/dev/null || true
  chmod +x /opt/chibitaru/tools/*.sh /opt/chibitaru/tools/*.py 2>/dev/null || true
  chmod +x /opt/chibitaru/install/*.sh 2>/dev/null || true

  # 置いたものが実際に動くかまで見る。存在確認だけでは、
  # 実行権限がない・中身が壊れている場合を見逃す。
  if [ -x /opt/chibitaru/bin/chibitaru-session ]; then
    c_ok "bin/chibitaru-session"
  else
    c_die "/opt/chibitaru/bin/chibitaru-session を置けませんでした"
  fi
  if python3 -c "import ast,sys; ast.parse(open('/opt/chibitaru/tui/chibitaru_tui.py').read())" 2>/dev/null; then
    c_ok "tui/chibitaru_tui.py"
  else
    c_die "TUI を置けませんでした"
  fi
  # 目録は画面と声の両方が読み込む。置き忘れると、画面は出るのに
  # 何を言っても動かない、という分かりにくい壊れ方をする。
  # 存在だけでなく読み込めるところまで見る。
  if python3 -c "import sys; sys.path.insert(0,'/opt/chibitaru/lib'); import knobs; assert knobs.CATALOG" 2>/dev/null; then
    c_ok "lib/knobs.py（設定の目録）"
  else
    c_die "設定の目録を置けませんでした"
  fi
}

# ═══════════════════════════════════════════════════════════
step_theme() {
  c_head "見た目（配色と文字サイズ）"
  # 既に選んであればそれを尊重する。流し直しで好みが戻ると困る。
  local t=mocha sz=14
  if [ -r /etc/chibitaru/theme ]; then
    t=$(awk -F= '/^CHIBITARU_THEME=/{print $2}' /etc/chibitaru/theme)
    sz=$(awk -F= '/^CHIBITARU_FONT_SIZE=/{print $2}' /etc/chibitaru/theme)
    c_ok "既存の設定を使う（${t} / ${sz}）"
  fi
  CHIBITARU_USER="$TARGET_USER" bash /opt/chibitaru/bin/chibitaru-theme \
    "${t:-mocha}" --size "${sz:-14}" | sed 's/^/  /'
  c_ok "chibitaru-theme で後から変えられる"
}

# ═══════════════════════════════════════════════════════════
step_vault() {
  c_head "Vault"
  # この OS で起きたことは全部ここに Markdown で残る。
  # ただのフォルダなので母艦の Obsidian でそのまま開ける。
  local v="${TARGET_HOME}/Vault"
  for d in 日記 ノート 会話 音声 web ops; do
    mkuserdir "$v/$d"
  done
  c_ok "$v （日記 / ノート / 会話 / 音声 / web / ops）"
}

# ═══════════════════════════════════════════════════════════
step_music() {
  c_head "音楽（mpd）"
  # システム全体の mpd は使わない。あれは mpd ユーザーで動くため、
  # 利用者の pipewire セッションに音を出せない。個人用に切り替える。
  systemctl disable --now mpd.service mpd.socket >/dev/null 2>&1 || true
  c_ok "システム全体の mpd は止めた"

  local mus="${TARGET_HOME}/音楽"
  mkuserdir "$mus"
  mkuserdir "${TARGET_HOME}/.config/mpd"
  mkuserdir "${TARGET_HOME}/.local/share/mpd/playlists"

  install -D -o "$TARGET_USER" -g "$TARGET_USER" -m 644 /dev/stdin \
    "${TARGET_HOME}/.config/mpd/mpd.conf" <<EOF
# install/setup.sh が生成
music_directory     "${mus}"
playlist_directory  "~/.local/share/mpd/playlists"
db_file             "~/.local/share/mpd/database"
state_file          "~/.local/share/mpd/state"
sticker_file        "~/.local/share/mpd/sticker.sql"

# 起動しっぱなしにしないので、状態はこまめに残す
auto_update         "yes"
restore_paused      "yes"

audio_output {
    type  "pipewire"
    name  "Chibitaru"
}
EOF
  c_ok "$mus を音楽フォルダに"

  # ソケット起動にする。音楽を鳴らすまで mpd は動かないので、
  # 使わない人は 25MB を払わずに済む。
  if $HAS_SYSTEMD; then
    local uid; uid=$(id -u "$TARGET_USER")
    if [ -d "/run/user/$uid" ]; then
      su - "$TARGET_USER" -c \
        "XDG_RUNTIME_DIR=/run/user/$uid systemctl --user enable --now mpd.socket" \
        >/dev/null 2>&1 \
        && c_ok "mpd をソケット起動に（使うまで常駐しない）" \
        || c_warn "mpd の有効化は次のログインから"
    else
      c_warn "セッションがないため、mpd の有効化は次のログインから"
    fi
  else
    c_skip "mpd の有効化（systemd なし）"
  fi
}

# ═══════════════════════════════════════════════════════════
step_ime() {
  c_head "日本語入力（fcitx5-mozc）"
  command -v fcitx5 >/dev/null || { c_warn "fcitx5 が入っていない"; return 0; }

  # labwc 0.8.3 は入力メソッドの中継を実装しており、foot は
  # text-input-v3 に対応している。両方そろっているので、
  # Wayland のまま追加のブリッジなしで通る。
  mkuserdir "${TARGET_HOME}/.config/fcitx5/conf"

  install -D -o "$TARGET_USER" -g "$TARGET_USER" -m 644 /dev/stdin \
    "${TARGET_HOME}/.config/fcitx5/profile" <<'EOF'
# install/setup.sh が生成
[Groups/0]
Name=Default
Default Layout=jp
DefaultIM=mozc

[Groups/0/Items/0]
Name=keyboard-jp
Layout=

[Groups/0/Items/1]
Name=mozc
Layout=

[GroupOrder]
0=Default
EOF

  # 切り替えキー。半角/全角 と Ctrl+Space の両方を受ける。
  # 日本語キーボードの人は前者、そうでない人は後者を使う。
  install -D -o "$TARGET_USER" -g "$TARGET_USER" -m 644 /dev/stdin \
    "${TARGET_HOME}/.config/fcitx5/config" <<'EOF'
# install/setup.sh が生成
[Hotkey/TriggerKeys]
0=Zenkaku_Hankaku
1=Control+space

[Hotkey]
EnumerateWithTriggerKeys=True

[Behavior]
ActiveByDefault=False
ShowInputMethodInformation=True
EOF
  c_ok "mozc を既定に（切替は 半角/全角 か Ctrl+Space）"

  # GTK のアプリ（Firefox など）向け。Wayland 対応のものは
  # text-input-v3 を直接使うが、そうでないものへの保険。
  install -D -m 644 /dev/stdin /etc/profile.d/chibitaru-ime.sh <<'EOF'
# install/setup.sh が生成
export GTK_IM_MODULE=fcitx
export QT_IM_MODULE=fcitx
export XMODIFIERS=@im=fcitx
EOF
  c_ok "GTK/Qt 向けの設定も配置"

  # labwc が上がったあとに起こす
  local auto="${TARGET_HOME}/.config/labwc/autostart"
  if [ -f "$auto" ] && ! grep -q "fcitx5" "$auto"; then
    printf '%s\n' "fcitx5 -d &" >> "$auto"
    c_ok "画面と一緒に起動するようにした"
  else
    c_ok "既に autostart に入っている"
  fi
}

# ═══════════════════════════════════════════════════════════
step_session() {
  c_head "セッション（起動したら画面が出るまで）"

  # ログイン画面は置かない。この OS は 1 人で使う道具で、
  # 画面が出るまでの時間と常駐メモリを減らすほうが目的に合う。
  install -D -m 644 /dev/stdin \
    /etc/systemd/system/getty@tty1.service.d/autologin.conf <<EOF
# install/setup.sh が生成
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin ${TARGET_USER} --noclear %I \$TERM
EOF
  c_ok "tty1 に ${TARGET_USER} で自動ログイン"

  # tty1 でログインした時だけ labwc を起こす。
  # SSH から入った時に画面を奪わないよう、条件を絞ってある。
  local prof="${TARGET_HOME}/.bash_profile"
  if ! grep -q "chibitaru-session" "$prof" 2>/dev/null; then
    cat >> "$prof" <<'EOF'

# ── chibitaru-session ──────────────────────────────
# tty1 から入った時だけ画面を起こす。SSH では起こさない。
if [ -z "${WAYLAND_DISPLAY:-}" ] && [ "$(tty)" = "/dev/tty1" ]; then
    exec dbus-run-session labwc
fi
EOF
    chown "$TARGET_USER:$TARGET_USER" "$prof"
  fi
  c_ok "tty1 から入った時だけ labwc（SSH では起こさない）"

  # labwc が上がったら端末を出す。Phase 2 で TUI シェルに差し替える。
  mkuserdir "${TARGET_HOME}/.config/labwc"
  mkuserdir "${TARGET_HOME}/.config/micro"   # エディタが設定を書く先
  local session_bin=/opt/chibitaru/bin/chibitaru-session
  [ -x "$session_bin" ] || c_die "$session_bin がありません（install 段が失敗している）"

  install -D -o "$TARGET_USER" -g "$TARGET_USER" -m 755 /dev/stdin \
    "${TARGET_HOME}/.config/labwc/autostart" <<EOF
#!/bin/sh
# install/setup.sh が生成
# 端末が落ちても画面が真っ黒にならないよう、失敗したら素の foot を出す。
foot -e ${session_bin} || foot &
EOF
  c_ok "labwc の autostart に Vault シェル"

  # 画面いっぱいに端末を出す。飾りは持たない。
  install -D -o "$TARGET_USER" -g "$TARGET_USER" -m 644 /dev/stdin \
    "${TARGET_HOME}/.config/labwc/rc.xml" <<'EOF'
<?xml version="1.0"?>
<!-- install/setup.sh が生成 -->
<labwc_config>
  <theme><cornerRadius>0</cornerRadius></theme>
  <!-- 端末は装飾なしで全画面。この OS に窓を並べる用途がない -->
  <windowRules>
    <windowRule identifier="foot">
      <action name="ToggleMaximize"/>
      <serverDecoration>no</serverDecoration>
    </windowRule>
  </windowRules>
</labwc_config>
EOF
  c_ok "端末は装飾なしで全画面"

  # マイクの増幅は ALSA 側で決める。
  #
  # 実機の ALC3232 は Capture が 97%（+28.5dB）で出荷状態になっており、
  # 環境音だけで波形が上限に張り付いていた。pipewire の音量を下げても
  # 効かない — あれは ADC で既に割れた後にかかるため。
  #
  # 実測（4秒の環境音・頂点/RMS）:
  #   90% +25.5dB  32768 / 7584  割れる
  #   70% +15.8dB  20593 / 2618  割れないが環境音が大きすぎる
  #   50%  +6.8dB   3363 /  612  ← これを採る。余裕があり環境音も低い
  #   35%  -0.8dB   1804 /  238  声が小さくなりすぎる恐れ
  if command -v amixer >/dev/null && [ -d /proc/asound/card0 ]; then
    amixer -c 0 sset Capture 50% >/dev/null 2>&1 || true
    for b in "Mic Boost" "Internal Mic Boost" "Dock Mic Boost"; do
      amixer -c 0 sset "$b" 0% >/dev/null 2>&1 || true
    done
    # 再起動しても戻らないように保存する（alsa-restore が読む）
    alsactl store >/dev/null 2>&1 || true
    c_ok "マイクの増幅を 50% に（実測で決めた値・保存済み）"
  fi

  svc daemon-reload
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
