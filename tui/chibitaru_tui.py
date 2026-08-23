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
import sys
import unicodedata
from datetime import date
from pathlib import Path

# panels は同じフォルダに置いてある
sys.path.insert(0, str(Path(__file__).resolve().parent))

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from panels import Mixer, MusicBar, NewsTicker, TopBar  # noqa: E402
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
        Binding("q", "confirm_quit", "終了"),
        Binding("space", "music_toggle", "再生/停止", show=False),
        Binding("ctrl+q", "power_off", "電源"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.current: Path | None = None
        self.tier = TIER          # 計器類が参照する

    def compose(self) -> ComposeResult:
        yield NewsTicker(id="news")
        yield TopBar()
        yield Input(placeholder="Vault を検索（Enter で実行、Esc で閉じる）", id="search")
        with Horizontal(id="body"):
            # 左の列が操作盤。上から順に、見る・たどる・調整する・鳴らす。
            with Vertical(id="left"):
                yield VaultTree(str(VAULT), id="tree")
                with Vertical(id="backlinks"):
                    yield Label("ここへのリンク", id="backlinks-title")
                    yield ListView(id="backlist")
                yield Mixer(id="mixer")
                yield MusicBar(id="music")
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

    def action_music_toggle(self) -> None:
        """再生と一時停止を入れ替える。ツリー操作の邪魔にならないよう
        Space はフッタに出さない。"""
        from panels import mpc
        mpc("toggle")
        self.query_one("#music", MusicBar).tick()

    def action_power_off(self) -> None:
        """
        電源を切る。二度押しにする。

        q と同じ理由で、ひと押しで到達してよい操作ではない。
        """
        if getattr(self, "_power_armed", False):
            subprocess.run(["systemctl", "poweroff"], check=False)
            return
        self._power_armed = True
        self.notify("もう一度 Ctrl+Q で電源を切ります", severity="warning",
                    timeout=5)
        self.set_timer(5.0, lambda: setattr(self, "_power_armed", False))

    def action_confirm_quit(self) -> None:
        """
        一度で終わらせない。

        この画面は Vault そのもので、消えると何も出ない黒い画面が残る。
        実機で q を押して画面が消え、戻し方が分からなくなった。
        キーひとつで到達できてよい状態ではない。
        """
        if getattr(self, "_quit_armed", False):
            self.exit()
            return
        self._quit_armed = True
        self.notify("もう一度 q で終了します（他のキーで取り消し）",
                    timeout=4)
        self.set_timer(4.0, self._disarm_quit)

    def _disarm_quit(self) -> None:
        self._quit_armed = False

    def on_key(self, event) -> None:
        # q 以外を押したら終了の構えを解く
        if getattr(self, "_quit_armed", False) and event.key != "q":
            self._quit_armed = False

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
