#!/usr/bin/env python3
"""
🖥 ちびたるダッシュボード - server.py
==========================================
このPC専用のダッシュボード本体。

  python3 dashboard/server.py           起動してブラウザを開く
  python3 dashboard/server.py --check   情報源が生きているか一括チェック
  python3 dashboard/server.py --once    1回だけ取得してVaultに記録（cron向き）
  python3 dashboard/server.py --port 9000

外部に何も送らない。127.0.0.1 でだけ待ち受ける。
"""

import sys
import json
import time
import argparse
import threading
import webbrowser
import datetime as dt
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

import sources                              # noqa: E402
import providers                            # noqa: E402
import obsidian                             # noqa: E402
import notify                               # noqa: E402
import sysinfo                              # noqa: E402
from config import CONFIG                   # noqa: E402
from fetch import now_jst, iso, http_get, get_json  # noqa: E402

STATIC_DIR = BASE_DIR / "static"
NEWS_CATEGORIES = list(sources.FEEDS.keys())


# ─────────────────────────────────────────────
#  データをまとめる
# ─────────────────────────────────────────────

class Store:
    """取得結果を持っておく箱。バックグラウンドで更新し、画面はここを読む。"""

    def __init__(self):
        self.lock = threading.Lock()
        self.data = {"ready": False, "generated": None,
                     "weather": {}, "alerts": {}, "news": {}, "fx": {},
                     "vault": {}, "errors": []}
        self.last_full = 0

    def snapshot(self) -> dict:
        with self.lock:
            return json.loads(json.dumps(self.data, ensure_ascii=False))

    def refresh(self, write_vault: bool = True) -> dict:
        """全部取り直す。個々の失敗は errors に積むだけで全体は止めない。"""
        started = time.time()
        errors = []

        def safe(label, fn, default):
            try:
                return fn()
            except Exception as e:
                errors.append(f"{label}: {type(e).__name__}: {e}")
                return default

        weather = safe("天気", providers.weather, {})
        quake   = safe("地震", providers.quakes, {"japan": [], "world": []})
        conf    = safe("紛争", providers.conflicts, {"items": []})
        fxdata  = safe("為替", providers.fx, {"pairs": []})

        news = {}
        for cat in NEWS_CATEGORIES:
            news[cat] = safe(f"ニュース({cat})", lambda c=cat: providers.news(c),
                             {"items": [], "count": 0})

        payload = {
            "ready":     True,
            "generated": iso(now_jst()),
            "elapsed":   round(time.time() - started, 1),
            "weather":   weather,
            "alerts":    {"conflict": conf, "quake": quake},
            "news":      news,
            "fx":        fxdata,
            "errors":    errors + weather.get("errors", []),
            "location":  CONFIG["location"],
            "config":    {
                "min_shindo":  CONFIG["alerts"]["min_shindo"],
                "vault":       CONFIG["vault"],
                "vault_on":    CONFIG["obsidian"]["enabled"],
                "light_mode":  CONFIG.get("light_mode", False),
                "ui_scale":    CONFIG.get("ui", {}).get("scale", "auto"),
            },
        }

        # 強い地震はデスクトップ通知でも知らせる（常時表示機向け）
        try:
            n = notify.notify_quakes(quake.get("japan", []),
                                     CONFIG["notify"]["min_shindo"])
            if n:
                print(f"🔔 地震通知 {n}件")
        except Exception as e:
            errors.append(f"通知: {e}")

        if write_vault:
            try:
                payload["vault"] = obsidian.record(payload)
            except Exception as e:
                payload["vault"] = {"error": f"{type(e).__name__}: {e}"}
                errors.append(f"Obsidian: {e}")

        with self.lock:
            self.data = payload
            self.last_full = time.time()
        return payload


STORE = Store()


def background_loop(store: Store, stop: threading.Event):
    """一番短い更新間隔に合わせて定期的に取り直す。"""
    tick = min(CONFIG["intervals"].values())
    while not stop.is_set():
        if stop.wait(tick):
            break
        try:
            store.refresh()
            print(f"🔄 更新 {now_jst():%H:%M:%S}")
        except Exception as e:
            print(f"⚠️  更新に失敗: {e}")


# ─────────────────────────────────────────────
#  HTTPサーバー
# ─────────────────────────────────────────────

MIME = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
        ".js": "application/javascript; charset=utf-8", ".json": "application/json",
        ".svg": "image/svg+xml", ".ico": "image/x-icon"}


class Handler(BaseHTTPRequestHandler):
    server_version = "Chibitaru/1.0"

    def log_message(self, fmt, *args):   # アクセスログは静かに
        pass

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def do_GET(self):
        path = self.path.split("?")[0]

        if path in ("/", "/index.html"):
            return self._static("index.html")

        if path.startswith("/static/"):
            return self._static(path[len("/static/"):])

        if path == "/api/all":
            snap = STORE.snapshot()
            if not snap.get("ready"):
                snap = STORE.refresh()
            return self._json(snap)

        if path == "/api/refresh":
            return self._json(STORE.refresh())

        if path == "/api/health":
            return self._json({"ok": True, "time": iso(now_jst()),
                               "last_full": STORE.last_full})

        return self._json({"error": "not found"}, 404)

    def _static(self, rel: str):
        # ディレクトリの外へ出られないようにする
        target = (STATIC_DIR / rel).resolve()
        if not str(target).startswith(str(STATIC_DIR.resolve())) or not target.is_file():
            return self._json({"error": "not found"}, 404)
        self._send(200, target.read_bytes(),
                   MIME.get(target.suffix, "application/octet-stream"))


# ─────────────────────────────────────────────
#  情報源チェック（--check）
# ─────────────────────────────────────────────

def run_check() -> int:
    """全部の情報源を1本ずつ叩いて、生きているか一覧で出す。"""
    from fetch import parse_feed
    from concurrent.futures import ThreadPoolExecutor

    print("=" * 62)
    print("🔍 情報源チェック（全部そのPCから直接つなぎます）")
    print("=" * 62)

    ok = fail = 0

    def check_feed(entry):
        name, url = entry
        try:
            items = parse_feed(http_get(url, ttl=0), name)
            return (True, name, f"{len(items)}件", url)
        except Exception as e:
            return (False, name, f"{type(e).__name__}: {str(e)[:60]}", url)

    groups: list[tuple[str, list]] = [("🚨 紛争アラート", sources.CONFLICT_FEEDS)]
    groups += [(f"📰 {c}", sources.FEEDS[c]) for c in NEWS_CATEGORIES]

    for label, feeds in groups:
        print(f"\n{label}")
        with ThreadPoolExecutor(max_workers=6) as ex:
            for good, name, info, url in ex.map(check_feed, feeds):
                print(f"  {'✅' if good else '❌'} {name:<16} {info}")
                if good:
                    ok += 1
                else:
                    fail += 1
                    print(f"      {url}")

    print("\n🌤 天気・地震・為替（JSON API）")
    api_checks = [
        ("気象庁 予報",  sources.JMA_FORECAST.format(area=CONFIG["location"]["jma_area"])),
        ("気象庁 概況",  sources.JMA_OVERVIEW.format(area=CONFIG["location"]["jma_area"])),
        ("気象庁 地震",  sources.JMA_QUAKE),
        ("USGS 地震",   sources.USGS_QUAKE),
        ("Open-Meteo", "https://api.open-meteo.com/v1/forecast"
                       f"?latitude={CONFIG['location']['lat']}&longitude={CONFIG['location']['lon']}"
                       "&current=temperature_2m&timezone=Asia%2FTokyo"),
        ("為替(主)",    sources.FX_PRIMARY.format(base="USD")),
        ("為替(予備)",  sources.FX_FALLBACK.format(base="USD")),
    ]
    for name, url in api_checks:
        try:
            d = get_json(url, ttl=0)
            n = len(d) if isinstance(d, (list, dict)) else 1
            print(f"  ✅ {name:<12} 取得OK ({n}項目)")
            ok += 1
        except Exception as e:
            print(f"  ❌ {name:<12} {type(e).__name__}: {str(e)[:60]}")
            print(f"      {url}")
            fail += 1

    vault = Path(CONFIG["vault"])
    print(f"\n📓 Obsidian Vault: {vault}")
    print(f"  {'✅ 見つかりました' if vault.exists() else '❌ 見つかりません（CHIBITARU_VAULT を設定してください）'}")

    print("\n" + "=" * 62)
    print(f"結果: ✅ {ok} 件OK / ❌ {fail} 件NG")
    if fail:
        print("※ NGが数本あっても、他の情報源で埋まるので画面は動きます。")
        print("※ 直したい場合は dashboard/sources.py のURLを差し替えてください。")
    print("=" * 62)
    return 0


# ─────────────────────────────────────────────
#  Vault の用意（--init-vault）
# ─────────────────────────────────────────────

def run_init_vault() -> int:
    """記録先のフォルダを作る。既にあれば何も壊さない。"""
    vault = Path(CONFIG["vault"])
    folder = CONFIG["obsidian"]["folder"]

    print("=" * 56)
    print("📓 Obsidian Vault の用意")
    print("=" * 56)
    print(f"  場所: {vault}")

    existed = vault.exists()
    if existed:
        print("  ✅ すでにあります（中身はそのままです）")
    else:
        print("  ➕ 新しく作ります")

    for sub in ("Daily", "Sources", "Topics"):
        (vault / folder / sub).mkdir(parents=True, exist_ok=True)

    readme = vault / folder / "README.md"
    if not readme.exists():
        readme.write_text(
            "---\ntype: dashboard-index\ntags: [dashboard]\n---\n"
            "# 🖥 ちびたるダッシュボードの記録\n\n"
            "- `Daily/` … その日のニュース（日付・見出し・ソース元・リンク）\n"
            "- `Sources/` … ソース元ごとのノート\n"
            "- `Topics/` … テーマごとのノート\n\n"
            "グラフビューを開くと、日付 ⇄ 媒体 ⇄ テーマ のつながりを辿れます。\n",
            encoding="utf-8",
        )

    print(f"  📁 {vault / folder}/(Daily, Sources, Topics) を用意しました")
    print()
    if not existed:
        print("  ▶ Obsidian で使うには:")
        print("     Obsidian を開く → 「フォルダーを Vault として開く」")
        print(f"     → {vault} を選ぶ")
        print()
    print("  ▶ この場所を覚えさせるには、次のどちらか:")
    print(f'     ・dashboard/config.json に  "vault": "{vault}"')
    print(f'     ・または  export CHIBITARU_VAULT="{vault}"  を ~/.bashrc に追記')
    print("     （自動起動でも確実に効くのは config.json のほうです）")
    print("=" * 56)
    return 0


# ─────────────────────────────────────────────
#  起動
# ─────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="ちびたるダッシュボード")
    ap.add_argument("--port", type=int, default=CONFIG["port"])
    ap.add_argument("--host", default=CONFIG["host"])
    ap.add_argument("--check", action="store_true", help="情報源が生きているか確認する")
    ap.add_argument("--once",  action="store_true", help="1回だけ取得してVaultに記録して終了")
    ap.add_argument("--init-vault", action="store_true",
                    help="記録先のフォルダを作る（既にあれば壊さない）")
    ap.add_argument("--no-browser", action="store_true", help="ブラウザを自動で開かない")
    ap.add_argument("--no-vault",   action="store_true", help="Vaultに書かない")
    args = ap.parse_args()

    if args.no_vault:
        CONFIG["obsidian"]["enabled"] = False

    if args.init_vault:
        return run_init_vault()

    if args.check:
        return run_check()

    if args.once:
        print("📥 取得中…")
        data = STORE.refresh()
        v = data.get("vault", {})
        print(f"✅ 完了（{data['elapsed']}秒）")
        for cat in NEWS_CATEGORIES:
            print(f"   {cat:<9} {len(data['news'].get(cat, {}).get('items', []))}件")
        print(f"   🚨 紛争 {len(data['alerts']['conflict'].get('items', []))}件 / "
              f"地震 {len(data['alerts']['quake'].get('japan', []))}件")
        if v.get("error"):
            print(f"   📓 Vault: ⚠️ {v['error']}")
        else:
            print(f"   📓 Vault: {v.get('written', 0)}件を記録 → {v.get('daily', '―')}")
        if data.get("errors"):
            print("\n⚠️  取得できなかったもの:")
            for e in data["errors"][:8]:
                print(f"   - {e}")
        return 0

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}/"

    print("=" * 56)
    print("🖥  ちびたるダッシュボード")
    print("=" * 56)
    print(f"  📍 {CONFIG['location']['pref']}{CONFIG['location']['name']}")
    print(f"  🌐 {url}")
    print(f"  📓 Vault: {CONFIG['vault']}"
          f"{'' if CONFIG['obsidian']['enabled'] else '（記録OFF）'}")
    print(f"  🚨 地震アラート: 震度{CONFIG['alerts']['min_shindo']}以上"
          f"（震度{CONFIG['notify']['min_shindo']}以上は通知）")
    print(f"  💻 {sysinfo.describe(CONFIG['sysinfo'])}")
    print("  ⏹  終了は Ctrl+C")
    print("=" * 56)

    stop = threading.Event()
    threading.Thread(target=lambda: STORE.refresh(), daemon=True).start()
    threading.Thread(target=background_loop, args=(STORE, stop), daemon=True).start()

    if CONFIG["open_browser"] and not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 停止しました")
    finally:
        stop.set()
        httpd.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
