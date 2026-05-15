"""
MYLN-FRAME 用 特徴量抽出器
============================
イベント辞書 → 5次元数値ベクトルに変換する。

出力形式:
  [proc_anomaly, cpu_spike, net_bytes, file_change, mem_pressure]
  すべて 0.0〜1.0

イベントタイプ一覧:
  suspicious_process  → proc 高
  suspicious_network  → net 高
  vault_mass_change   → file 高（ランサムウェア指標）
  ai_injection        → file + proc 中
  ransomware_pattern  → 全部高
"""


def extract(event: dict, sys_metrics: dict = None) -> list:
    """
    event     : monitor.py が生成するイベント辞書
    sys_metrics: {'cpu_pct': 0-100, 'mem_pct': 0-100} など（任意）
    戻り値    : [proc, cpu, net, file, mem] 各 0.0-1.0
    """
    etype  = event.get("type", "")
    detail = event.get("detail", "").lower()

    # ── イベントタイプ別ベーススコア ──────────────────────────
    proc = cpu = net = file = mem = 0.0

    if etype == "suspicious_process":
        proc = 0.80
        cpu  = 0.50

    elif etype == "suspicious_network":
        net  = 0.85
        proc = 0.30

    elif etype == "vault_mass_change":
        count = event.get("count", 0)
        file  = min(count / 40.0, 1.0)   # 40件で満点
        proc  = 0.50
        cpu   = 0.40

    elif etype == "ai_injection":
        file  = 0.60
        proc  = 0.45

    elif etype == "ransomware_pattern":
        proc  = 0.90
        file  = 0.95
        net   = 0.70
        cpu   = 0.90
        mem   = 0.75

    # ── キーワードブースト ────────────────────────────────────
    if any(w in detail for w in ("暗号化", "encrypt", "cipher")):
        file = min(file + 0.30, 1.0)
        proc = min(proc + 0.20, 1.0)

    if any(w in detail for w in ("ランサム", "ransom")):
        file = max(file, 0.90)
        proc = max(proc, 0.80)

    if any(w in detail for w in ("バックドア", "backdoor", "reverse shell")):
        net  = max(net,  0.85)
        proc = max(proc, 0.60)

    if "大量" in detail:
        file = min(file + 0.20, 1.0)

    if any(w in detail for w in ("injection", "インジェクション", "prompt")):
        proc = min(proc + 0.15, 1.0)

    # ── システム実測値で上書き（あれば）────────────────────────
    if sys_metrics:
        cpu = max(cpu, sys_metrics.get("cpu_pct", 0) / 100.0)
        mem = max(mem, sys_metrics.get("mem_pct", 0) / 100.0)

    return [
        round(proc, 3),
        round(cpu,  3),
        round(net,  3),
        round(file, 3),
        round(mem,  3),
    ]
