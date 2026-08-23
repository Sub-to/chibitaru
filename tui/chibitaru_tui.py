#!/usr/bin/env python3
"""
Chibitaru OS の Vault シェル。

この OS のデスクトップにあたるもの。アイコンを並べる画面は持たず、
起動すると Vault（Markdown のフォルダ）そのものが出る。

画面の下半分は本物の bash が動いている。端末エミュレータを自前で
持たず tmux に任せているので、vim も htop も普通に動く。
このプログラムが受け持つのは Vault 側だけ。

  ┌─ tree ────┬─ preview ─────────┐
  │ 日記      │ # 2026-08-23      │  ← このプログラム
  │ ノート    │ …                 │
  ├───────────┴───────────────────┤
  │ $ _                           │  ← 本物の bash（tmux の別ペイン）
  └───────────────────────────────┘

キー:
  ↑↓        選ぶ          Enter  読む
  e         下のシェルで開く（micro）
  /         Vault 全体を検索
  n         今日の日記を作る
  r         読み直す      q      終了
"""

from __future__ import annotations

import os
import re
import subprocess
import unicodedata
from datetime import date, datetime
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    DirectoryTree,
    Footer,
    Input,
    ListItem,
    ListView,
    Label,
    Markdown,
    Static,
)

# ── 表示幅 ────────────────────────────────────────────────
# 日本語は 1 文字で 2 桁を占める。文字数で詰めると必ずずれる。
# docs/TUI-の前提.md 参照。


def dw(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def pad(s: str, width: int) -> str:
    return s + " " * max(0, width - dw(s))


def clip(s: str, width: int) -> str:
    """表示幅で切る。日本語の途中で切っても幅が合うようにする。"""
    out, w = [], 0
    for c in s:
        cw = 2 if unicodedata.east_asian_width(c) in "WF" else 1
        if w + cw > width:
            break
        out.append(c)
        w += cw
    return "".join(out)


# ── 設定 ──────────────────────────────────────────────────
def load_profile() -> dict:
    """setup.sh が書いた /etc/chibitaru/profile を読む。"""
    conf = {}
    p = Path("/etc/chibitaru/profile")
    if p.is_file():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                conf[k.strip()] = v.strip()
    return conf


def _theme_path() -> str:
    """
    /etc/chibitaru/theme で選ばれた配色ファイルを返す。
    無ければ mocha に落ちる（設定が壊れていても画面は出す）。
    """
    name = "mocha"
    conf = Path("/etc/chibitaru/theme")
    if conf.is_file():
        for line in conf.read_text().splitlines():
            if line.startswith("CHIBITARU_THEME="):
                cand = line.partition("=")[2].strip()
                if cand:
                    name = cand
    here = Path(__file__).resolve().parent.parent / "profiles" / "theme"
    css = here / f"{name}.tcss"
    if not css.is_file():
        css = here / "mocha.tcss"
    return str(css)


PROFILE = load_profile()
VAULT = Path(
    os.environ.get("CHIBITARU_VAULT")
    or PROFILE.get("CHIBITARU_VAULT")
    or (Path.home() / "Vault")
)
TIER = PROFILE.get("CHIBITARU_PROFILE", "?")

WIKILINK = re.compile(r"\[\[([^\]|#]+)")


# ── ウィジェット ──────────────────────────────────────────
class VaultTree(DirectoryTree):
    """Vault のツリー。Markdown 以外と隠しファイルは出さない。"""

    def filter_paths(self, paths):
        for p in paths:
            if p.name.startswith("."):
                continue
            if p.is_dir() or p.suffix.lower() in (".md", ".markdown", ".canvas"):
                yield p


WEEKDAY = ("月", "火", "水", "木", "金", "土", "日")


class TopBar(Horizontal):
    """
    画面のいちばん上。左に状態、右に日付と時刻。

    下ではなく上に置いたのは、下は本物のシェルが占めていて
    視線がそちらに行くため。常に見えていてほしいものは上に出す。
    """

    def compose(self) -> ComposeResult:
        yield Label("", id="top-state")
        yield Label("", id="top-clock")

    def on_mount(self) -> None:
        self.tick()
        # 秒は出さないので 10 秒ごとで足りる。無駄に起こさない。
        self.set_interval(10.0, self.tick)

    def tick(self) -> None:
        self.query_one("#top-state", Label).update(self._state())
        self.query_one("#top-clock", Label).update(self._clock())

    def _clock(self) -> str:
        now = datetime.now()
        return (f"{now.year}-{now.month:02d}-{now.day:02d} "
                f"({WEEKDAY[now.weekday()]}) {now.hour:02d}:{now.minute:02d} ")

    def _state(self) -> str:
        try:
            info = {}
            for line in Path("/proc/meminfo").read_text().splitlines():
                k, _, v = line.partition(":")
                info[k] = int(v.split()[0]) // 1024
            total = info["MemTotal"]
            used = total - info["MemAvailable"]
            ratio = used / total if total else 0
            # 空きが減ってきたら色で気づけるようにする。earlyoom が
            # 何かを落とす前に、利用者が自分で閉じられるほうがよい。
            color = "green" if ratio < 0.6 else "yellow" if ratio < 0.8 else "red"
            mem = f"[{color}]RAM {used/1024:.1f}/{total/1024:.1f}G[/]"
        except (OSError, KeyError, ValueError):
            mem = "RAM ?"
        notes = sum(1 for _ in VAULT.rglob("*.md")) if VAULT.is_dir() else 0
        return f" Chibitaru {TIER}  │  ノート {notes}  │  {mem}"


# ── 本体 ──────────────────────────────────────────────────
class ChibitaruTUI(App):
    TITLE = "Chibitaru"

    # 配色は外のファイルに置く。chibitaru-theme で切り替えられるように。
    CSS_PATH = _theme_path()


    BINDINGS = [
        Binding("e", "edit", "編集"),
        Binding("slash", "search", "検索"),
        Binding("n", "today", "今日の日記"),
        Binding("r", "reload", "読み直す"),
        Binding("q", "quit", "終了"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.current: Path | None = None

    def compose(self) -> ComposeResult:
        yield TopBar()
        yield Input(placeholder="Vault を検索（Enter で実行、Esc で閉じる）", id="search")
        with Horizontal(id="body"):
            with Vertical(id="left"):
                yield VaultTree(str(VAULT), id="tree")
                with Vertical(id="backlinks"):
                    yield Label("ここへのリンク", id="backlinks-title")
                    yield ListView(id="backlist")
            with Vertical(id="right"):
                yield Markdown("", id="view")
        yield Footer()

    def on_mount(self) -> None:
        if not VAULT.is_dir():
            self.query_one("#view", Markdown).update(
                f"# Vault がありません\n\n`{VAULT}` が見つかりません。\n\n"
                "`sudo bash install/setup.sh --only vault` で作れます。"
            )

    # ── ファイルを開く ──────────────────────────────────
    def on_directory_tree_file_selected(
        self, event: DirectoryTree.FileSelected
    ) -> None:
        self.open_note(event.path)

    def open_note(self, path: Path) -> None:
        self.current = path
        view = self.query_one("#view", Markdown)
        try:
            view.update(path.read_text(encoding="utf-8", errors="replace"))
        except OSError as e:
            view.update(f"# 読めません\n\n`{path}`\n\n```\n{e}\n```")
        self.sub_title = clip(str(path.relative_to(VAULT)), 60)
        self.update_backlinks(path)

    def update_backlinks(self, path: Path) -> None:
        """このノートを [[…]] で指している他のノートを集める。"""
        lst = self.query_one("#backlist", ListView)
        lst.clear()
        stem = path.stem
        found = []
        for md in VAULT.rglob("*.md"):
            if md == path:
                continue
            try:
                text = md.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if any(t.strip() == stem for t in WIKILINK.findall(text)):
                found.append(md)
                if len(found) >= 20:      # 多すぎる時は打ち切る
                    break
        for md in found:
            lst.append(ListItem(Label(clip(md.stem, 28))))
        self._backlinks = found
        self.query_one("#backlinks-title", Label).update(
            f"ここへのリンク {len(found)}件" if found else "ここへのリンク なし"
        )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        idx = event.list_view.index
        if idx is not None and 0 <= idx < len(getattr(self, "_backlinks", [])):
            self.open_note(self._backlinks[idx])

    # ── 下のシェルを動かす ──────────────────────────────
    def action_edit(self) -> None:
        """
        選んでいるノートを下のシェルペインで開く。

        自前でエディタを持たない。下は本物の bash なので、
        使い慣れたエディタがそのまま使える。
        """
        if not self.current:
            self.notify("先にノートを選んでください")
            return
        pane = os.environ.get("CHIBITARU_SHELL_PANE")
        if not pane:
            self.notify("シェルペインが見つかりません（tmux 経由で起動してください）")
            return
        editor = os.environ.get("EDITOR", "micro")
        subprocess.run(
            ["tmux", "send-keys", "-t", pane,
             f"{editor} {shquote(str(self.current))}", "Enter"],
            check=False,
        )
        subprocess.run(["tmux", "select-pane", "-t", pane], check=False)

    # ── その他 ──────────────────────────────────────────
    def action_today(self) -> None:
        """今日の日記。なければ作る。"""
        d = date.today()
        path = VAULT / "日記" / f"{d.isoformat()}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(f"# {d.isoformat()}\n\n", encoding="utf-8")
            self.notify(f"作りました: {path.name}")
        self.query_one("#tree", VaultTree).reload()
        self.open_note(path)

    def action_search(self) -> None:
        box = self.query_one("#search", Input)
        box.add_class("visible")
        box.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        query = event.value.strip()
        event.input.remove_class("visible")
        event.input.value = ""
        self.query_one("#tree", VaultTree).focus()
        if not query:
            return
        # ripgrep があれば使う。なければ Python で拾う。
        try:
            out = subprocess.run(
                ["rg", "-n", "--no-heading", "-S", "-m", "3", query, str(VAULT)],
                capture_output=True, text=True, timeout=10,
            ).stdout
        except (FileNotFoundError, subprocess.SubprocessError):
            out = self._grep(query)

        if not out.strip():
            self.query_one("#view", Markdown).update(
                f"# 見つかりません\n\n`{query}`"
            )
            return
        lines = []
        for line in out.splitlines()[:60]:
            parts = line.split(":", 2)
            if len(parts) == 3:
                try:
                    rel = Path(parts[0]).relative_to(VAULT)
                except ValueError:
                    rel = Path(parts[0]).name
                lines.append(f"- **{rel}**:{parts[1]}  {parts[2].strip()[:100]}")
        self.query_one("#view", Markdown).update(
            f"# 検索: {query}\n\n" + "\n".join(lines)
        )

    def _grep(self, query: str) -> str:
        hits = []
        q = query.lower()
        for md in VAULT.rglob("*.md"):
            try:
                for i, line in enumerate(
                    md.read_text(encoding="utf-8", errors="ignore").splitlines(), 1
                ):
                    if q in line.lower():
                        hits.append(f"{md}:{i}:{line}")
                        if len(hits) >= 60:
                            return "\n".join(hits)
            except OSError:
                continue
        return "\n".join(hits)

    def action_reload(self) -> None:
        self.query_one("#tree", VaultTree).reload()
        if self.current and self.current.is_file():
            self.open_note(self.current)
        self.notify("読み直しました")


def shquote(s: str) -> str:
    import shlex
    return shlex.quote(s)


def main() -> None:
    ChibitaruTUI().run()


if __name__ == "__main__":
    main()
