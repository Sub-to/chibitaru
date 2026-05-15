#!/usr/bin/env python3
"""
🔵 青っ子 myln_conductor.py - MYLN-FRAME 版指揮官
===================================================
conductor.py の完全互換ドロップイン版。
Qwen2.5 × 3 の代わりに MYLN-FRAME C++ コアを使用。

- GPU 不要 / LLM 不要 / 推論 < 1ms / メモリ < 20MB

使い方:
  monitor.py の先頭を
    from conductor      import judge   # 旧
    from myln_conductor import judge   # 新
  に変えるだけ。
"""

import sys, time, platform
from pathlib import Path

# ── ライブラリパス ────────────────────────────────────────────
def _pick_lib() -> str:
    s = platform.system()
    if s == "Darwin":  return "libmyln.dylib"
    if s == "Windows": return "myln.dll"
    return "libmyln.so"

_LIB_PATH = str(Path(__file__).parent / "lib" / _pick_lib())
sys.path.insert(0, str(Path(__file__).parent))

from feature_extractor import extract

# ── MYLN-FRAME 起動 ───────────────────────────────────────────
_frame   = None
_MYLN_OK = False
try:
    from myln import MylnFrame
    _frame   = MylnFrame(size="T", n_classes=5, lib_path=_LIB_PATH).tune_security(in_dim=5)
    _MYLN_OK = True
    print(f"  [MYLN] ✅ {_frame.tag} v{_frame.version} 起動完了")
except Exception as e:
    print(f"  [MYLN] ⚠️ 起動失敗: {e} → LLM にフォールバック")

# ── 定数 ─────────────────────────────────────────────────────
LEVELS  = ["SAFE", "LOW", "MEDIUM", "HIGH", "CRITICAL"]
ICONS   = {"SAFE":"✅","LOW":"🔵","MEDIUM":"🟡","HIGH":"🔴","CRITICAL":"💀"}
ACTIONS = {
    "SAFE":     "記録のみ",
    "LOW":      "監視強化",
    "MEDIUM":   "ネットワーク切断",
    "HIGH":     "Vault隔離＋通知",
    "CRITICAL": "人間に判断委ねる",
    "UNKNOWN":  "手動確認",
}
_SLOTS = ["プロセス監視", "ネット監視", "ファイル監視", "リソース監視"]


def judge(event: dict) -> dict:
    """
    イベントを MYLN-FRAME で判定する。
    返り値は conductor.py と同一形式。
    """
    # フォールバック: MYLN が使えない場合は LLM を使う
    if not _MYLN_OK:
        from conductor import judge as _llm_judge
        return _llm_judge(event)

    print(f"\n  [MYLN] ⚡ 分析: {event.get('type','?')}")
    t0 = time.time()

    # 1. 特徴量抽出
    feats = extract(event)
    print("  [特徴量] " + "  ".join(
        f"{l}={v:.2f}" for l, v in zip(["proc","cpu","net","file","mem"], feats)
    ))

    # 2. 推論
    probs       = _frame.infer(feats)
    final_level = LEVELS[probs.index(max(probs))]

    elapsed = (time.time() - t0) * 1000

    # 3. 4ヘッドを個別表示（三連星風）
    slot_inputs = [
        [feats[0], 0,       0,       0,       0      ],  # proc
        [0,        feats[1],feats[2],0,       0      ],  # cpu+net
        [0,        0,       0,       feats[3],0      ],  # file
        [0,        0,       0,       0,       feats[4]],  # mem
    ]
    verdicts = []
    for i, (name, sf) in enumerate(zip(_SLOTS, slot_inputs)):
        sp = _frame.infer(sf)
        sl = LEVELS[sp.index(max(sp))]
        print(f"  [頭{i+1}/{name}] {ICONS.get(sl,'⚪')} {sl}")
        verdicts.append({"agent": str(i+1), "level": sl, "reason": f"{name} score={max(sp):.0%}"})

    action = ACTIONS.get(final_level, "手動確認")
    print(f"  [MYLN] {ICONS.get(final_level,'⚪')} 最終: {final_level} → {action} ({elapsed:.1f}ms)")

    return {"level": final_level, "action": action, "event": event, "verdicts": verdicts}


# ── テスト ────────────────────────────────────────────────────
if __name__ == "__main__":
    for ev in [
        {"type": "suspicious_process", "detail": "未知プロセスが/etc/passwdにアクセス"},
        {"type": "vault_mass_change",  "detail": "38件急増", "count": 38},
        {"type": "ransomware_pattern", "detail": "大量ファイル暗号化試行を検出"},
    ]:
        r = judge(ev)
        print(f"  → level={r['level']}\n")
