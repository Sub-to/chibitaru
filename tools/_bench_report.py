#!/usr/bin/env python3
"""
firefox-bench.sh の集計。

同じ条件でも 750〜790MB のように 40MB 程度ぶれるので、1 回の計測で
「調整が効いた／効かない」を判断してはいけない。複数回まわして
中央値で比べ、ばらつきも一緒に出す。

  --raw   : 箱の中から 1 回分を出す（measure.py --json を受ける）
  それ以外 : 集めた結果ファイルを表にする
"""
import json
import statistics
import sys
from collections import defaultdict

BUDGET = {"4g": 800, "8g": 800}   # 実測にもとづく（旧 550/900）


def raw(tier, mode):
    d = json.load(sys.stdin)
    ff = d["components"].get("Firefox", {"mb": 0.0, "procs": 0})
    denied = d.get("denied_procs", 0)
    # 読めなかったプロセスがあれば数字は過少。集計側で捨てる。
    print(f"RESULT {tier} {mode} {ff['mb']:.0f} {ff['procs']} {denied}")


def summarize(path):
    runs = defaultdict(list)
    procs = defaultdict(list)
    bad = 0
    for line in open(path):
        if not line.startswith("RESULT "):
            continue
        _, tier, mode, mb, np_, denied = line.split()
        if int(denied) > 0 or float(mb) < 50:
            bad += 1
            continue
        runs[(tier, mode)].append(float(mb))
        procs[(tier, mode)].append(int(np_))

    if not runs:
        print("  有効な計測が 1 件もない。")
        return

    print()
    print("  Firefox メモリ実測 — 中央値")
    print("  " + "─" * 66)
    print(f"  {'':<4} {'調整なし':>18} {'調整あり':>18} {'差':>10} {'予算':>8}")
    print("  " + "─" * 66)

    for tier in ("4g", "8g"):
        base = runs.get((tier, "none"))
        tuned = runs.get((tier, tier))
        if not base or not tuned:
            continue
        b, t = statistics.median(base), statistics.median(tuned)
        bp = statistics.median(procs[(tier, "none")])
        tp = statistics.median(procs[(tier, tier)])
        delta = t - b
        budget = BUDGET[tier]
        over = "" if t <= budget else f"  超過+{t - budget:.0f}"
        print(f"  {tier:<4} {b:>8.0f}MB {bp:>3.0f}proc "
              f"{t:>8.0f}MB {tp:>3.0f}proc "
              f"{delta:>+9.0f} {budget:>8}{over}")

    print("  " + "─" * 66)
    for tier in ("4g", "8g"):
        for mode, label in (("none", "調整なし"), (tier, "調整あり")):
            vals = runs.get((tier, mode))
            if not vals or len(vals) < 2:
                continue
            print(f"  {tier} {label}  n={len(vals)}  "
                  f"幅 {min(vals):.0f}〜{max(vals):.0f}MB")
    if bad:
        print(f"  ⚠ {bad} 件は計測不良として除外（権限不足か起動失敗）")
    print()


if __name__ == "__main__":
    if sys.argv[1] == "--raw":
        raw(sys.argv[2], sys.argv[3])
    else:
        summarize(sys.argv[1])
