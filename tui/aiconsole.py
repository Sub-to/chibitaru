#!/usr/bin/env python3
"""
AI の居場所。

つまみを並べる代わりに、ここへ話しかけて動かす。円は飾りではなく
状態そのもので、待っているのか・聞いているのか・考えているのかが
一目で分かる。声が届いているか分からないまま話し続けるのが一番困る。
"""

from __future__ import annotations

import math
from datetime import datetime

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Label, Static

# 状態 → (中央の一文字, 環の数, 回る速さ)
STATES = {
    "idle":   ("待", 3, 0.012),
    "listen": ("聞", 4, 0.070),
    "think":  ("考", 4, 0.045),
    "speak":  ("話", 4, 0.030),
    "off":    ("休", 2, 0.000),
}

# 濃さの段階。薄い方から。
SHADES = " ·∙◦●"


class Ring(Static):
    """同心の環。角度と位相で濃淡を作り、回っているように見せる。"""

    def on_mount(self) -> None:
        self._phase = 0.0
        self.state = "idle"
        self.set_interval(0.12, self._tick)

    def set_state(self, state: str) -> None:
        if state in STATES:
            self.state = state

    def _tick(self) -> None:
        self._phase += 1.0
        self.refresh()

    def render(self) -> str:
        w, h = self.size.width, self.size.height
        if w < 16 or h < 5:
            # 小さすぎる時は文字だけ出す。潰れた円を出すより読める。
            return STATES[self.state][0].center(max(1, w))

        label, rings, speed = STATES[self.state]
        cx, cy = (w - 1) / 2, (h - 1) / 2
        # 升目は縦長なので横を潰して丸く見せる。2.0 だと真円になるが、
        # 横に広い画面では小さく見えるので少し楕円に寄せてある。
        aspect = 2.8
        span = min((h - 1) / 2.0, (w - 1) / (aspect * 2))
        inner = max(1.8, span * 0.30)
        gap = max(0.8, (span - inner) / max(1, rings))
        edge = span + 0.9          # 外の輪郭

        grid = [[" "] * w for _ in range(h)]
        for y in range(h):
            for x in range(w):
                dx, dy = (x - cx) / aspect, y - cy
                d = math.hypot(dx, dy)
                # 輪郭は動かさない。ここが動くと全体が落ち着かない。
                if abs(d - edge) < 0.40:
                    grid[y][x] = "·"
                    continue
                if d < inner - 0.7:      # 中央は文字のために空ける
                    continue
                a = math.atan2(dy, dx)
                for i in range(rings):
                    r = inner + i * gap
                    if abs(d - r) < 0.40:
                        t = (a / (2 * math.pi)
                             + self._phase * speed - i * 0.12) % 1.0
                        lv = 1.0 - abs(t - 0.5) * 2.0
                        grid[y][x] = SHADES[min(4, int(lv * 5))]
                        break

        mid = h // 2
        col = int(cx)
        if 0 <= mid < h and 0 <= col < w:
            grid[mid][col] = label
            # 全角なので隣の升は潰す（ここを消さないと桁がずれる）
            if col + 1 < w:
                grid[mid][col + 1] = ""

        # 末尾を削らない。行の長さが揃っていないと、中央揃えが
        # 一番長い行を基準にしてしまい、円が横にずれる（実機でずれた）。
        # 升目を最後まで埋めれば、格子の作り方どおり真ん中に来る。
        return "\n".join("".join(r) for r in grid)


class AIConsole(Vertical):
    """円と、やりとりの記録。"""

    MAX_LINES = 6

    def compose(self) -> ComposeResult:
        yield Ring(id="ring")
        yield Static("", id="ai-log")

    def on_mount(self) -> None:
        self._lines: list[str] = []
        self.say("ちびたる", "話しかけてください。会話は右のボタンで入り切りできます。")

    def set_state(self, state: str) -> None:
        self.query_one("#ring", Ring).set_state(state)

    def say(self, who: str, text: str) -> None:
        """やりとりを 1 行足す。古いものから消えていく。"""
        stamp = datetime.now().strftime("%H:%M")
        mark = "[$accent]" if who == "ちびたる" else "[$success]"
        self._lines.append(f"[dim]{stamp}[/] {mark}{who}[/] {text}")
        self._lines = self._lines[-self.MAX_LINES:]
        self.query_one("#ai-log", Static).update("\n".join(self._lines))


class Switches(Vertical):
    """
    大事な操作だけは押せるようにしておく。

    声で動かす前提の画面だが、声が効かない時に電源を切れないと詰む。
    逃げ道を、壊れているかもしれない仕組みに預けない。
    """

    def compose(self) -> ComposeResult:
        yield Label(" 会話  切", id="sw-talk", classes="switch")
        yield Label(" 電源", id="sw-power", classes="switch")

    def on_mount(self) -> None:
        self.talking = False

    def set_talking(self, on: bool) -> None:
        self.talking = on
        self.query_one("#sw-talk", Label).update(
            " 会話  [$success]入[/]" if on else " 会話  切")
        self.query_one("#sw-talk", Label).set_class(on, "on")

    def on_click(self, event) -> None:
        wid = getattr(event.widget, "id", "") or ""
        if wid == "sw-talk":
            self.app.action_toggle_talk()
        elif wid == "sw-power":
            self.app.action_power_off()
