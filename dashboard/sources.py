#!/usr/bin/env python3
"""
🖥 ちびたるダッシュボード - sources.py
==========================================
情報源の一覧。全部「APIキー不要・無料」のものだけ。

・公的機関（気象庁 / USGS / 国連）の公開JSON・RSS
・各媒体が自分で配っている公開RSS
・任意テーマは Googleニュース RSS（キーワード検索フィード）

feeds の形: (表示名, URL)
先頭のものほど信頼して並べる、といった重み付けはしていない（時刻順に並べる）。
"""

import urllib.parse

# ── 気象庁（無料・キー不要）──────────────────
JMA_FORECAST  = "https://www.jma.go.jp/bosai/forecast/data/forecast/{area}.json"
JMA_OVERVIEW  = "https://www.jma.go.jp/bosai/forecast/data/overview_forecast/{area}.json"
JMA_QUAKE     = "https://www.jma.go.jp/bosai/quake/data/list.json"
JMA_WARNING   = "https://www.jma.go.jp/bosai/warning/data/warning/{area}.json"

# ── 地震（海外）USGS 無料 ────────────────────
USGS_QUAKE    = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_day.geojson"

# ── 為替（無料・キー不要）────────────────────
# open.er-api.com が本命、駄目なら frankfurter（ECB公表値）に落とす
FX_PRIMARY    = "https://open.er-api.com/v6/latest/{base}"
FX_FALLBACK   = "https://api.frankfurter.app/latest?from={base}"


def google_news(query: str, lang="ja", country="JP") -> str:
    """Googleニュースの検索RSS。キーワードで拾えるので地方・専門ネタに強い。"""
    q = urllib.parse.quote(query)
    return f"https://news.google.com/rss/search?q={q}&hl={lang}&gl={country}&ceid={country}:{lang}"


# ─────────────────────────────────────────────
#  ニュース分類ごとのフィード
#  キーはフロント側のタブIDと一致させる
# ─────────────────────────────────────────────

FEEDS: dict[str, list[tuple[str, str]]] = {

    # ── 日本のニュース ───────────────────────
    "japan": [
        ("NHK",            "https://www.nhk.or.jp/rss/news/cat0.xml"),
        ("Yahoo!トピックス", "https://news.yahoo.co.jp/rss/topics/top-picks.xml"),
        ("Yahoo!国内",      "https://news.yahoo.co.jp/rss/topics/domestic.xml"),
        ("NHK 政治",        "https://www.nhk.or.jp/rss/news/cat4.xml"),
        ("NHK 経済",        "https://www.nhk.or.jp/rss/news/cat5.xml"),
    ],

    # ── 世界のニュース ───────────────────────
    "world": [
        ("Yahoo!国際",      "https://news.yahoo.co.jp/rss/topics/world.xml"),
        ("NHK 国際",        "https://www.nhk.or.jp/rss/news/cat6.xml"),
        ("BBC World",      "https://feeds.bbci.co.uk/news/world/rss.xml"),
        ("Al Jazeera",     "https://www.aljazeera.com/xml/rss/all.xml"),
        ("UN News",        "https://news.un.org/feed/subscribe/en/news/all/rss.xml"),
        ("France24",       "https://www.france24.com/en/rss"),
    ],

    # ── 宮崎県のニュース ─────────────────────
    "miyazaki": [
        ("Google:宮崎県",   google_news("宮崎県 OR 宮崎市 when:3d")),
        ("Google:宮崎防災",  google_news("宮崎県 (地震 OR 台風 OR 大雨 OR 避難) when:3d")),
        ("宮崎日日新聞",     google_news("site:the-miyanichi.co.jp when:7d")),
        ("UMKテレビ宮崎",    google_news("site:umk.co.jp OR site:mrt.jp when:7d")),
    ],

    # ── AI ───────────────────────────────────
    "ai": [
        ("ITmedia AI+",    "https://rss.itmedia.co.jp/rss/2.0/aiplus.xml"),
        ("Google:AI",      google_news("AI OR 生成AI OR LLM when:2d")),
        ("Ars Technica AI", "https://arstechnica.com/ai/feed/"),
        ("Google:AI(EN)",  google_news("artificial intelligence OR LLM when:2d", lang="en", country="US")),
    ],

    # ── テック全般 ───────────────────────────
    "tech": [
        ("GIGAZINE",       "https://gigazine.net/news/rss_2.0/"),
        ("ITmedia NEWS",   "https://rss.itmedia.co.jp/rss/2.0/news_bursts.xml"),
        ("Publickey",      "https://www.publickey1.jp/atom.xml"),
        ("Hacker News",    "https://hnrss.org/frontpage?points=100"),
        ("The Verge",      "https://www.theverge.com/rss/index.xml"),
    ],

    # ── ガジェット ───────────────────────────
    "gadget": [
        ("ケータイ Watch",  "https://k-tai.watch.impress.co.jp/data/rss/1.0/ktw/feed.rdf"),
        ("家電 Watch",      "https://kaden.watch.impress.co.jp/data/rss/1.0/kdw/feed.rdf"),
        ("Engadget",       "https://www.engadget.com/rss.xml"),
        ("Google:ガジェット", google_news("ガジェット OR スマートフォン新製品 when:3d")),
    ],

    # ── コンピューター / PC ──────────────────
    "pc": [
        ("PC Watch",       "https://pc.watch.impress.co.jp/data/rss/1.0/pcw/feed.rdf"),
        ("窓の杜",          "https://forest.watch.impress.co.jp/data/rss/1.0/wf/feed.rdf"),
        ("クラウド Watch",  "https://cloud.watch.impress.co.jp/data/rss/1.0/clw/feed.rdf"),
        ("Google:自作PC",   google_news("自作PC OR CPU OR GPU OR Windows11 when:3d")),
    ],
}

# ── 紛争・災害アラート用（赤帯）──────────────
CONFLICT_FEEDS: list[tuple[str, str]] = [
    ("UN 平和と安全", "https://news.un.org/feed/subscribe/en/news/topic/peace-and-security/feed/rss.xml"),
    ("GDACS 災害警報", "https://www.gdacs.org/xml/rss.xml"),
    ("Al Jazeera",   "https://www.aljazeera.com/xml/rss/all.xml"),
    ("BBC World",    "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("Google:紛争",   google_news("紛争 OR 停戦 OR 空爆 OR 侵攻 when:2d")),
    ("Google:安保",   google_news("日本 (領空侵犯 OR 弾道ミサイル OR 防衛出動 OR 有事) when:2d")),
]

# 紛争アラートの拾い上げキーワード（重み付き）
CONFLICT_KEYWORDS: dict[str, int] = {
    # 日本語
    "紛争": 5, "戦争": 5, "侵攻": 5, "空爆": 5, "砲撃": 4, "戦闘": 4,
    "ミサイル": 4, "弾道ミサイル": 5, "停戦": 3, "休戦": 3, "軍事": 2,
    "交戦": 4, "テロ": 4, "爆発": 3, "領空侵犯": 4, "有事": 3, "動員": 2,
    "制裁": 2, "避難命令": 3, "死者": 2, "武力": 3, "衝突": 3,
    # 英語
    "war": 5, "invasion": 5, "airstrike": 5, "air strike": 5, "missile": 4,
    "ceasefire": 3, "conflict": 4, "offensive": 3, "attack": 3, "strike": 2,
    "troops": 3, "military": 2, "shelling": 4, "casualties": 3, "killed": 2,
    "escalation": 3, "drone": 2, "terror": 4, "coup": 4, "hostilities": 4,
}

# 誤検知しやすい語（スコアを下げる）
CONFLICT_NEGATIVE: dict[str, int] = {
    "スト": 2, "ゲーム": 4, "映画": 4, "ドラマ": 4, "アニメ": 4, "野球": 4,
    "サッカー": 4, "game": 4, "movie": 4, "film": 4, "trailer": 4, "sport": 4,
    "レビュー": 3, "review": 3, "セール": 3, "sale": 3,
}
