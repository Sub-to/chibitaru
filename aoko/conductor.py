#!/usr/bin/env python3
"""
🔵 青っ子 conductor.py - 三連星指揮官
=======================================
A・B・C号機に脅威情報を投げて多数決で判定する。
"""

import json
import time
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import Optional

# ── 3号機のポート設定 ────────────────────────────────────────────────────────
AGENTS = {
    "A": {
        "port": 11201,
        "name": "ファイル監視",
        "system": "あなたはファイルとプロセスのセキュリティ監視AIです。不審なファイルアクセス・プロセス起動を検出し、JSONのみで回答します。",
    },
    "B": {
        "port": 11202,
        "name": "ネットワーク監視",
        "system": "あなたはネットワーク通信のセキュリティ監視AIです。不審な通信・外部接続を検出し、JSONのみで回答します。",
    },
    "C": {
        "port": 11203,
        "name": "AI攻撃判定",
        "system": "あなたはAI攻撃・プロンプトインジェクションを検出するセキュリティAIです。AIを使った攻撃パターンを識別し、JSONのみで回答します。",
    },
}

# ── 脅威レベル ────────────────────────────────────────────────────────────────
LEVELS = ["SAFE", "LOW", "MEDIUM", "HIGH", "CRITICAL"]


@dataclass
class Verdict:
    agent: str
    level: str
    reason: str
    elapsed: float


def ask_agent(agent_id: str, port: int, event: dict, system: str = "") -> Optional[Verdict]:
    """1号機に問い合わせて判定を受け取る。"""
    prompt = f"""セキュリティイベントを分析してください。

イベント: {json.dumps(event, ensure_ascii=False)}

以下のJSON形式のみで回答してください（説明不要）:
{{"level": "SAFE/LOW/MEDIUM/HIGH/CRITICAL", "reason": "理由を30字以内"}}"""

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = json.dumps({
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 60,
    }).encode()

    t0 = time.time()
    try:
        req = urllib.request.Request(
            f"http://localhost:{port}/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
            text = data["choices"][0]["message"]["content"].strip()
            # JSON部分だけ抽出
            start = text.find("{")
            end = text.rfind("}") + 1
            result = json.loads(text[start:end])
            return Verdict(
                agent=agent_id,
                level=result.get("level", "SAFE").upper(),
                reason=result.get("reason", ""),
                elapsed=time.time() - t0,
            )
    except Exception as e:
        print(f"  [青っ子{agent_id}] ⚠️ 応答なし: {e}")
        return None


def majority_vote(verdicts: list[Verdict]) -> tuple[str, list[Verdict]]:
    """多数決で最終脅威レベルを決定する。"""
    if not verdicts:
        return "UNKNOWN", []

    # レベルを数値化して平均
    scores = {v: i for i, v in enumerate(LEVELS)}
    valid = [v for v in verdicts if v.level in scores]
    if not valid:
        return "UNKNOWN", verdicts

    avg = sum(scores[v.level] for v in valid) / len(valid)
    final_level = LEVELS[round(avg)]
    return final_level, verdicts


def judge(event: dict) -> dict:
    """
    イベントを3号機に投げて多数決で判定。
    戻り値: {"level": str, "verdicts": list, "action": str}
    """
    print(f"\n  [指揮官] 🔵 脅威分析開始: {event.get('type','?')}")
    verdicts = []

    for agent_id, info in AGENTS.items():
        v = ask_agent(agent_id, info["port"], event, info.get("system", ""))
        if v:
            verdicts.append(v)
            icon = {"SAFE": "✅", "LOW": "🔵", "MEDIUM": "🟡",
                    "HIGH": "🔴", "CRITICAL": "💀"}.get(v.level, "⚪")
            print(f"  [{agent_id}号機/{info['name']}] {icon} {v.level} "
                  f"「{v.reason}」({v.elapsed:.1f}s)")

    final_level, _ = majority_vote(verdicts)

    action = {
        "SAFE":     "記録のみ",
        "LOW":      "監視強化",
        "MEDIUM":   "ネットワーク切断",
        "HIGH":     "Vault隔離＋通知",
        "CRITICAL": "人間に判断委ねる",
        "UNKNOWN":  "手動確認",
    }.get(final_level, "手動確認")

    print(f"  [指揮官] 🗳️ 最終判定: {final_level} → {action}")

    return {
        "level": final_level,
        "action": action,
        "verdicts": [{"agent": v.agent, "level": v.level, "reason": v.reason}
                     for v in verdicts],
        "event": event,
    }


if __name__ == "__main__":
    # テスト
    test_event = {
        "type": "suspicious_process",
        "detail": "未知のプロセスが/etc/passwdにアクセス試行",
        "pid": 9999,
        "path": "/tmp/.hidden_process",
    }
    result = judge(test_event)
    print(f"\n結果: {json.dumps(result, ensure_ascii=False, indent=2)}")
