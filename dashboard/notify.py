#!/usr/bin/env python3
"""
🖥 ちびたるダッシュボード - notify.py
==========================================
強い地震のときだけ、デスクトップ通知を出す。

常時表示させている画面を見ていなくても気づけるように。
うるさくならないよう、既定は震度4以上・同じ地震は1回だけ。
青っ子(response.py)と同じやり方でOSごとに出し分ける。
"""

import json
import platform
import subprocess
from pathlib import Path

from config import CONFIG

_OS = platform.system()
_SENT_PATH = Path(CONFIG["cache_dir"]) / "notified.json"
_KEEP = 200


def _load_sent() -> dict:
    if _SENT_PATH.exists():
        try:
            return json.loads(_SENT_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_sent(sent: dict):
    if len(sent) > _KEEP:
        sent = dict(list(sent.items())[-_KEEP:])
    _SENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SENT_PATH.write_text(json.dumps(sent, ensure_ascii=False), encoding="utf-8")


def send(title: str, message: str, urgent: bool = False):
    """OS問わずデスクトップ通知を出す。失敗しても黙って諦める。"""
    try:
        if _OS == "Linux":
            subprocess.run(
                ["notify-send", "-u", "critical" if urgent else "normal",
                 "-a", "ちびたるダッシュボード", title, message],
                check=False, timeout=5,
            )
        elif _OS == "Darwin":
            subprocess.run(
                ["osascript", "-e",
                 f'display notification "{message}" with title "{title}"'],
                check=False, timeout=5,
            )
        elif _OS == "Windows":
            ps = (
                "[reflection.assembly]::loadwithpartialname('System.Windows.Forms');"
                "$n=New-Object System.Windows.Forms.NotifyIcon;"
                "$n.Icon=[System.Drawing.SystemIcons]::Information;"
                f"$n.BalloonTipTitle='{title}';$n.BalloonTipText='{message}';"
                "$n.Visible=$true;$n.ShowBalloonTip(10000)"
            )
            subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           check=False, timeout=10)
    except Exception:
        pass


def notify_quakes(quakes: list[dict], min_shindo: float) -> int:
    """
    まだ知らせていない地震のうち、しきい値以上のものを通知する。
    戻り値は実際に通知した件数。
    """
    if not CONFIG.get("notify", {}).get("enabled", True):
        return 0

    sent = _load_sent()
    count = 0
    for q in quakes:
        if q.get("shindo_v", 0) < min_shindo:
            continue
        key = str(q.get("id") or f'{q.get("time")}{q.get("place")}')
        if key in sent:
            continue
        sent[key] = True
        send(
            f'🌏 地震 最大震度{q.get("shindo")}',
            f'{q.get("place", "")} ／ M{q.get("mag", "―")}\n'
            f'{(q.get("time") or "")[11:16]} 発生（気象庁）',
            urgent=q.get("shindo_v", 0) >= 5,
        )
        count += 1

    if count:
        _save_sent(sent)
    return count
