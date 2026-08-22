#!/usr/bin/env python3
"""
メモリ実測ツール — 設計書の予算表を推定から実測へ置き換えるためのもの。

RSS ではなく PSS（比例配分セットサイズ）で数える。Firefox のように
共有ライブラリを大量に抱えるプロセスでは RSS が二重計上になるため、
「このプロセスが実際にいくら占めているか」は PSS でしか出せない。

  ./measure.py                  今の内訳を出す
  ./measure.py --peak 60        60秒サンプリングして最大値を出す
  ./measure.py --json           機械可読（予算表との突き合わせ用）
"""

import argparse
import json
import os
import sys
import time
import unicodedata
from pathlib import Path


def dw(s):
    """端末上の表示幅。日本語は 1 文字で 2 桁を占める。"""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def pad(s, width, align="<"):
    """表示幅で揃える。str.ljust は文字数で数えるので日本語だと崩れる。"""
    fill = " " * max(0, width - dw(s))
    return s + fill if align == "<" else fill + s

# ── 設計書の予算（MB）。実測をこれと突き合わせる ─────────────────
# Firefox の 800 は推定ではなく実測（3タブ / 各3回 / 中央値）。
# 設定でこれ以下にはならないことを確認済みなので、全ティア同値。
# 2GB / 1GB は別プロジェクトに分離した（実機での検証に切り替えたため）。
BUDGET = {
    "4g": {"基盤": 540, "Firefox": 800, "会話AI": 420, "mpv": 180, "コンテナ": 350},
    "8g": {"基盤": 540, "Firefox": 800, "会話AI": 1150, "mpv": 180, "コンテナ": 350},
}

# ── プロセス名 → 構成要素。上から順に最初に一致したものを採る ────
COMPONENTS = [
    # パスに /chibitaru/ を含むだけのシェルを拾わないよう、実行ファイル名で照合する
    ("TUI シェル",  ("chibitaru-tui", "chibitaru_tui", "tui.py")),
    ("端末",        ("foot", "footclient", "alacritty")),
    ("labwc",       ("labwc", "sway", "wlroots")),
    ("Firefox",     ("firefox", "Web Content", "Isolated Web Co", "WebExtensions",
                     "RDD Process", "Utility Process", "Privileged Cont")),
    ("会話AI",      ("llama-server", "llama-cli", "ollama")),
    ("音声認識",    ("whisper", "whisper-cli", "main.whisper")),
    ("mpv",         ("mpv", "yt-dlp")),
    ("mpd",         ("mpd",)),
    ("pipewire",    ("pipewire", "pipewire-pulse", "wireplumber")),
    ("MYLN",        ("myln", "myln-daemon", "conductor.py")),
    ("コンテナ",    ("conmon", "crun", "runc", "podman", "catatonit")),
    ("sshd",        ("sshd",)),
]


CGROUP = Path("/sys/fs/cgroup")


def read_meminfo():
    """
    搭載量・使用量・空きを MB で返す。

    box.sh の中では /proc/meminfo がホストの搭載量（開発機なら 32GB）を
    返してしまう。meminfo は名前空間化されないため、2GB の箱にいても
    「空き 76%」のような嘘になる。cgroup の上限が効いている場合は
    そちらを正とする。
    """
    host = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        k, _, v = line.partition(":")
        host[k] = int(v.split()[0]) // 1024  # kB → MB

    limit = _cgroup_limit()
    if limit is None:
        host["Source"] = "host"
        return host

    total, current, file_cache = limit
    return {
        "MemTotal": total,
        # ページキャッシュは回収できるので空き側に数える
        "MemAvailable": max(0, total - current + file_cache),
        "MemFree": max(0, total - current),
        "Cached": file_cache,
        "Source": "cgroup",
    }


def _cgroup_limit():
    """cgroup v2 の上限が効いていれば (総量, 使用量, キャッシュ) を MB で返す。"""
    try:
        raw = (CGROUP / "memory.max").read_text().strip()
        if raw == "max":
            return None
        total = int(raw) // 1048576
        current = int((CGROUP / "memory.current").read_text().strip()) // 1048576
    except (OSError, ValueError):
        return None

    file_cache = 0
    try:
        for line in (CGROUP / "memory.stat").read_text().splitlines():
            key, _, val = line.partition(" ")
            if key == "file":
                file_cache = int(val) // 1048576
                break
    except (OSError, ValueError):
        pass
    return total, current, file_cache


def zram_stats():
    """zram の実効圧縮率。載っていなければ None。"""
    out = []
    for dev in sorted(Path("/sys/block").glob("zram*")):
        try:
            orig, compr, mem_used = (
                Path(dev / "mm_stat").read_text().split()[:3]
            )
        except (OSError, ValueError):
            continue
        orig, compr = int(orig), int(compr)
        out.append({
            "device": dev.name,
            "orig_mb": orig // 1048576,
            "compressed_mb": compr // 1048576,
            # 空の zram は圧縮率を持たない。0 を入れて「未使用」と描き分ける。
            "ratio": round(orig / compr, 2) if orig and compr else 0.0,
        })
    return out


class Denied(Exception):
    """smaps_rollup が権限で読めなかった。0 と区別する必要がある。"""


def proc_pss(pid):
    """
    PSS を MB で返す。

    読めなかった場合に 0 を返してはいけない。rootless の podman は
    CAP_SYS_PTRACE を落とすため、別ユーザーのプロセスがまるごと
    読めなくなる。それを 0 として数えると「Firefox は 2MB でした」の
    ような、一見もっともらしい嘘の計測結果になる。
    """
    try:
        for line in Path(f"/proc/{pid}/smaps_rollup").read_text().splitlines():
            if line.startswith("Pss:"):
                return int(line.split()[1]) / 1024
    except PermissionError:
        raise Denied from None
    except (OSError, ValueError):
        pass  # プロセスが消えただけ。無視してよい。
    return None


def proc_name(pid):
    """comm より cmdline のほうが Firefox の子プロセスを見分けられる。"""
    try:
        comm = Path(f"/proc/{pid}/comm").read_text().strip()
    except OSError:
        return None
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ")
        cmdline = raw.decode("utf-8", "replace").strip()
    except OSError:
        cmdline = ""
    return comm, cmdline


def classify(comm, cmdline):
    hay = f"{comm} {cmdline}"
    for label, patterns in COMPONENTS:
        if any(p in hay for p in patterns):
            return label
    return None


def sample():
    """今この瞬間の構成要素別 PSS を返す。(groups, 未分類MB, 読めなかった数)"""
    groups = {}
    unclassified = 0.0
    denied = 0
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        names = proc_name(entry)
        if names is None:
            continue
        try:
            pss = proc_pss(entry)
        except Denied:
            denied += 1
            continue
        if pss is None:
            continue
        label = classify(*names)
        if label is None:
            unclassified += pss
        else:
            g = groups.setdefault(label, {"mb": 0.0, "procs": 0})
            g["mb"] += pss
            g["procs"] += 1
    return groups, unclassified, denied


def merge_peak(acc, groups):
    for label, g in groups.items():
        cur = acc.setdefault(label, {"mb": 0.0, "procs": 0})
        if g["mb"] > cur["mb"]:
            cur["mb"] = g["mb"]
            cur["procs"] = g["procs"]


def render(groups, unclassified, denied, mem, tier, elapsed=None):
    total_used = mem["MemTotal"] - mem["MemAvailable"]
    identified = sum(g["mb"] for g in groups.values())
    budget = BUDGET.get(tier, {})

    print()
    where = "箱" if mem.get("Source") == "cgroup" else "実機"
    head = f"  メモリ実測  ({where} {mem['MemTotal']} MB"
    if elapsed:
        head += f" / {elapsed}秒間の最大値"
    print(head + ")")
    rule = "  " + "─" * 60
    print(rule)
    print("  " + pad("構成要素", 16) + pad("実測", 10, ">")
          + pad("予算", 8, ">") + pad("差", 10, ">") + pad("数", 6, ">"))
    print(rule)

    order = [label for label, _ in COMPONENTS if label in groups]
    for label in order:
        g = groups[label]
        b = budget.get(label)
        if b is None:
            b_s, d_s = "—", ""
        else:
            b_s = str(b)
            delta = g["mb"] - b
            # 予算を 25% 超えたら印をつける。設計を直すか実装を絞るかの分岐点。
            d_s = f"{delta:+.0f}" + ("!" if delta > b * 0.25 else "")
        print("  " + pad(label, 16) + pad(f"{g['mb']:.0f} MB", 10, ">")
              + pad(b_s, 8, ">") + pad(d_s, 10, ">")
              + pad(str(g["procs"]), 6, ">"))

    print(rule)
    for label, val in (
        ("計測できた分", f"{identified:.0f} MB"),
        ("その他+kernel", f"{total_used - identified:.0f} MB"),
        ("システム使用計", f"{total_used:.0f} MB"),
        ("空き", f"{mem['MemAvailable']:.0f} MB"),
    ):
        line = "  " + pad(label, 16) + pad(val, 10, ">")
        if label == "その他+kernel":
            line += f"   未分類プロセス {unclassified:.0f} MB を含む"
        elif label == "システム使用計":
            line += f"   / {mem['MemTotal']} MB = {100*total_used/mem['MemTotal']:.0f}%"
        elif label == "空き":
            line += f"   = {100*mem['MemAvailable']/mem['MemTotal']:.0f}%"
        print(line)

    # 箱の中から見える zram はホストのもの。混乱するので出さない。
    if denied:
        print(rule)
        print(f"  ⚠ {denied} 個のプロセスを権限で読めなかった。この数字は過少。")
        print("    rootless podman は CAP_SYS_PTRACE を落とすため、別ユーザーの")
        print("    プロセスが丸ごと欠ける。--cap-add=SYS_PTRACE を付けて測り直すこと。")

    z = zram_stats() if mem.get("Source") == "host" else []
    if z:
        print(rule)
        for d in z:
            if d["orig_mb"] == 0:
                print(f"  zram {d['device']}  未使用（スワップが発生していない）")
            else:
                print(f"  zram {d['device']}  {d['orig_mb']} MB を "
                      f"{d['compressed_mb']} MB に圧縮  ×{d['ratio']}")
    print()

    if mem["MemAvailable"] < mem["MemTotal"] * 0.3:
        print("  ⚠ 空きが 30% を切っている。ページキャッシュが痩せて")
        print("    ディスクを読み直し続ける状態に入りやすい。")
        print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--peak", type=int, metavar="SEC",
                    help="指定秒数サンプリングして最大値を出す")
    ap.add_argument("--tier", choices=("4g", "8g"),
                    help="突き合わせる予算（省略時は搭載量から推定）")
    ap.add_argument("--json", action="store_true", help="機械可読で出す")
    args = ap.parse_args()

    mem = read_meminfo()
    tier = args.tier or ("4g" if mem["MemTotal"] <= 5120 else "8g")

    if args.peak:
        acc, unc, den = {}, 0.0, 0
        deadline = time.monotonic() + args.peak
        while time.monotonic() < deadline:
            groups, u, d = sample()
            merge_peak(acc, groups)
            unc = max(unc, u)
            den = max(den, d)
            if not args.json:
                total = sum(g["mb"] for g in acc.values())
                left = int(deadline - time.monotonic())
                print(f"\r  計測中… 残り {left:>3}秒   最大 {total:.0f} MB ",
                      end="", file=sys.stderr, flush=True)
            time.sleep(1)
        if not args.json:
            print("\r" + " " * 46 + "\r", end="", file=sys.stderr)
        groups, unclassified, denied, elapsed = acc, unc, den, args.peak
    else:
        groups, unclassified, denied = sample()
        elapsed = None

    if args.json:
        json.dump({
            "tier": tier,
            "meminfo": {k: mem[k] for k in
                        ("MemTotal", "MemAvailable", "MemFree", "Cached")},
            "components": groups,
            "unclassified_mb": round(unclassified, 1),
            "denied_procs": denied,
            "zram": zram_stats(),
        }, sys.stdout, ensure_ascii=False, indent=2)
        print()
    else:
        render(groups, unclassified, denied, mem, tier, elapsed)


if __name__ == "__main__":
    main()
