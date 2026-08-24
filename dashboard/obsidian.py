#!/usr/bin/env python3
"""
🖥 ちびたるダッシュボード - obsidian.py
==========================================
見たニュースを Obsidian Vault に記録する。

作るノート:
  Dashboard/Daily/2026-08-24.md   … その日の記録（日付・見出し・ソース元・リンク）
  Dashboard/Sources/NHK.md        … ソース元ノート
  Dashboard/Topics/AI.md          … トピックノート

日付ノート ⇄ ソース元ノート ⇄ トピックノート を [[ウィキリンク]] で結ぶので、
グラフビューで「この日 → この媒体 → このテーマ」と辿れる。

同じ記事は二度書かない（seen.json でURLを覚えておく）。
"""

import json
import re
import datetime as dt
from pathlib import Path

from config import CONFIG
from fetch import now_jst, to_jst

VAULT   = Path(CONFIG["vault"])
OB      = CONFIG["obsidian"]
ROOT    = VAULT / OB["folder"]
DAILY   = ROOT / "Daily"
SOURCES = ROOT / "Sources"
TOPICS  = ROOT / "Topics"

SEEN_PATH = Path(CONFIG["cache_dir"]) / "seen.json"
SEEN_KEEP = 4000   # 覚えておくURLの上限

# カテゴリID → 日本語見出しとトピック名
CATEGORY_META = {
    "alert":    ("🚨 アラート",      ["アラート"]),
    "conflict": ("🚨 紛争アラート",  ["紛争", "国際情勢"]),
    "quake":    ("🌏 地震アラート",  ["地震", "防災"]),
    "japan":    ("🇯🇵 日本のニュース", ["日本"]),
    "world":    ("🌐 世界のニュース", ["国際"]),
    "miyazaki": ("🏞 宮崎県のニュース", ["宮崎県", "地域"]),
    "ai":       ("🤖 AI",            ["AI", "テクノロジー"]),
    "tech":     ("💡 テック",        ["テクノロジー"]),
    "gadget":   ("📱 ガジェット",    ["ガジェット", "テクノロジー"]),
    "pc":       ("💻 コンピューター", ["PC", "テクノロジー"]),
}

_BAD = re.compile(r'[\\/:*?"<>|\[\]#^]')


def safe_name(s: str, limit: int = 60) -> str:
    """Obsidianのファイル名に使えない文字を落とす。"""
    s = _BAD.sub("", (s or "").strip())
    s = re.sub(r"\s+", " ", s)
    return (s[:limit] or "不明").strip(". ")


# ─────────────────────────────────────────────
#  既読管理
# ─────────────────────────────────────────────

def _load_seen() -> dict:
    if SEEN_PATH.exists():
        try:
            return json.loads(SEEN_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_seen(seen: dict):
    if len(seen) > SEEN_KEEP:   # 古いものから捨てる
        seen = dict(sorted(seen.items(), key=lambda kv: kv[1])[-SEEN_KEEP:])
    SEEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    SEEN_PATH.write_text(json.dumps(seen, ensure_ascii=False), encoding="utf-8")


def _url_key(item: dict) -> str:
    return (item.get("link") or item.get("title") or "").split("?")[0]


# ─────────────────────────────────────────────
#  ノート生成
# ─────────────────────────────────────────────

def _ensure_stub(path: Path, title: str, kind: str, extra_links: list[str] = None):
    """ソース元・トピックのノートが無ければ作る（あれば触らない）。"""
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    links = "\n".join(f"- [[{l}]]" for l in (extra_links or []))
    path.write_text(
        f"---\ntype: {kind}\ntags: [dashboard, {kind}]\n---\n"
        f"# {title}\n\n"
        f"> ちびたるダッシュボードが自動で作ったノート。\n"
        f"> ここに集まるバックリンクから、この{'媒体' if kind == 'source' else 'テーマ'}の記事を辿れる。\n\n"
        f"{links}\n",
        encoding="utf-8",
    )


def _daily_path(day: dt.date) -> Path:
    return DAILY / f"{day.isoformat()}.md"


def _init_daily(day: dt.date) -> Path:
    """その日の記録ノートを用意する。"""
    path = _daily_path(day)
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    wd = "月火水木金土日"[day.weekday()]
    path.write_text(
        f"---\ndate: {day.isoformat()}\ntype: dashboard-daily\n"
        f"tags: [dashboard, daily]\n---\n"
        f"# 📅 {day.year}年{day.month}月{day.day}日（{wd}）のニュース記録\n\n"
        f"> 🖥 ちびたるダッシュボードの自動記録。見出し・ソース元・リンクを残している。\n\n",
        encoding="utf-8",
    )
    return path


def _section(text: str, heading: str) -> bool:
    return f"\n## {heading}\n" in text or text.startswith(f"## {heading}\n")


def _format_item(item: dict, category: str) -> str:
    """1記事を1ブロックのMarkdownにする。"""
    t = to_jst(item.get("published")) or now_jst()
    hhmm = t.strftime("%H:%M")
    title = (item.get("title") or "無題").replace("\n", " ").strip()
    src = safe_name(item.get("source") or item.get("feed") or "不明", 40)
    _, topics = CATEGORY_META.get(category, ("", []))
    topic_links = " ".join(f"[[{safe_name(tp, 30)}]]" for tp in topics)
    link = item.get("link") or ""

    lines = [f"### {hhmm} {title}"]
    lines.append(f"- 🏷 ソース元: [[{src}]] ／ トピック: {topic_links}")
    if link:
        lines.append(f"- 🔗 [記事を開く]({link})")
    if item.get("summary"):
        lines.append(f"- 📝 {item['summary'][:180]}")
    if item.get("shindo"):     # 地震
        lines.append(f"- 🌏 最大震度 **{item['shindo']}** ／ {item.get('place', '')} ／ M{item.get('mag', '―')}")
    lines.append("")
    return "\n".join(lines)


def record(payload: dict) -> dict:
    """
    ダッシュボードの中身をVaultに追記する。
    payload は server 側が作る {"news": {...}, "alerts": {...}} の形。
    """
    if not OB.get("enabled"):
        return {"written": 0, "skipped": 0, "note": "obsidian無効"}
    if not VAULT.exists():
        return {"written": 0, "skipped": 0,
                "error": f"Vaultが見つからない: {VAULT}（CHIBITARU_VAULT を設定してください）"}

    seen = _load_seen()
    now  = now_jst()
    today = now.date()
    path = _init_daily(today)
    text = path.read_text(encoding="utf-8")

    written, skipped = 0, 0
    used_sources, used_topics = set(), set()
    wanted = set(OB.get("log_categories", []))

    # カテゴリごとに、その日のノートの該当セクションへ追記していく
    buckets: list[tuple[str, list[dict]]] = []

    alerts = payload.get("alerts", {})
    if "alert" in wanted or "conflict" in wanted:
        conf = alerts.get("conflict", {}).get("items", [])
        if conf:
            buckets.append(("conflict", conf))
        qs = alerts.get("quake", {})
        quake_items = []
        for q in qs.get("japan", []):
            quake_items.append({
                "title":   f'最大震度{q["shindo"]} {q["place"]} M{q["mag"]}',
                "link":    q.get("link", ""),
                "source":  "気象庁",
                "published": q.get("time"),
                "shindo":  q.get("shindo"), "place": q.get("place"), "mag": q.get("mag"),
            })
        for q in qs.get("world", []):
            quake_items.append({
                "title":   f'M{q["mag"]} {q["place"]}',
                "link":    q.get("link", ""),
                "source":  "USGS",
                "published": q.get("time"),
            })
        if quake_items:
            buckets.append(("quake", quake_items))

    for cat, block in payload.get("news", {}).items():
        if cat in wanted:
            buckets.append((cat, block.get("items", [])))

    for cat, items in buckets:
        heading, topics = CATEGORY_META.get(cat, (cat, [cat]))
        new_blocks = []
        for it in items:
            key = _url_key(it)
            if not key or key in seen:
                skipped += 1
                continue
            seen[key] = now.timestamp()
            new_blocks.append(_format_item(it, cat))
            used_sources.add(safe_name(it.get("source") or it.get("feed") or "不明", 40))
            used_topics.update(safe_name(tp, 30) for tp in topics)
            written += 1

        if not new_blocks:
            continue

        body = "".join(new_blocks)
        if _section(text, heading):
            # 既にある見出しの直後に差し込む
            marker = f"## {heading}\n"
            idx = text.index(marker) + len(marker)
            text = text[:idx] + "\n" + body + text[idx:]
        else:
            text = text.rstrip() + f"\n\n## {heading}\n\n" + body

    if written:
        path.write_text(text, encoding="utf-8")
        # ソース元・トピックのノートを用意（グラフの結び目になる）
        for s in used_sources:
            _ensure_stub(SOURCES / f"{s}.md", s, "source")
        for tp in used_topics:
            _ensure_stub(TOPICS / f"{tp}.md", tp, "topic")
        _save_seen(seen)

    return {
        "written": written,
        "skipped": skipped,
        "daily":   str(path),
        "sources": sorted(used_sources),
        "topics":  sorted(used_topics),
    }
