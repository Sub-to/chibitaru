#!/usr/bin/env python3
"""
消費電力を実測する。

「エコな OS」を名乗る以上、消費電力は主張ではなく数字で持つ。
Intel の RAPL カウンタ（累積エネルギー）を 2 回読んで差を取る。

  ./power.py                  5 秒測る
  ./power.py -s 30            30 秒測る
  ./power.py -- mpv video.mp4 そのコマンドを動かしながら測る
  ./power.py --json           機械可読

RAPL が読めない機体（AMD の一部・仮想環境）では測れない。その場合は
黙って 0 を返さず、測れないと言う。ゼロと未計測を混同すると、
「省電力です」という嘘の根拠になる。
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

POWERCAP = Path("/sys/class/powercap")


class Domain:
    """RAPL の 1 ドメイン（package / core / uncore / dram）。"""

    def __init__(self, path: Path):
        self.path = path
        self.name = (path / "name").read_text().strip()
        self.energy = path / "energy_uj"
        self.max_uj = int((path / "max_energy_range_uj").read_text())

    def read(self) -> int:
        return int(self.energy.read_text())


def find_domains() -> list[Domain]:
    out = []
    for p in sorted(POWERCAP.glob("intel-rapl:*")):
        try:
            out.append(Domain(p))
        except (OSError, ValueError):
            continue
    return out


def measure(domains, seconds: float, proc=None):
    """
    seconds 秒ぶんの平均電力を W で返す。

    カウンタは上限で 0 に戻る。差が負なら 1 周したものとして補正する。
    ここを見落とすと、たまに巨大な値や負の値が出る。
    """
    t0 = time.monotonic()
    first = {d.name: d.read() for d in domains}

    if proc is not None:
        # コマンドが終わるまで待つ。長すぎる場合は seconds で打ち切る。
        try:
            proc.wait(timeout=seconds)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
    else:
        time.sleep(seconds)

    elapsed = time.monotonic() - t0
    result = {}
    for d in domains:
        delta = d.read() - first[d.name]
        if delta < 0:
            delta += d.max_uj          # カウンタが一周した
        result[d.name] = (delta / 1e6) / elapsed   # µJ → J → W
    return result, elapsed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-s", "--seconds", type=float, default=5.0)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("cmd", nargs="*", help="-- のあとに測りたいコマンド")
    args = ap.parse_args()

    domains = find_domains()
    if not domains:
        msg = ("RAPL が読めないため消費電力を測れません。\n"
               "  Intel の対応機か、仮想環境でないかを確認してください。")
        if args.json:
            json.dump({"error": "rapl_unavailable"}, sys.stdout)
            print()
        else:
            print(f"\n  {msg}\n", file=sys.stderr)
        return 2

    proc = None
    if args.cmd:
        proc = subprocess.Popen(args.cmd,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)

    watts, elapsed = measure(domains, args.seconds, proc)

    if args.json:
        json.dump({"seconds": round(elapsed, 2), "watts": watts},
                  sys.stdout, ensure_ascii=False, indent=2)
        print()
        return 0

    total = watts.get("package-0", sum(watts.values()))
    print()
    print(f"  消費電力（{elapsed:.1f}秒の平均）")
    print("  " + "─" * 40)
    for name, w in sorted(watts.items()):
        label = {"package-0": "CPU全体", "core": "コア",
                 "uncore": "内蔵GPU", "dram": "メモリ"}.get(name, name)
        print(f"  {label:<10} {w:>7.2f} W")
    print("  " + "─" * 40)
    # 1 日 8 時間この状態で使った場合の目安
    print(f"  この状態で8時間: {total * 8 / 1000:.2f} kWh 相当")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
