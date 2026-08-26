#!/usr/bin/env python3
"""
🔵 青っ子 monitor.py - OS監視エンジン
======================================
Macのファイル・プロセス・ネットワークを監視して
怪しいイベントを指揮官(conductor)に流す。
"""

import os
import re
import sys
import time
import json
import platform
import subprocess
import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# ── 判定エンジンの選択 ────────────────────────────────────────────────────────
# CHIBITARU_ENGINE=llm    → Qwen2.5×3（llama-server + 940MBモデルが必要）
# それ以外（既定 auto）    → MYLN-FRAME（native or 純Python・軽量モード）
_ENGINE = os.environ.get("CHIBITARU_ENGINE", "auto").strip().lower()
if _ENGINE == "llm":
    from conductor import judge
    _ENGINE_NAME = "llm"
else:
    from myln_conductor import judge, backend
    _ENGINE_NAME = backend()

from response import execute

_OS = platform.system()  # "Darwin" / "Linux" / "Windows"

# ── 監視設定 ──────────────────────────────────────────────────────────────────
SCAN_INTERVAL   = 30      # 秒
VAULT_PATH      = Path(os.environ.get("CHIBITARU_VAULT", str(Path.home() / "ObsidianVault")))

# 怪しいプロセス名のパターン
SUSPICIOUS_PROCS = [
    r"\.hidden", r"tmp/\.", r"/var/tmp/",
    r"curl.*\|.*sh", r"wget.*\|.*sh",
    r"nc\s+-", r"ncat\s",
    r"python.*-c.*exec", r"base64.*decode",
]

# 怪しいネットワーク接続先（国別コードは粗いが参考程度）
SUSPICIOUS_PORTS = {4444, 5555, 6666, 31337, 1337}  # よくあるバックドアポート

# Vault内で急増したら警告するファイル変化閾値
VAULT_CHANGE_THRESHOLD = 20  # 30秒以内にこれ以上変更されたら異常


def get_processes() -> list[dict]:
    """現在起動中のプロセス一覧を取得（OS対応）。"""
    try:
        if _OS == "Windows":
            result = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=5
            )
            procs = []
            for line in result.stdout.splitlines():
                parts = [p.strip('"') for p in line.split('","')]
                if len(parts) >= 2:
                    procs.append({"pid": parts[1], "cpu": "?", "mem": "?", "cmd": parts[0]})
            return procs
        else:
            # macOS / Linux
            result = subprocess.run(
                ["ps", "aux"],
                capture_output=True, text=True, timeout=5
            )
            procs = []
            for line in result.stdout.splitlines()[1:]:
                parts = line.split(None, 10)
                if len(parts) >= 11:
                    procs.append({
                        "pid": parts[1],
                        "cpu": parts[2],
                        "mem": parts[3],
                        "cmd": parts[10],
                    })
            return procs
    except Exception:
        return []


def get_network_connections() -> list[dict]:
    """現在のネットワーク接続一覧（OS対応）。"""
    try:
        if _OS == "Windows":
            result = subprocess.run(
                ["netstat", "-n"],
                capture_output=True, text=True, timeout=5
            )
        else:
            result = subprocess.run(
                ["netstat", "-an"],
                capture_output=True, text=True, timeout=5
            )
        conns = []
        for line in result.stdout.splitlines():
            if "ESTABLISHED" in line or "SYN_SENT" in line:
                conns.append({"raw": line.strip()})
        return conns
    except Exception:
        return []


def check_suspicious_processes(procs: list[dict]) -> list[dict]:
    """不審なプロセスを検出。"""
    events = []
    for proc in procs:
        cmd = proc.get("cmd", "")
        for pattern in SUSPICIOUS_PROCS:
            if re.search(pattern, cmd, re.IGNORECASE):
                events.append({
                    "type": "suspicious_process",
                    "detail": f"不審なプロセス検出: {cmd[:80]}",
                    "pid": proc["pid"],
                    "path": cmd.split()[0] if cmd else "",
                })
                break
    return events


def check_suspicious_network(conns: list[dict]) -> list[dict]:
    """不審なネットワーク接続を検出。"""
    events = []
    for conn in conns:
        raw = conn.get("raw", "")
        # バックドアポートチェック
        for port in SUSPICIOUS_PORTS:
            if f".{port} " in raw or f":{port} " in raw:
                events.append({
                    "type": "suspicious_network",
                    "detail": f"バックドアポート接続疑い: {raw}",
                    "port": port,
                })
    return events


def check_vault_changes() -> list[dict]:
    """Vault内のファイル変化が急増していないか確認（OS対応）。"""
    events = []
    try:
        now = time.time()
        cutoff = now - SCAN_INTERVAL * 2  # 直近60秒
        changed = []
        for md in VAULT_PATH.rglob("*.md"):
            try:
                if md.stat().st_mtime > cutoff and ".obsidian" not in md.parts:
                    changed.append(str(md))
            except OSError:
                continue
        if len(changed) >= VAULT_CHANGE_THRESHOLD:
            events.append({
                "type": "vault_mass_change",
                "detail": f"Vault内ファイルが急増変化: {len(changed)}件（ランサムウェア疑い）",
                "count": len(changed),
            })
    except Exception:
        pass
    return events


def check_ai_injection() -> list[dict]:
    """
    Vault内のノートにプロンプトインジェクション的な文字列がないか確認。
    外部コンテンツ経由でのAI攻撃を想定。
    """
    events = []
    suspicious_patterns = [
        r"ignore previous instructions",
        r"disregard.*system prompt",
        r"あなたはもう.*AIではありません",
        r"sudo.*rm.*-rf",
        r"<script>.*</script>",
        r"eval\(.*base64",
    ]
    # 直近に更新されたノートだけチェック（重くならないよう）
    try:
        cutoff = time.time() - 300  # 直近5分
        recent_files = []
        if VAULT_PATH.exists():
            for md in VAULT_PATH.rglob("*.md"):
                try:
                    if md.stat().st_mtime > cutoff:
                        recent_files.append(str(md))
                except OSError:
                    continue
        recent_files = recent_files[:10]
        for fpath in recent_files:
            try:
                content = Path(fpath).read_text(encoding="utf-8", errors="replace")
                for pat in suspicious_patterns:
                    if re.search(pat, content, re.IGNORECASE):
                        events.append({
                            "type": "ai_injection",
                            "detail": f"プロンプトインジェクション疑い: {Path(fpath).name}",
                            "file": fpath,
                            "pattern": pat,
                        })
                        break
            except Exception:
                continue
    except Exception:
        pass
    return events


def scan_once() -> list[dict]:
    """1回分のスキャンを実行してイベント一覧を返す。"""
    all_events = []
    all_events += check_suspicious_processes(get_processes())
    all_events += check_suspicious_network(get_network_connections())
    all_events += check_vault_changes()
    all_events += check_ai_injection()
    return all_events


def run_monitor(once: bool = False):
    """メイン監視ループ。once=True なら1回スキャンして終了する。"""
    print("\n🔵🔵🔵 青っ子 監視開始 🔵🔵🔵")
    print(f"  判定エンジン: {_ENGINE_NAME}")
    print(f"  Vault: {VAULT_PATH}")
    print(f"  スキャン間隔: {SCAN_INTERVAL}秒")
    print("  Ctrl+C で停止\n" if not once else "  単発スキャンモード\n")

    scan_count = 0
    while True:
        scan_count += 1
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        print(f"  [{ts}] スキャン #{scan_count}...", end=" ", flush=True)

        all_events = scan_once()

        if not all_events:
            print("✅ 異常なし")
        else:
            print(f"⚠️ {len(all_events)}件のイベント検出！")
            for event in all_events:
                result = judge(event)          # 三連星で判定
                execute(result)                # 対応実行
                # SAFEなら次へ
                if result["level"] == "SAFE":
                    continue

        if once:
            return
        time.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    try:
        run_monitor(once="--once" in sys.argv)
    except KeyboardInterrupt:
        print("\n\n  🔵 監視を停止しました")
