#!/usr/bin/env python3
"""
👹 鬼丸（Onimaru）セキュリティAI - Phase 1
ログ監視 + Vault記録

対応OS: macOS / Linux
常駐方法: LaunchAgent (Mac) / systemd (Linux)
"""

import subprocess
import os
import sys
import time
import json
import re
import hashlib
from datetime import datetime
from pathlib import Path

# ─── 設定 ────────────────────────────────────────────
VAULT_PATH      = Path("/Users/masudatakaaki/Ofsaver1")
REPORT_DIR      = VAULT_PATH / "日記" / "鬼丸レポート"
STATE_FILE      = Path.home() / ".onimaru_state.json"
SYSLOG_PATH     = Path("/var/log/system.log")
AUTH_LOG_PATH   = Path("/var/log/auth.log")        # Linux用
CHECK_INTERVAL  = 60   # 秒
LOG_WINDOW_MIN  = 2    # 何分前まで遡るか
PLATFORM        = sys.platform                     # 'darwin' or 'linux'
FP_PATTERNS_FILE = Path.home() / ".orochi_fp_patterns.json"   # 大蛇フィードバック
FP_RELOAD_EVERY  = 10   # 何サイクルごとに再読み込みするか（10回×60秒=10分）

# ─── 監視パターン（正規表現）────────────────────────
DANGER_PATTERNS = [
    r"authentication failure",
    r"Failed password",
    r"FAILED SU",
    r"sudo.*incorrect password",
    r"Invalid user",
    r"Connection closed by.*\[preauth\]",
    r"Repeated login failures",
    r"BREAK-IN ATTEMPT",
]

# 誤検知除外リスト（アプリのエラーは対象外）
IGNORE_PATTERNS = [
    # ─── アプリケーション誤検知 ──────────────────────────
    r"Safari",
    r"LPImageFetcher",
    r"LinkPresentation",
    r"com\.apple\.log.*log run noninteractively",   # 自分自身
    r"Spotify",
    r"Chrome",
    r"firefox",
    # ─── macOS システムデーモン（正常動作）──────────────
    r"opendirectoryd",                # ディレクトリサービス
    r"PasswordChangeAllowed",         # アカウントポリシー評価（脅威ではない）
    r"ScreenTimeAgent",               # スクリーンタイム管理
    r"triald",                        # トライアルサブスクリプション管理
    r"backgroundtaskmanagementd",     # バックグラウンドタスク管理
    r"sharedfilelistd",               # 共有ファイルリストデーモン
    r"syspolicyd",                    # Gatekeeper評価（正常動作）
    r"distnoted",                     # 分散通知デーモン
    r"nesessionmanager",              # ネットワーク拡張セッション管理
    r"nehelper",                      # ネットワーク拡張ヘルパー
    r"ch\.sudo\.cyberduck",           # CyberduckのUUID管理（正常）
    r"NotificationCenter",            # 通知センター
    r"Spotlight",                     # Spotlight検索
    r"dmd\[",                         # デバイス管理デーモン
    r"authdb.*importing right",       # 権限定義インポート（sudo権限の初期化）
    # ─── カーネル・APFS の正常動作 ──────────────────────
    r"is_root_hash_authentication_required",  # APFSルートハッシュ検証
    r"SECUREPKITRUSTSTOREASSETS",             # APFSトラストストアアセット
    r"UC_SIRI_ASR",                           # SiriASRアセット検証
    r"UC_SPEECH_ASR",                         # 音声認識アセット検証
]
WARNING_PATTERNS = [
    r"\bsudo\b",
    r"\bsu\b.*root",
    r"session opened for user root",
    r"Accepted password for",
    r"Accepted publickey for",
    r"USER_PROCESS",
    r"new session",
]
# ────────────────────────────────────────────────────


def hash_line(line: str) -> str:
    """行のハッシュ（重複排除用）"""
    return hashlib.md5(line.encode()).hexdigest()


# ─── 大蛇フィードバック：誤検知パターンの動的読み込み ──
_fp_patterns: list[str] = []

def load_fp_patterns() -> list[str]:
    """大蛇が記録した誤検知パターンをJSONから読み込む"""
    if not FP_PATTERNS_FILE.exists():
        return []
    try:
        data = json.loads(FP_PATTERNS_FILE.read_text(encoding="utf-8"))
        pats = [p["pattern"] for p in data.get("patterns", []) if p.get("pattern")]
        if pats:
            print(f"[ONIMARU] 🐍 大蛇フィードバック読み込み: {len(pats)}パターン")
        return pats
    except Exception as e:
        print(f"[ONIMARU] フィードバック読み込みエラー: {e}")
        return []


def is_ignored(line: str) -> bool:
    """誤検知除外リストに該当するか（静的パターン + 大蛇フィードバック）"""
    for pat in IGNORE_PATTERNS:
        if re.search(pat, line, re.IGNORECASE):
            return True
    for pat in _fp_patterns:
        if re.search(pat, line, re.IGNORECASE):
            return True
    return False

def classify(line: str) -> str:
    """イベントを重要度で分類"""
    if is_ignored(line):
        return "🔵"   # 無視リストはすべて情報扱い（記録しない）
    for pat in DANGER_PATTERNS:
        if re.search(pat, line, re.IGNORECASE):
            return "🔴"
    for pat in WARNING_PATTERNS:
        if re.search(pat, line, re.IGNORECASE):
            return "🟡"
    return "🔵"


# ─── Mac: Unified Log取得 ────────────────────────────
def get_unified_log(minutes: int = 2) -> list[str]:
    """macOS Unified Logから認証・権限昇格イベントを取得"""
    predicate = (
        '('
        'eventMessage contains[c] "sudo" '
        'OR eventMessage contains[c] "authentication" '
        'OR eventMessage contains[c] "Failed password" '
        'OR eventMessage contains[c] "Invalid user" '
        'OR eventMessage contains[c] "session opened" '
        'OR eventMessage contains[c] "FAILED"'
        ') AND NOT processImagePath ENDSWITH "/log"'   # 自分自身を除外
    )
    try:
        result = subprocess.run(
            ["log", "show", "--predicate", predicate,
             "--last", f"{minutes}m", "--style", "compact", "--no-pager"],
            capture_output=True, text=True, timeout=30
        )
        return [l.strip() for l in result.stdout.splitlines()
                if l.strip() and not l.startswith("Timestamp")]
    except Exception as e:
        return []


# ─── Mac: system.log取得 ────────────────────────────
def get_syslog_events(n_lines: int = 100) -> list[str]:
    """system.log末尾から直近の認証関連行を抽出（今日分のみ）"""
    if not SYSLOG_PATH.exists():
        return []
    try:
        result = subprocess.run(
            ["tail", f"-{n_lines}", str(SYSLOG_PATH)],
            capture_output=True, text=True, timeout=10
        )
        keywords = ["sudo", "su:", "USER_PROCESS", "DEAD_PROCESS",
                    "authentication", "Failed", "login", "logout"]
        # 今日の日付プレフィックス（例: "May  1"）
        today_str = datetime.now().strftime("%b %e")
        lines = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line.startswith(today_str):
                continue   # 今日以外の古いログは無視
            if any(kw.lower() in line.lower() for kw in keywords):
                lines.append(line)
        return lines
    except Exception:
        return []


# ─── Linux: journalctl / auth.log取得 ───────────────
def get_linux_events(minutes: int = 2) -> list[str]:
    """Linuxの認証ログを取得"""
    # journalctl優先
    try:
        result = subprocess.run(
            ["journalctl", "--since", f"{minutes} minutes ago",
             "--no-pager", "-q"],
            capture_output=True, text=True, timeout=30
        )
        keywords = ["sudo", "su:", "authentication", "Failed",
                    "Invalid user", "session", "sshd"]
        return [l.strip() for l in result.stdout.splitlines()
                if any(kw.lower() in l.lower() for kw in keywords)]
    except FileNotFoundError:
        pass
    # フォールバック: auth.log
    if AUTH_LOG_PATH.exists():
        try:
            result = subprocess.run(
                ["tail", "-200", str(AUTH_LOG_PATH)],
                capture_output=True, text=True, timeout=10
            )
            return [l.strip() for l in result.stdout.splitlines() if l.strip()]
        except Exception:
            pass
    return []


# ─── 通知 ────────────────────────────────────────────
def notify_mac(title: str, message: str):
    """Mac通知センターへ通知"""
    safe_msg = message[:80].replace('"', "'")
    script = f'display notification "{safe_msg}" with title "👹 {title}" sound name "Basso"'
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
    except Exception:
        pass


# ─── Vault記録 ───────────────────────────────────────
def save_report(events: list[tuple[str, str]]):
    """VaultにMarkdownレポートを追記"""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    now   = datetime.now().strftime("%H:%M:%S")
    report_path = REPORT_DIR / f"{today}_鬼丸レポート.md"

    # 初回作成時はフロントマターとヘッダを書く
    if not report_path.exists():
        report_path.write_text(
            f"---\n"
            f"日付: {today}\n"
            f"タグ: [鬼丸, セキュリティ, 監視ログ]\n"
            f"---\n\n"
            f"# 👹 鬼丸レポート {today}\n\n"
            f"| 時刻 | 重要度 | イベント |\n"
            f"|------|--------|----------|\n",
            encoding="utf-8"
        )

    with report_path.open("a", encoding="utf-8") as f:
        for level, line in events:
            # 長すぎる行は切り詰め
            short = line[:120].replace("|", "｜")
            f.write(f"| `{now}` | {level} | {short} |\n")


# ─── 状態管理（重複排除）────────────────────────────
def load_seen() -> set:
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text())
            return set(data.get("seen", []))
        except Exception:
            pass
    return set()


def save_seen(seen: set):
    recent = list(seen)[-2000:]   # 最新2000件のみ保持
    STATE_FILE.write_text(json.dumps({"seen": recent}))


# ─── メインループ ────────────────────────────────────
def main():
    # デーモン時もログが即時フラッシュされるよう設定
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)

    print(f"👹 鬼丸 Phase 1 起動 [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]")
    print(f"   Platform : {PLATFORM}")
    print(f"   Vault    : {VAULT_PATH}")
    print(f"   Report   : {REPORT_DIR}")
    print(f"   Interval : {CHECK_INTERVAL}秒\n")

    seen = load_seen()
    global _fp_patterns
    _fp_patterns = load_fp_patterns()
    _cycle = 0

    while True:
        try:
            # 10サイクル（約10分）ごとに大蛇フィードバックを再読み込み
            _cycle += 1
            if _cycle % FP_RELOAD_EVERY == 0:
                _fp_patterns = load_fp_patterns()
            # プラットフォーム別ログ取得
            if PLATFORM == "darwin":
                raw = get_unified_log(LOG_WINDOW_MIN) + get_syslog_events()
            else:
                raw = get_linux_events(LOG_WINDOW_MIN)

            # 重複排除 + 重要度フィルタ
            new_events: list[tuple[str, str]] = []
            for line in raw:
                h = hash_line(line)
                if h not in seen:
                    seen.add(h)
                    level = classify(line)
                    if level in ("🔴", "🟡"):
                        new_events.append((level, line))

            # 🔴危険イベントは即通知
            dangers = [e for e in new_events if e[0] == "🔴"]
            for _, line in dangers[:3]:   # 最大3件まで
                if PLATFORM == "darwin":
                    notify_mac("⚠️ 危険なイベント検知！", line)

            # Vault記録
            if new_events:
                save_report(new_events)
                ts = datetime.now().strftime("%H:%M:%S")
                danger_n  = len([e for e in new_events if e[0] == "🔴"])
                warning_n = len([e for e in new_events if e[0] == "🟡"])
                print(f"[{ts}] 記録: 🔴{danger_n}件 🟡{warning_n}件")

            save_seen(seen)

        except KeyboardInterrupt:
            print("\n👹 鬼丸 停止")
            break
        except Exception as e:
            print(f"[ERROR] {e}")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
