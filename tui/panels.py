#!/usr/bin/env python3
"""
Vault シェルの計器類。

数字は全部 /sys と /proc から直接読む。外部コマンドを毎秒呼ぶと、
2 コアの古い機体では計器そのものが CPU を食う。
"""

from __future__ import annotations

import subprocess
import unicodedata
from datetime import datetime
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Label, Static

WEEKDAY = ("月", "火", "水", "木", "金", "土", "日")


def dw(s: str) -> int:
    """端末上の表示幅。日本語は 1 文字で 2 桁。"""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def bar(value: float, width: int = 8) -> str:
    """0.0〜1.0 を棒にする。ミキサーの目盛りのつもり。"""
    filled = max(0, min(width, round(value * width)))
    return "▇" * filled + "░" * (width - filled)


# ── 読み取り ──────────────────────────────────────────────
def read_first(path: str, default=None):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return default


def battery() -> tuple[int | None, float | None, str]:
    """
    残量(%)・電圧(V)・状態。

    T440s は電池を 2 つ持つ（内蔵と着脱式）。合算して 1 つに見せる。
    片方だけ見ると「98%」と出ているのに急に切れる、ということが起きる。
    """
    total_now = total_full = 0
    volts, status = [], []
    for b in sorted(Path("/sys/class/power_supply").glob("BAT*")):
        now = read_first(f"{b}/energy_now") or read_first(f"{b}/charge_now")
        full = read_first(f"{b}/energy_full") or read_first(f"{b}/charge_full")
        if now and full:
            total_now += int(now)
            total_full += int(full)
        v = read_first(f"{b}/voltage_now")
        if v:
            volts.append(int(v) / 1e6)
        s = read_first(f"{b}/status")
        if s:
            status.append(s)

    pct = round(100 * total_now / total_full) if total_full else None
    volt = max(volts) if volts else None
    if any(s == "Charging" for s in status):
        mark = "充電"
    elif Path("/sys/class/power_supply/AC/online").is_file() and \
            read_first("/sys/class/power_supply/AC/online") == "1":
        mark = "電源"
    else:
        mark = "電池"
    return pct, volt, mark


def wifi() -> tuple[str | None, int | None]:
    """
    つないでいる口の名前と、電波の強さ(0〜100%)。

    dBm をそのまま出すと -48 のような負の数になり、良いのか悪いのか
    分かりにくい。カーネルが出す品質値（0〜70）を割合に直して返す。
    他の計器と単位が揃うので読みやすい。
    """
    try:
        lines = Path("/proc/net/wireless").read_text().splitlines()[2:]
    except OSError:
        return None, None
    for line in lines:
        parts = line.split()
        if len(parts) < 4:
            continue
        name = parts[0].rstrip(":")
        try:
            quality = float(parts[2].rstrip("."))
            level = float(parts[3].rstrip("."))
        except ValueError:
            continue
        # 圏外は 0 や -256 が出る。つないでいないものは出さない。
        if level in (0, -256) or quality <= 0:
            continue
        return name, max(0, min(100, round(quality / 70 * 100)))
    return None, None


def temperature() -> int | None:
    """一番熱いところ。どのセンサが CPU かは機体で違うので最大を採る。"""
    temps = []
    for z in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
        v = read_first(str(z))
        if v:
            try:
                t = int(v) / 1000
                if 0 < t < 150:      # 明らかに嘘の値は捨てる
                    temps.append(t)
            except ValueError:
                pass
    return round(max(temps)) if temps else None


class CPUMeter:
    """/proc/stat の差分で使用率を出す。前回との差なので状態を持つ。"""

    def __init__(self) -> None:
        self._prev = self._read()

    @staticmethod
    def _read() -> tuple[int, int]:
        try:
            f = Path("/proc/stat").read_text().splitlines()[0].split()[1:]
            vals = [int(x) for x in f]
            idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
            return sum(vals), idle
        except (OSError, ValueError, IndexError):
            return 0, 0

    def percent(self) -> int:
        total, idle = self._read()
        dt, di = total - self._prev[0], idle - self._prev[1]
        self._prev = (total, idle)
        if dt <= 0:
            return 0
        return max(0, min(100, round(100 * (dt - di) / dt)))


def memory() -> tuple[float, float]:
    """使用量と搭載量を GB で。"""
    info = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            k, _, v = line.partition(":")
            info[k] = int(v.split()[0])
    except (OSError, ValueError):
        return 0.0, 0.0
    total = info.get("MemTotal", 0) / 1048576
    used = (info.get("MemTotal", 0) - info.get("MemAvailable", 0)) / 1048576
    return used, total


def volume() -> float | None:
    """再生側の音量。wpctl は外部コマンドなので呼ぶ間隔を空ける。"""
    try:
        out = subprocess.run(
            ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
            capture_output=True, text=True, timeout=2,
        ).stdout
        return float(out.split()[1])
    except (FileNotFoundError, subprocess.SubprocessError, ValueError, IndexError):
        return None


def mpc(*args: str) -> str:
    """mpd を操作する。動いていなければ静かに諦める。"""
    try:
        return subprocess.run(["mpc", *args], capture_output=True,
                              text=True, timeout=2).stdout
    except (FileNotFoundError, subprocess.SubprocessError):
        return ""


# ══════════════════════════════════════════════════════════
class NewsTicker(Static):
    """
    右から左へ流れるお知らせ。地震・注意報・天気・紛争。

    集めるのは chibitaru-news の仕事で、ここは読んで流すだけ。
    取りに行くのを画面の中でやると、電波が悪い時に画面ごと固まる。
    別の腕にやらせて、こちらはファイルだけ見る。
    """

    # 個人のものが先。機械ぜんたいの既定は置き場所として残す。
    SOURCES = ("~/.cache/chibitaru/news", "/etc/chibitaru/news")
    FETCH_SECONDS = 600      # 取りに行く間隔。気象庁に何度も訊かない

    def on_mount(self) -> None:
        self._offset = 0
        self._text = ""
        self.load()
        self.set_interval(0.4, self.scroll_step)   # 流れ
        self.set_interval(60.0, self.load)         # 読み直し
        # すぐには取りに行かない。画面を出すのが先。
        self.set_timer(3.0, self.fetch)
        self.set_interval(self.FETCH_SECONDS, self.fetch)

    def fetch(self) -> None:
        self.app.run_worker(self._fetch_once, thread=True, group="news")

    def _fetch_once(self) -> None:
        # 失敗しても何も言わない。電波が無いのは普通のことで、
        # そのたびに画面に出しても、できることは何もない。
        # 前に取れたものがそのまま流れ続ける。
        try:
            subprocess.run(["chibitaru-news"], capture_output=True, timeout=90)
        except (FileNotFoundError, subprocess.SubprocessError):
            return
        self.app.call_from_thread(self.load)

    def load(self) -> None:
        lines = []
        for s in self.SOURCES:
            try:
                lines = [l.strip() for l in Path(s).expanduser().read_text().splitlines()
                         if l.strip() and not l.startswith("#")]
            except OSError:
                continue
            if lines:
                break
        self._text = "　　◆　　".join(lines) if lines else ""

    def scroll_step(self) -> None:
        if not self._text:
            self.update("")
            return
        # 端まで流れたら頭に戻す。連結して切り出すほうが実装が短い。
        pad = "　" * 8
        loop = self._text + pad
        self._offset = (self._offset + 1) % len(loop)

        # 字数ではなく桁数で切る。日本語と英数字が混ざるので、
        # 決め打ちの字数だと英語の見出しの時に右が余る。
        width = max(20, self.size.width - 2)
        shown, used = [], 0
        for ch in (loop + loop)[self._offset:]:
            cw = dw(ch)
            if used + cw > width:
                break
            shown.append(ch)
            used += cw
        self.update(" " + "".join(shown))


# ══════════════════════════════════════════════════════════
class Mixer(Vertical):
    """
    計器。つまみは置かない — 調整は声でやる。ここは見るだけ。

    札は日本語にしてある。演算・記憶・電源といった言葉のほうが、
    この OS の世界（蔵丸・鬼丸）に合う。
    """

    def compose(self) -> ComposeResult:
        yield Label("計器", classes="panel-title")
        yield Label("", id="m-vol")
        yield Label("", id="m-cpu")
        yield Label("", id="m-mem")
        yield Label("", id="m-tmp")

    def on_mount(self) -> None:
        self._cpu = CPUMeter()
        self._vol_cache = volume()
        self.tick()
        self.set_interval(2.0, self.tick)
        self.set_interval(6.0, self._refresh_volume)   # 外部コマンドなので間隔を空ける

    def _refresh_volume(self) -> None:
        self._vol_cache = volume()

    def tick(self) -> None:
        # 棒より数字。棒は「だいたい」しか分からず、いくつなのかを
        # 声で言う時に困る（実機で「いま何%か言えない」となった）。
        v = self._vol_cache
        self.query_one("#m-vol", Label).update(
            f"音量  {v*100:3.0f}%" if v is not None else "音量   ──")
        c = self._cpu.percent()
        self.query_one("#m-cpu", Label).update(f"演算  {c:3d}%")
        used, total = memory()
        pct = round(100 * used / total) if total else 0
        self.query_one("#m-mem", Label).update(f"記憶  {pct:3d}%  {used:.1f}G")
        t = temperature()
        # 熱くなってきたら色を変える。古い機体は埃で温度が上がる。
        col = "" if t is None or t < 65 else ("[$warning]" if t < 80 else "[$error]")
        end = "" if not col else "[/]"
        self.query_one("#m-tmp", Label).update(
            f"温度 {col}{t}°[/]" if t is not None and col else
            (f"温度 {t}°" if t is not None else "温度 ──"))


class MusicBar(Horizontal):
    """音楽の操作。mpd が動いていなくても画面は壊さない。"""

    def compose(self) -> ComposeResult:
        yield Label("⏮", id="mu-prev", classes="mu-btn")
        yield Label("⏵", id="mu-play", classes="mu-btn")
        yield Label("⏸", id="mu-pause", classes="mu-btn")
        yield Label("⏹", id="mu-stop", classes="mu-btn")
        yield Label("⏭", id="mu-next", classes="mu-btn")
        yield Label("", id="mu-title")

    def on_mount(self) -> None:
        self.tick()
        self.set_interval(3.0, self.tick)

    def tick(self) -> None:
        out = mpc("status")
        lines = [l for l in out.splitlines() if l.strip()]
        label = self.query_one("#mu-title", Label)
        if lines and ("[playing]" in out or "[paused]" in out):
            state = "再生中" if "[playing]" in out else "一時停止"
            label.update(f" {state}  {lines[0][:40]}")
        else:
            label.update(" [dim]止まっています[/]")

    def on_click(self, event) -> None:
        # ボタンは Label なので、押された id で振り分ける
        wid = getattr(event.widget, "id", "") or ""
        cmd = {"mu-prev": "prev", "mu-play": "play", "mu-pause": "toggle",
               "mu-stop": "stop", "mu-next": "next"}.get(wid)
        if cmd:
            mpc(cmd)
            self.tick()


class TopBar(Horizontal):
    """左に状態、右に日付と時刻。"""

    def compose(self) -> ComposeResult:
        yield Label("", id="top-state")
        yield Label("", id="top-clock")

    def on_mount(self) -> None:
        self.tick()
        self.set_interval(10.0, self.tick)

    def tick(self) -> None:
        self.query_one("#top-state", Label).update(self._state())
        now = datetime.now()
        self.query_one("#top-clock", Label).update(
            f"{now.year}-{now.month:02d}-{now.day:02d} "
            f"({WEEKDAY[now.weekday()]}) {now.hour:02d}:{now.minute:02d} ")

    def _state(self) -> str:
        parts = [f" Chibitaru {self.app.tier}"]

        pct, _, mark = battery()
        if pct is not None:
            # 残り少なくなったら色を変える。気づかず切れるのが一番困る。
            col = "[$error]" if pct <= 15 else (
                "[$warning]" if pct <= 30 else "")
            end = "[/]" if col else ""
            parts.append(f"{col}{mark} {pct}%{end}")

        name, strength = wifi()
        if name:
            # 弱くなったら色を変える。切れる前に気づけるように。
            col = "[$error]" if strength < 30 else (
                "[$warning]" if strength < 50 else "")
            end = "[/]" if col else ""
            parts.append(f"電波 {col}{strength}%{end}")
        else:
            parts.append("[dim]電波 圏外[/]")

        return "  │  ".join(parts)
