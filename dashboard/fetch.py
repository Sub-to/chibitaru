#!/usr/bin/env python3
"""
🖥 ちびたるダッシュボード - fetch.py
==========================================
取得まわりの土台。標準ライブラリのみ（pip install 不要）。

・HTTPキャッシュ（ETag / Last-Modified による条件付きGET）
  → 変わっていなければ304が返るので通信量もサーバー負荷も最小限
・RSS 2.0 / RSS 1.0(RDF) / Atom をまとめて解析
"""

import gzip
import json
import time
import hashlib
import html as html_mod
import re
import urllib.request
import urllib.error
import datetime as dt
from email.utils import parsedate_to_datetime
from pathlib import Path
from xml.etree import ElementTree as ET

from config import CONFIG

JST = dt.timezone(dt.timedelta(hours=9), "JST")

CACHE_DIR = Path(CONFIG["cache_dir"])
HTTP_DIR  = CACHE_DIR / "http"


def _ensure_dirs():
    HTTP_DIR.mkdir(parents=True, exist_ok=True)


def _key(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]


# ─────────────────────────────────────────────
#  HTTP
# ─────────────────────────────────────────────

class FetchError(Exception):
    """取得に失敗したときの例外（呼び出し側で握りつぶして使う）。"""


def http_get(url: str, ttl: int = 300, timeout: int | None = None) -> bytes:
    """
    URLを取得する。ttl秒以内に取ったものが残っていればそれを返す。
    期限切れなら ETag / Last-Modified を付けて問い合わせ、
    304 Not Modified ならキャッシュ本体を使い回す。
    """
    _ensure_dirs()
    timeout = timeout or CONFIG["http"]["timeout"]
    k = _key(url)
    body_path = HTTP_DIR / f"{k}.body"
    meta_path = HTTP_DIR / f"{k}.meta.json"

    meta = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}

    fresh = (time.time() - meta.get("fetched_at", 0)) < ttl
    if fresh and body_path.exists():
        return body_path.read_bytes()

    req = urllib.request.Request(url, headers={
        "User-Agent":      CONFIG["http"]["user_agent"],
        "Accept-Encoding": "gzip",
        "Accept":          "application/json, application/rss+xml, application/xml, text/xml, */*",
    })
    if meta.get("etag"):
        req.add_header("If-None-Match", meta["etag"])
    if meta.get("last_modified"):
        req.add_header("If-Modified-Since", meta["last_modified"])

    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            raw = res.read()
            if res.headers.get("Content-Encoding", "").lower() == "gzip":
                raw = gzip.decompress(raw)
            body_path.write_bytes(raw)
            meta_path.write_text(json.dumps({
                "url":           url,
                "fetched_at":    time.time(),
                "etag":          res.headers.get("ETag"),
                "last_modified": res.headers.get("Last-Modified"),
                "status":        res.status,
            }, ensure_ascii=False), encoding="utf-8")
            return raw

    except urllib.error.HTTPError as e:
        if e.code == 304 and body_path.exists():
            meta["fetched_at"] = time.time()
            meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
            return body_path.read_bytes()
        # 落ちているときは古くてもキャッシュで凌ぐ
        if body_path.exists():
            return body_path.read_bytes()
        raise FetchError(f"HTTP {e.code} {url}") from e

    except Exception as e:
        if body_path.exists():
            return body_path.read_bytes()
        raise FetchError(f"{type(e).__name__}: {e} ({url})") from e


def get_json(url: str, ttl: int = 300):
    """JSONを取得する。"""
    return json.loads(http_get(url, ttl=ttl).decode("utf-8", "replace"))


# ─────────────────────────────────────────────
#  日時
# ─────────────────────────────────────────────

def to_jst(value) -> dt.datetime | None:
    """RFC822 / ISO8601 / epoch を日本時間の datetime に揃える。"""
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)):
            return dt.datetime.fromtimestamp(value, tz=JST)

        s = str(value).strip()

        # ISO 8601（Atom, 気象庁JSONなど）
        iso = s.replace("Z", "+00:00")
        try:
            d = dt.datetime.fromisoformat(iso)
            if d.tzinfo is None:
                d = d.replace(tzinfo=JST)   # 気象庁などTZ無し表記は日本時間とみなす
            return d.astimezone(JST)
        except ValueError:
            pass

        # RFC 822（RSS の pubDate）
        d = parsedate_to_datetime(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return d.astimezone(JST)
    except Exception:
        return None


def now_jst() -> dt.datetime:
    return dt.datetime.now(JST)


def iso(d: dt.datetime | None) -> str | None:
    return d.isoformat() if d else None


# ─────────────────────────────────────────────
#  フィード解析
# ─────────────────────────────────────────────

_TAG_RE   = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")


def clean_text(s: str | None, limit: int = 300) -> str:
    """HTMLタグと余分な空白を落として読める文にする。"""
    if not s:
        return ""
    s = _TAG_RE.sub(" ", s)
    s = html_mod.unescape(s)
    s = _SPACE_RE.sub(" ", s).strip()
    return s[:limit]


def _local(tag: str) -> str:
    """{namespace}tag → tag"""
    return tag.rsplit("}", 1)[-1].lower()


def _first(el, *names):
    """子要素を名前（名前空間無視）で探して最初の文字列を返す。"""
    for name in names:
        for child in el:
            if _local(child.tag) == name:
                if child.text and child.text.strip():
                    return child.text.strip()
        # Atom の <link href="..."> のように属性に入っている場合
        for child in el:
            if _local(child.tag) == name and child.get("href"):
                return child.get("href")
    return None


def _atom_link(el) -> str | None:
    """Atom の link を選ぶ（rel=alternate 優先）。"""
    fallback = None
    for child in el:
        if _local(child.tag) != "link":
            continue
        href = child.get("href")
        if not href:
            continue
        rel = (child.get("rel") or "alternate").lower()
        if rel == "alternate":
            return href
        fallback = fallback or href
    return fallback


def parse_feed(raw: bytes, source_name: str = "") -> list[dict]:
    """
    RSS 2.0 / RSS 1.0(RDF) / Atom を共通の形に潰す。
    返り値: [{title, link, published(iso), summary, source}, ...]
    """
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        # 先頭にゴミが付いている配信があるので、最初の < から読み直す
        try:
            txt = raw.decode("utf-8", "replace")
            root = ET.fromstring(txt[txt.index("<"):])
        except Exception as e:
            raise FetchError(f"XML解析に失敗: {e}")

    items: list[dict] = []
    root_name = _local(root.tag)

    if root_name == "feed":                       # Atom
        entries = [c for c in root if _local(c.tag) == "entry"]
        for e in entries:
            items.append({
                "title":     clean_text(_first(e, "title"), 200),
                "link":      _atom_link(e) or _first(e, "id") or "",
                "published": _first(e, "published", "updated"),
                "summary":   clean_text(_first(e, "summary", "content"), 240),
            })
    else:                                          # RSS 2.0 / RDF
        channel = None
        for c in root:
            if _local(c.tag) == "channel":
                channel = c
                break
        holder = channel if channel is not None else root
        entries = [c for c in holder if _local(c.tag) == "item"]
        if not entries:  # RDF は item が channel の外に並ぶ
            entries = [c for c in root if _local(c.tag) == "item"]
        for e in entries:
            items.append({
                "title":     clean_text(_first(e, "title"), 200),
                "link":      (_first(e, "link", "guid") or "").strip(),
                "published": _first(e, "pubdate", "date", "updated", "issued"),
                "summary":   clean_text(_first(e, "description", "summary", "encoded"), 240),
            })

    out = []
    for it in items:
        if not it["title"] or not it["link"]:
            continue
        d = to_jst(it["published"])
        title, src = _split_google_suffix(it["title"], source_name)
        out.append({
            "title":     title,
            "link":      it["link"],
            "published": iso(d),
            "ts":        d.timestamp() if d else 0,
            "summary":   it["summary"],
            "source":    src,
        })
    return out


def _split_google_suffix(title: str, source_name: str) -> tuple[str, str]:
    """
    Googleニュースの見出しは「本文 - 媒体名」形式なので、媒体名を分離する。
    それ以外はフィード名をそのままソース元にする。
    """
    if source_name.startswith("Google:") and " - " in title:
        head, _, tail = title.rpartition(" - ")
        if head and len(tail) <= 30:
            return head.strip(), tail.strip()
    return title, source_name


def dedupe(items: list[dict]) -> list[dict]:
    """同じ記事（URL or 見出し）を1件にまとめる。"""
    seen, out = set(), []
    for it in items:
        link = (it.get("link") or "").split("?")[0]
        key = link or it.get("title", "")
        tkey = re.sub(r"\W+", "", it.get("title", ""))[:40]
        if key in seen or (tkey and tkey in seen):
            continue
        seen.add(key)
        if tkey:
            seen.add(tkey)
        out.append(it)
    return out
