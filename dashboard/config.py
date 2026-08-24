#!/usr/bin/env python3
"""
🖥 ちびたるダッシュボード - config.py
==========================================
設定の読み込み。優先順位は 環境変数 > config.json > 既定値。
APIキーが要るサービスは一切使わない（＝完全無料）。
"""

import os
import json
import copy
from pathlib import Path

BASE_DIR   = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"

# キャッシュ置き場（Vaultを汚さないようにホーム配下へ）
CACHE_DIR = Path(os.environ.get(
    "CHIBITARU_DASH_CACHE",
    str(Path.home() / ".chibitaru" / "dashboard")
))

DEFAULTS = {
    # ── サーバー ─────────────────────────────
    "port": 8787,
    "host": "127.0.0.1",
    "open_browser": True,

    # ── 場所（宮崎県宮崎市）───────────────────
    "location": {
        "name":       "宮崎市",
        "pref":       "宮崎県",
        "lat":        31.9111,
        "lon":        131.4239,
        "jma_area":   "450000",   # 気象庁 府県予報区コード（宮崎県）
        "jma_class10": "450010",  # 南部平野部（宮崎市を含む）
        "timezone":   "Asia/Tokyo",
    },

    # ── 更新間隔（秒）─────────────────────────
    # 無料サービスに迷惑をかけないよう、ゆったりめ。
    "intervals": {
        "weather":  1800,   # 30分
        "quake":     180,   # 3分（アラートなので短め）
        "fx":       1800,   # 30分（無料の為替は日次更新のため十分）
        "news":      900,   # 15分
        "conflict":  600,   # 10分
    },

    # ── アラート閾値 ─────────────────────────
    "alerts": {
        "min_shindo":     3,     # 震度3以上を地震アラートに出す
        "world_quake_mag": 6.0,  # 海外はM6.0以上
        "quake_hours":    24,    # 何時間前までを表示するか
        "conflict_hours": 48,
    },

    # ── 表示件数 ─────────────────────────────
    "limits": {
        "per_feed":  12,   # 1フィードから取り込む最大件数
        "per_tab":   40,   # 1タブに表示する最大件数
        "alerts":    12,
    },

    # ── 為替 ─────────────────────────────────
    "fx_pairs": [
        ["USD", "JPY"],
        ["EUR", "JPY"],
        ["EUR", "USD"],
    ],

    # ── デスクトップ通知 ─────────────────────
    # 画面を見ていなくても強い地震に気づけるように。
    # うるさければ enabled を false にする。
    "notify": {
        "enabled":     True,
        "min_shindo":  4,     # 震度4以上だけ通知（画面には3以上を出す）
    },

    # ── Obsidian Vault の場所 ────────────────
    # null なら 環境変数 CHIBITARU_VAULT → ~/ObsidianVault の順に探す。
    # "~/Documents/MyVault" のように書ける（自動起動でも確実に効く）。
    "vault": None,

    # ── Obsidian 記録 ────────────────────────
    "obsidian": {
        "enabled":   True,
        "folder":    "Dashboard",  # Vault内のルートフォルダ
        "article_notes": False,    # true にすると記事1件ごとにノートを作る（グラフが濃くなるが増殖する）
        "log_categories": ["alert", "japan", "world", "miyazaki", "ai", "tech", "gadget", "pc"],
        "min_per_run": 0,
    },

    # ── 画面まわり ───────────────────────────
    "ui": {
        # 文字の大きさ。"auto" は画面とタッチ有無から自動で決める。
        # 数値（0.8〜1.6）で固定もできる。Surface 3 のような高精細小型画面では
        # 既定のままだと文字が小さいので、自動で少し大きくする。
        "scale": "auto",
        # 常時表示（キオスク）向け: 画面が隠れている間は取得を止めて電池を守る
        "pause_when_hidden": True,
        # ニュースをゆっくり自動スクロールする（触ると20秒止まる）
        "auto_scroll": True,
        # このPCの状態を見にいく間隔（秒）
        "sysmon_sec": 3,
    },

    # ── 性能プロファイル ─────────────────────
    # "auto"   : PCの体力を見て自動で決める（Surface 3 などは軽量モード）
    # "light"  : 常に軽量（アニメ無し・件数少なめ・更新ゆっくり）
    # "normal" : 常に通常
    "performance": "auto",

    "http": {
        "timeout":     15,
        "user_agent":  "ChibitaruDashboard/1.0 (personal use; stdlib urllib)",
        "max_workers": 8,
    },
}


# 軽量モードのときに上から被せる値（非力なPCを労わる設定）
LIGHT_OVERRIDES = {
    "intervals": {
        "weather":  3600,   # 60分
        "quake":     300,   # 5分（アラートなので短めは維持）
        "fx":       3600,
        "news":     1800,   # 30分
        "conflict": 1200,
    },
    "limits": {
        "per_feed": 8,
        "per_tab":  20,     # DOMを軽くする（描画がAtomには重い）
        "alerts":   8,
    },
    "http": {"max_workers": 3},   # 同時接続を絞ってCPUとメモリを節約
}


def _deep_merge(base: dict, over: dict) -> dict:
    """辞書を再帰的にマージする（overが勝つ）。"""
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def vault_path(cfg: dict | None = None) -> Path:
    """
    Obsidian Vault の場所。優先順位は
      環境変数 CHIBITARU_VAULT > config.json の "vault" > 既定の ~/ObsidianVault

    config.json でも指定できるようにしてあるのは、自動起動（.desktop）から
    立ち上げると ~/.bashrc が読まれず、環境変数が効かないため。
    """
    env = os.environ.get("CHIBITARU_VAULT")
    if env:
        return Path(env).expanduser()
    if cfg and cfg.get("vault"):
        return Path(str(cfg["vault"])).expanduser()
    return Path.home() / "ObsidianVault"


def load() -> dict:
    """設定を読み込む。config.json が無くても既定値で動く。"""
    cfg = copy.deepcopy(DEFAULTS)

    if CONFIG_PATH.exists():
        try:
            cfg = _deep_merge(cfg, json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except Exception as e:  # 壊れていても止めない
            print(f"⚠️  config.json を読めませんでした（既定値で続行）: {e}")

    # 環境変数での上書き
    if os.environ.get("CHIBITARU_DASH_PORT"):
        try:
            cfg["port"] = int(os.environ["CHIBITARU_DASH_PORT"])
        except ValueError:
            pass
    if os.environ.get("CHIBITARU_DASH_NO_BROWSER"):
        cfg["open_browser"] = False
    if os.environ.get("CHIBITARU_DASH_NO_VAULT"):
        cfg["obsidian"]["enabled"] = False

    # ── 性能プロファイルの決定 ──
    import sysinfo
    info = sysinfo.probe()

    mode = os.environ.get("CHIBITARU_DASH_PERF", cfg.get("performance", "auto"))
    if mode == "auto":
        light = info["light"]
    else:
        light = (mode == "light")

    if light:
        cfg = _deep_merge(cfg, LIGHT_OVERRIDES)

    cfg["light_mode"] = light
    cfg["sysinfo"]    = info
    cfg["vault"]      = str(vault_path(cfg))
    cfg["cache_dir"]  = str(CACHE_DIR)
    return cfg


CONFIG = load()
