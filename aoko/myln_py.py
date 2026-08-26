"""
MYLN-FRAME 純Python互換コア
==============================
libmyln (C実装) が無い環境でも同じ判定を行うための、
標準ライブラリだけで動くフォールバック実装。

  - 外部依存ゼロ（numpy 不要 / コンパイル不要 / GPU 不要 / LLM 不要）
  - .so / .dylib / .dll のビルド済みバイナリが無くても動く
  - MylnFrame と同一の API（infer / predict / tag / dim / n_classes / version）

低スペック Linux・古い x86_64・ARM SBC など、
バイナリを配布できない環境向けの「軽量モード」の心臓部。

注意:
    C実装 (libmyln) とは別実装のため、確率値はビット単位で一致しない。
    5段階のレベル判定が一致するようにチューニングした互換品である。
    ネイティブ版が使える環境では、そちらが常に優先される。

Usage:
    from myln_py import PyMylnFrame

    frame = PyMylnFrame(n_classes=5).tune_security(in_dim=5)
    frame.predict([0.9, 0.95, 0.8, 0.99, 0.85])   # → 'CRITICAL'
"""

import math
from typing import List, Optional

__version__ = "0.1.0-py"

# ── 特徴量の重み ───────────────────────────────────────────────
# 入力順: [proc_anomaly, cpu_spike, net_bytes, file_change, mem_pressure]
# 合計 1.0。ファイル改変とプロセス異常を重く見る（ランサムウェア優先検知）。
_WEIGHTS = (0.26, 0.10, 0.22, 0.32, 0.10)

# ── 危険度クラスの中心値 ────────────────────────────────────────
# 等間隔ではない。「検知された時点で最低でも LOW」という運用に合わせ、
# 低危険側を密に、高危険側を疎に配置している。
_CENTERS = (0.00, 0.18, 0.32, 0.50, 0.75)

# 確率分布のなだらかさ。小さいほど断定的になる。
_TAU = 0.20

# 複数の指標が同時に立った時の加点（単発の誤検知と区別するため）
_BREADTH_BONUS = 0.06
_ELEVATED_THRESHOLD = 0.5

SECURITY_CLASSES = ["SAFE", "LOW", "MEDIUM", "HIGH", "CRITICAL"]


def risk_score(features: List[float]) -> float:
    """
    特徴量ベクトルを 0.0〜1.0 の危険度スコアに畳み込む。

    重み付き和に「同時に立っている指標の数」によるボーナスを加える。
    1つだけ跳ねた場合（＝よくある誤検知）は加点されず、
    複数指標が連動した場合（＝本物の攻撃）だけスコアが伸びる。
    """
    if not features:
        return 0.0

    # 入力次元が重みより多い/少ない場合も落ちないように合わせる
    n = min(len(features), len(_WEIGHTS))
    score = 0.0
    for i in range(n):
        v = features[i]
        # 0.0-1.0 にクランプ（異常値でスコアが壊れないように）
        if v < 0.0:
            v = 0.0
        elif v > 1.0:
            v = 1.0
        score += v * _WEIGHTS[i]

    elevated = sum(1 for i in range(n) if features[i] >= _ELEVATED_THRESHOLD)
    if elevated >= 2:
        score += _BREADTH_BONUS * (elevated - 1)

    return min(score, 1.0)


def _distribute(score: float, n_classes: int) -> List[float]:
    """
    スコアをクラス確率分布に変換する（ガウシアンカーネル + 正規化）。

    各クラスの中心値からの距離が近いほど高い確率になる。
    argmax は「最も近い中心値のクラス」と一致する。
    """
    centers = _class_centers(n_classes)
    raw = [math.exp(-(((score - c) / _TAU) ** 2)) for c in centers]
    total = sum(raw)
    if total <= 0.0:
        # 数値的にありえないが、念のため一様分布を返す
        return [1.0 / n_classes] * n_classes
    return [r / total for r in raw]


def _class_centers(n_classes: int) -> List[float]:
    """クラス数に応じた中心値。5クラス以外は等間隔で生成する。"""
    if n_classes == len(_CENTERS):
        return list(_CENTERS)
    if n_classes <= 1:
        return [0.0]
    step = 1.0 / (n_classes - 1)
    return [i * step for i in range(n_classes)]


class PyMylnFrame:
    """
    MylnFrame の純Python互換実装。

    ctypes も共有ライブラリも使わないので、Python さえ動けばどこでも動く。
    """

    SECURITY_CLASSES = SECURITY_CLASSES

    def __init__(self, size: str = "T", n_classes: int = 5, lib_path: Optional[str] = None):
        # lib_path は MylnFrame とシグネチャを揃えるためだけに受け取る（未使用）
        self._size = size
        self._n_classes = n_classes
        self._dim = 5
        self._tuned = False

    # ── チューニング ────────────────────────────────────────────
    def tune_security(self, in_dim: int = 5) -> "PyMylnFrame":
        """セキュリティ監視用プリセット。重みは定数として組み込み済み。"""
        self._dim = in_dim
        self._tuned = True
        return self  # メソッドチェーン用

    # ── 推論 ───────────────────────────────────────────────────
    def infer(self, features: List[float]) -> List[float]:
        """特徴量リストからクラス確率を返す。"""
        return _distribute(risk_score(list(features)), self._n_classes)

    def predict(self, features: List[float], classes: Optional[list] = None) -> str:
        """最も確率の高いクラス名を返す。"""
        labels = classes or self.SECURITY_CLASSES
        probs = self.infer(features)
        return labels[probs.index(max(probs))]

    def predict_with_score(self, features: List[float], classes: Optional[list] = None):
        """(クラス名, 確率) のタプルを返す。"""
        labels = classes or self.SECURITY_CLASSES
        probs = self.infer(features)
        best = probs.index(max(probs))
        return labels[best], probs[best]

    # ── メタ情報 ───────────────────────────────────────────────
    @property
    def tag(self) -> str:
        return f"MYLN-PY-{self._size}"

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def n_classes(self) -> int:
        return self._n_classes

    @property
    def version(self) -> str:
        return __version__

    def __repr__(self):
        return f"PyMylnFrame(tag={self.tag!r}, dim={self.dim}, classes={self.n_classes})"


# ── 単体テスト ─────────────────────────────────────────────────
if __name__ == "__main__":
    frame = PyMylnFrame().tune_security(in_dim=5)
    print(frame, "\n")
    samples = [
        ("平常時",             [0.0,  0.0,  0.0,  0.0,  0.0 ]),
        ("不審プロセス",        [0.80, 0.50, 0.0,  0.0,  0.0 ]),
        ("バックドア通信",      [0.60, 0.0,  0.85, 0.0,  0.0 ]),
        ("Vault大量変更(38件)", [0.50, 0.40, 0.0,  0.95, 0.0 ]),
        ("ランサムウェア",      [0.90, 0.90, 0.70, 0.95, 0.75]),
    ]
    for name, f in samples:
        level, p = frame.predict_with_score(f)
        print(f"  {name:<22} score={risk_score(f):.3f}  → {level:<8} ({p:.0%})")
