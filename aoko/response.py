#!/usr/bin/env python3
"""
🔵 青っ子 response.py - 対応実行エンジン
==========================================
判定結果を受けて実際の防御アクションを実行する。
最終判断は必ず人間に委ねる。
"""

import os
import sys
import json
import datetime
import subprocess
import platform
from pathlib import Path

VAULT_PATH = Path(os.environ.get("CHIBITARU_VAULT", str(Path.home() / "ObsidianVault")))
LOG_PATH   = VAULT_PATH / "chibitaru-alerts.md"

_OS = platform.system()  # "Darwin" / "Linux" / "Windows"


def notify_user(title: str, message: str, urgent: bool = False):
    """OS問わず通知を送る（Mac / Linux / Windows 対応）。"""
    try:
        if _OS == "Darwin":
            sound = "Funk" if urgent else "default"
            subprocess.run([
                "osascript", "-e",
                f'display notification "{message}" with title "{title}" sound name "{sound}"'
            ], check=False)
        elif _OS == "Linux":
            urgency = "critical" if urgent else "normal"
            subprocess.run(
                ["notify-send", "-u", urgency, title, message],
                check=False, timeout=5
            )
        elif _OS == "Windows":
            # PowerShell トースト通知
            ps_cmd = (
                f"[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
                f"ContentType=WindowsRuntime] | Out-Null;"
                f"$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
                f"[Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
                f"$xml.GetElementsByTagName('text')[0].AppendChild($xml.CreateTextNode('{title}')) | Out-Null;"
                f"$xml.GetElementsByTagName('text')[1].AppendChild($xml.CreateTextNode('{message}')) | Out-Null;"
                f"$toast = [Windows.UI.Notifications.ToastNotification]::new($xml);"
                f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('チビタル').Show($toast)"
            )
            subprocess.run(["powershell", "-Command", ps_cmd], check=False, timeout=10)
    except Exception:
        pass
    # どのOSでも必ずコンソールにも出す
    prefix = "🚨" if urgent else "🔔"
    print(f"  [{prefix}] {title}: {message}")


def disconnect_network():
    """ネットワークを切断する（緊急時・OS対応）。"""
    try:
        if _OS == "Darwin":
            result = subprocess.run(
                ["networksetup", "-setairportpower", "en0", "off"],
                capture_output=True, timeout=5
            )
            return result.returncode == 0
        elif _OS == "Linux":
            # nmcli or ip
            for cmd in [["nmcli", "radio", "wifi", "off"], ["ip", "link", "set", "wlan0", "down"]]:
                r = subprocess.run(cmd, capture_output=True, timeout=5)
                if r.returncode == 0:
                    return True
            return False
        elif _OS == "Windows":
            r = subprocess.run(
                ["netsh", "interface", "set", "interface", "Wi-Fi", "disable"],
                capture_output=True, timeout=5
            )
            return r.returncode == 0
    except Exception:
        return False


def make_vault_readonly():
    """VaultフォルダをRead-Onlyに変更（緊急保護）。"""
    try:
        subprocess.run(["chmod", "-R", "444", str(VAULT_PATH)],
                       capture_output=True, timeout=10)
        return True
    except Exception:
        return False


def restore_vault_writable():
    """Vault書き込み権限を復元。"""
    try:
        subprocess.run(["chmod", "-R", "644", str(VAULT_PATH)],
                       capture_output=True, timeout=10)
        return True
    except Exception:
        return False


def log_to_vault(result: dict):
    """判定結果をVaultに記録する。"""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    level = result.get("level", "UNKNOWN")
    action = result.get("action", "?")
    event = result.get("event", {})
    verdicts = result.get("verdicts", [])

    icon = {"SAFE": "✅", "LOW": "🔵", "MEDIUM": "🟡",
            "HIGH": "🔴", "CRITICAL": "💀"}.get(level, "⚪")

    entry = f"""
## {icon} [{now}] {level} - {event.get('type', '不明')}

| 項目 | 内容 |
|------|------|
| 脅威レベル | `{level}` |
| 対応 | {action} |
| イベント | {event.get('detail', '')} |

**三連星の判定:**
"""
    for v in verdicts:
        v_icon = {"SAFE": "✅", "LOW": "🔵", "MEDIUM": "🟡",
                  "HIGH": "🔴", "CRITICAL": "💀"}.get(v['level'], "⚪")
        entry += f"- {v['agent']}号機: {v_icon} {v['level']} 「{v['reason']}」\n"

    entry += "\n---\n"

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not LOG_PATH.exists():
        LOG_PATH.write_text(
            "# 🔵 Chibitaru Security Alert Log\n\n",
            encoding="utf-8"
        )
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(entry)


def execute(result: dict) -> bool:
    """
    判定結果に基づいて防御アクションを実行する。
    戻り値: True=正常完了 / False=人間の対応が必要
    """
    level  = result.get("level", "UNKNOWN")
    event  = result.get("event", {})
    action = result.get("action", "")

    # 常に記録
    log_to_vault(result)

    if level == "SAFE":
        return True

    elif level == "LOW":
        notify_user("🔵 青っ子", f"低脅威検知: {event.get('type','?')}")
        return True

    elif level == "MEDIUM":
        notify_user("🟡 青っ子 警告", f"ネットワーク切断を検討: {event.get('detail','')}", urgent=True)
        # 自動切断はしない → 通知のみ
        return True

    elif level == "HIGH":
        notify_user("🔴 青っ子 危険！", "Vault保護中・確認してください", urgent=True)
        # Vaultをread-onlyに保護
        if make_vault_readonly():
            print("  [青っ子] 🔒 Vault を読み取り専用に保護しました")
            notify_user("🔴 Vault保護", "書き込み禁止にしました。解除: restore_vault_writable()")
        return False  # 人間確認が必要

    elif level == "CRITICAL":
        notify_user("💀 青っ子 緊急事態！！", "即座に確認が必要です！", urgent=True)
        print("\n" + "="*50)
        print("💀 CRITICAL 検知！")
        print(f"   {event.get('detail','')}")
        print("="*50)
        print("\n選択してください:")
        print("  1: ネットワーク切断")
        print("  2: Vault隔離")
        print("  3: 両方")
        print("  0: 何もしない（手動対応）")
        try:
            choice = input("選択 > ").strip()
            if choice in ("1", "3"):
                if disconnect_network():
                    print("  ✅ Wi-Fi を切断しました")
            if choice in ("2", "3"):
                if make_vault_readonly():
                    print("  ✅ Vault を保護しました")
        except (KeyboardInterrupt, EOFError):
            print("\n  手動対応モードに移行します")
        return False

    return True


if __name__ == "__main__":
    # テスト
    test_result = {
        "level": "HIGH",
        "action": "Vault隔離＋通知",
        "event": {"type": "ransomware_pattern", "detail": "大量ファイル暗号化試行を検出"},
        "verdicts": [
            {"agent": "A", "level": "HIGH", "reason": "暗号化プロセス多数起動"},
            {"agent": "B", "level": "MEDIUM", "reason": "外部への大量通信"},
            {"agent": "C", "level": "HIGH", "reason": "ランサムウェアパターン一致"},
        ]
    }
    execute(test_result)
