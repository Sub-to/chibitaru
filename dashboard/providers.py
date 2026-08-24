#!/usr/bin/env python3
"""
🖥 ちびたるダッシュボード - providers.py
==========================================
各パネルに出すデータを作るところ。

天気     : 気象庁（予報・週間）＋ Open-Meteo（今の気温）
地震     : 気象庁 震度リスト（震度3以上）＋ USGS（海外M6.0以上）
紛争     : 国連・GDACS・各国報道のRSSをキーワードで採点して抽出
ニュース : 各カテゴリのRSSを時刻順にまとめる
為替     : ドル / 円 / ユーロ

どれも失敗したら error を入れて返すだけで、他のパネルは巻き込まない。
"""

import datetime as dt
from concurrent.futures import ThreadPoolExecutor

import sources
from config import CONFIG
from fetch import (http_get, get_json, parse_feed, dedupe, to_jst,
                   now_jst, iso, FetchError, JST)

LOC    = CONFIG["location"]
LIMITS = CONFIG["limits"]
ALERTS = CONFIG["alerts"]
IVL    = CONFIG["intervals"]


# ─────────────────────────────────────────────
#  天気
# ─────────────────────────────────────────────

# 気象庁天気コード → ざっくり絵文字（先頭1桁で判定、特殊なものだけ個別）
def _jma_icon(code: str) -> str:
    if not code:
        return "🌡"
    c = str(code)
    special = {"100": "☀️", "101": "🌤", "200": "☁️", "201": "⛅️",
               "300": "🌧", "400": "❄️", "402": "🌨"}
    if c in special:
        return special[c]
    head = c[0]
    return {"1": "☀️", "2": "☁️", "3": "🌧", "4": "❄️"}.get(head, "🌡")


# Open-Meteo(WMO)コード → 日本語＋絵文字
_WMO = {
    0: ("快晴", "☀️"), 1: ("晴れ", "🌤"), 2: ("薄曇り", "⛅️"), 3: ("曇り", "☁️"),
    45: ("霧", "🌫"), 48: ("霧氷", "🌫"),
    51: ("霧雨", "🌦"), 53: ("霧雨", "🌦"), 55: ("霧雨", "🌦"),
    61: ("小雨", "🌧"), 63: ("雨", "🌧"), 65: ("強い雨", "🌧"),
    71: ("小雪", "🌨"), 73: ("雪", "🌨"), 75: ("大雪", "❄️"),
    80: ("にわか雨", "🌦"), 81: ("にわか雨", "🌦"), 82: ("激しい雨", "⛈"),
    95: ("雷雨", "⛈"), 96: ("雷雨", "⛈"), 99: ("激しい雷雨", "⛈"),
}


def _pick_area(areas: list, want_code: str, want_name: str):
    """予報の細分区域から宮崎市を含むものを選ぶ。見つからなければ先頭。"""
    for a in areas:
        if a.get("area", {}).get("code") == want_code:
            return a
    for a in areas:
        if want_name in a.get("area", {}).get("name", ""):
            return a
    return areas[0] if areas else None


def weather() -> dict:
    """宮崎市の天気（今の気温＋今日明日＋週間）。"""
    out = {
        "place": f'{LOC["pref"]}{LOC["name"]}',
        "current": None, "today": None, "weekly": [],
        "overview": None, "errors": [],
    }

    # ① 気象庁の予報
    try:
        data = get_json(sources.JMA_FORECAST.format(area=LOC["jma_area"]),
                        ttl=IVL["weather"])
        near = data[0]
        out["updated"] = iso(to_jst(near.get("reportDatetime")))
        out["office"]  = near.get("publishingOffice", "気象庁")

        ts = near.get("timeSeries", [])
        # 天気
        if len(ts) > 0:
            a = _pick_area(ts[0].get("areas", []), LOC["jma_class10"], "南部平野部")
            if a:
                defines = ts[0].get("timeDefines", [])
                days = []
                for i, w in enumerate(a.get("weathers", [])[:3]):
                    d = to_jst(defines[i]) if i < len(defines) else None
                    days.append({
                        "date":    iso(d),
                        "label":   ["今日", "明日", "明後日"][i] if i < 3 else "",
                        "weather": " ".join(w.split()),
                        "icon":    _jma_icon((a.get("weatherCodes") or [""] * 3)[i]),
                        "wind":    (a.get("winds") or [""] * 3)[i] if i < len(a.get("winds", [])) else "",
                    })
                out["today"] = days[0] if days else None
                out["days"] = days
        # 降水確率
        if len(ts) > 1:
            a = _pick_area(ts[1].get("areas", []), LOC["jma_class10"], "南部平野部")
            if a:
                out["pops"] = [
                    {"time": iso(to_jst(t)), "pop": p}
                    for t, p in zip(ts[1].get("timeDefines", []), a.get("pops", []))
                ][:8]
        # 気温
        if len(ts) > 2:
            a = _pick_area(ts[2].get("areas", []), "", LOC["name"][:2])
            if a:
                temps = [t for t in a.get("temps", []) if t not in ("", None)]
                if temps:
                    out["today_temp"] = {"min": temps[0], "max": temps[-1]}

        # 週間予報（配列の2番目）
        if len(data) > 1:
            wts = data[1].get("timeSeries", [])
            wdays, tmin, tmax = [], [], []
            if wts:
                a = _pick_area(wts[0].get("areas", []), "", LOC["pref"][:2])
                defines = wts[0].get("timeDefines", [])
                codes = a.get("weatherCodes", []) if a else []
                pops  = a.get("pops", []) if a else []
                if len(wts) > 1:
                    b = _pick_area(wts[1].get("areas", []), "", LOC["name"][:2])
                    tmin = b.get("tempsMin", []) if b else []
                    tmax = b.get("tempsMax", []) if b else []
                for i, t in enumerate(defines[:7]):
                    d = to_jst(t)
                    wdays.append({
                        "date": iso(d),
                        "wday": "月火水木金土日"[d.weekday()] if d else "",
                        "md":   f"{d.month}/{d.day}" if d else "",
                        "icon": _jma_icon(codes[i] if i < len(codes) else ""),
                        "pop":  pops[i] if i < len(pops) else "",
                        "min":  tmin[i] if i < len(tmin) else "",
                        "max":  tmax[i] if i < len(tmax) else "",
                    })
            out["weekly"] = wdays
    except Exception as e:
        out["errors"].append(f"気象庁予報: {e}")

    # ② 気象庁の概況テキスト
    try:
        ov = get_json(sources.JMA_OVERVIEW.format(area=LOC["jma_area"]),
                      ttl=IVL["weather"])
        out["overview"] = (ov.get("text") or "").strip()
    except Exception as e:
        out["errors"].append(f"気象庁概況: {e}")

    # ③ Open-Meteo（今この瞬間の気温・湿度・風）
    try:
        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={LOC['lat']}&longitude={LOC['lon']}"
            "&current=temperature_2m,relative_humidity_2m,apparent_temperature,"
            "precipitation,weather_code,wind_speed_10m"
            "&daily=sunrise,sunset,uv_index_max"
            f"&timezone={LOC['timezone'].replace('/', '%2F')}&forecast_days=1"
        )
        om = get_json(url, ttl=600)
        cur = om.get("current", {})
        label, icon = _WMO.get(int(cur.get("weather_code", -1)), ("―", "🌡"))
        daily = om.get("daily", {})
        out["current"] = {
            "temp":      cur.get("temperature_2m"),
            "feels":     cur.get("apparent_temperature"),
            "humidity":  cur.get("relative_humidity_2m"),
            "wind":      cur.get("wind_speed_10m"),
            "precip":    cur.get("precipitation"),
            "label":     label,
            "icon":      icon,
            "sunrise":   (daily.get("sunrise") or [None])[0],
            "sunset":    (daily.get("sunset") or [None])[0],
            "uv":        (daily.get("uv_index_max") or [None])[0],
            "observed":  cur.get("time"),
        }
    except Exception as e:
        out["errors"].append(f"Open-Meteo: {e}")

    return out


# ─────────────────────────────────────────────
#  地震
# ─────────────────────────────────────────────

# 震度表記を数値に（比較用）。"5-"=5.0 / "5+"=5.5 のように扱う。
_SHINDO = {"1": 1.0, "2": 2.0, "3": 3.0, "4": 4.0,
           "5-": 5.0, "5+": 5.5, "6-": 6.0, "6+": 6.5, "7": 7.0}


def shindo_value(s: str | None) -> float:
    if not s:
        return 0.0
    s = str(s).strip()
    if s in _SHINDO:
        return _SHINDO[s]
    # "50" = 5弱 / "55" = 5強 という表記のAPIもある
    table = {"50": 5.0, "55": 5.5, "60": 6.0, "65": 6.5, "70": 7.0}
    if s in table:
        return table[s]
    try:
        return float(s)
    except ValueError:
        return 0.0


def shindo_label(s: str | None) -> str:
    v = shindo_value(s)
    return {5.0: "5弱", 5.5: "5強", 6.0: "6弱", 6.5: "6強"}.get(v, str(s or "―"))


def quakes() -> dict:
    """気象庁の震度リストから、しきい値以上の地震だけ拾う。"""
    out = {"japan": [], "world": [], "errors": [], "threshold": ALERTS["min_shindo"]}
    cutoff = now_jst() - dt.timedelta(hours=ALERTS["quake_hours"])

    # ① 国内（震度）
    try:
        data = get_json(sources.JMA_QUAKE, ttl=IVL["quake"])
        seen = set()
        for e in data:
            maxi = e.get("maxi")
            val  = shindo_value(maxi)
            if val < ALERTS["min_shindo"]:
                continue
            at = to_jst(e.get("at") or e.get("rdt"))
            if at and at < cutoff:
                continue
            eid = e.get("eid") or e.get("ctt")
            if eid in seen:
                continue
            seen.add(eid)
            out["japan"].append({
                "id":       eid,
                "time":     iso(at),
                "ts":       at.timestamp() if at else 0,
                "place":    e.get("anm") or "調査中",
                "mag":      e.get("mag") or "―",
                "shindo":   shindo_label(maxi),
                "shindo_v": val,
                "title":    e.get("ttl") or "震源・震度情報",
                "link":     "https://www.jma.go.jp/bosai/map.html#contents=earthquake_map",
                "source":   "気象庁",
            })
        out["japan"].sort(key=lambda x: x["ts"], reverse=True)
        out["japan"] = out["japan"][:LIMITS["alerts"]]
    except Exception as e:
        out["errors"].append(f"気象庁地震: {e}")

    # ② 海外（マグニチュード）
    try:
        gj = get_json(sources.USGS_QUAKE, ttl=IVL["quake"])
        for f in gj.get("features", []):
            p = f.get("properties", {})
            mag = p.get("mag") or 0
            if mag < ALERTS["world_quake_mag"]:
                continue
            at = to_jst((p.get("time") or 0) / 1000)
            if at and at < cutoff:
                continue
            out["world"].append({
                "time":   iso(at),
                "ts":     at.timestamp() if at else 0,
                "place":  p.get("place") or "―",
                "mag":    round(float(mag), 1),
                "link":   p.get("url") or "",
                "source": "USGS",
            })
        out["world"].sort(key=lambda x: x["ts"], reverse=True)
        out["world"] = out["world"][:6]
    except Exception as e:
        out["errors"].append(f"USGS: {e}")

    return out


# ─────────────────────────────────────────────
#  紛争アラート
# ─────────────────────────────────────────────

def _conflict_score(item: dict) -> int:
    """見出し＋要約を採点。関係なさそうな語はマイナス。"""
    text = f'{item.get("title", "")} {item.get("summary", "")}'.lower()
    score = 0
    hits = []
    for kw, w in sources.CONFLICT_KEYWORDS.items():
        if kw.lower() in text:
            score += w
            hits.append(kw)
    for kw, w in sources.CONFLICT_NEGATIVE.items():
        if kw.lower() in text:
            score -= w
    item["_hits"] = hits[:4]
    return score


def _fetch_feed(name_url: tuple[str, str], ttl: int) -> list[dict]:
    name, url = name_url
    try:
        items = parse_feed(http_get(url, ttl=ttl), name)
        for it in items:
            it.setdefault("source", name)
            it["feed"] = name
        return items[:LIMITS["per_feed"]]
    except Exception:
        return []


def _fetch_many(feeds: list[tuple[str, str]], ttl: int) -> list[dict]:
    """複数フィードを並行取得（1本詰まっても全体を止めない）。"""
    workers = min(CONFIG["http"]["max_workers"], max(1, len(feeds)))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(lambda f: _fetch_feed(f, ttl), feeds))
    return [it for group in results for it in group]


def conflicts() -> dict:
    """世界（日本含む）の紛争・重大災害アラート。"""
    items = _fetch_many(sources.CONFLICT_FEEDS, IVL["conflict"])
    cutoff = (now_jst() - dt.timedelta(hours=ALERTS["conflict_hours"])).timestamp()

    scored = []
    for it in dedupe(items):
        if it["ts"] and it["ts"] < cutoff:
            continue
        s = _conflict_score(it)
        # GDACSは元々が警報なので下駄をはかせる
        if it.get("feed", "").startswith("GDACS"):
            s += 4
        if s >= 5:
            it["score"] = s
            scored.append(it)

    scored.sort(key=lambda x: (x["score"], x["ts"]), reverse=True)
    return {"items": scored[:LIMITS["alerts"]], "count": len(scored)}


# ─────────────────────────────────────────────
#  ニュース
# ─────────────────────────────────────────────

def news(category: str) -> dict:
    """カテゴリごとのニュース（新しい順）。"""
    feeds = sources.FEEDS.get(category, [])
    items = _fetch_many(feeds, IVL["news"])
    items = dedupe(items)
    items.sort(key=lambda x: x["ts"], reverse=True)
    for it in items:
        it["category"] = category
    return {"items": items[:LIMITS["per_tab"]], "count": len(items)}


# ─────────────────────────────────────────────
#  為替
# ─────────────────────────────────────────────

def fx() -> dict:
    """ドル・円・ユーロ。無料APIなので更新は日次〜数時間おき。"""
    out = {"pairs": [], "errors": [], "source": None, "updated": None}
    rates, base = None, "USD"

    try:
        d = get_json(sources.FX_PRIMARY.format(base=base), ttl=IVL["fx"])
        if d.get("result") == "success":
            rates = d.get("rates", {})
            out["source"]  = "open.er-api.com"
            out["updated"] = iso(to_jst(d.get("time_last_update_unix")))
    except Exception as e:
        out["errors"].append(f"open.er-api: {e}")

    if not rates:
        try:
            d = get_json(sources.FX_FALLBACK.format(base=base), ttl=IVL["fx"])
            rates = d.get("rates", {})
            out["source"]  = "frankfurter.app (ECB)"
            out["updated"] = iso(to_jst(d.get("date")))
        except Exception as e:
            out["errors"].append(f"frankfurter: {e}")

    if not rates:
        return out

    def rate(frm: str, to: str) -> float | None:
        """USD基準の表から任意ペアを計算する。"""
        if frm == base:
            return rates.get(to)
        if to == base:
            r = rates.get(frm)
            return (1 / r) if r else None
        a, b = rates.get(frm), rates.get(to)
        return (b / a) if a and b else None

    for frm, to in CONFIG["fx_pairs"]:
        v = rate(frm, to)
        if v is None:
            continue
        out["pairs"].append({
            "pair":  f"{frm}/{to}",
            "from":  frm,
            "to":    to,
            "value": round(v, 4 if v < 10 else 2),
        })
    return out
