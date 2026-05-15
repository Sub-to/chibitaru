"""
MYLN-FRAME Python Bridge
========================
ctypes経由でC APIを呼ぶ薄いラッパー。
GPUもフレームワークも不要。

Usage:
    from myln import MylnFrame

    frame = MylnFrame(size="T", n_classes=5)
    frame.tune_security(in_dim=5)

    probs  = frame.infer([0.9, 0.95, 0.8, 0.99, 0.85])
    label  = frame.predict([0.9, 0.95, 0.8, 0.99, 0.85])
    print(label)  # → CRITICAL
"""

import ctypes
import os
import sys
from pathlib import Path
from typing import Optional

# ── libmyln の検索 ────────────────────────────────────────
def _find_lib() -> str:
    candidates = [
        Path(__file__).parent.parent.parent / "build" / "libmyln.so",
        Path(__file__).parent.parent.parent / "build" / "libmyln.dylib",
        Path(__file__).parent.parent.parent / "build" / "myln.dll",
        Path("libmyln.so"),
        Path("libmyln.dylib"),
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    raise FileNotFoundError(
        "libmyln が見つかりません。まず build/ でビルドしてください。\n"
        "  cd build && cmake .. && make myln"
    )


# ── C API バインディング ──────────────────────────────────
class _CAPI:
    def __init__(self, lib_path: Optional[str] = None):
        path = lib_path or _find_lib()
        lib = ctypes.CDLL(path)

        lib.myln_new.restype  = ctypes.c_void_p
        lib.myln_new.argtypes = [ctypes.c_char_p, ctypes.c_int]

        lib.myln_free.restype  = None
        lib.myln_free.argtypes = [ctypes.c_void_p]

        lib.myln_tune_security.restype  = None
        lib.myln_tune_security.argtypes = [ctypes.c_void_p, ctypes.c_int]

        lib.myln_infer.restype  = ctypes.POINTER(ctypes.c_float)
        lib.myln_infer.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_float),
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
        ]

        lib.myln_tag.restype       = ctypes.c_char_p
        lib.myln_tag.argtypes      = [ctypes.c_void_p]
        lib.myln_dim.restype       = ctypes.c_int
        lib.myln_dim.argtypes      = [ctypes.c_void_p]
        lib.myln_n_classes.restype = ctypes.c_int
        lib.myln_n_classes.argtypes= [ctypes.c_void_p]
        lib.myln_version.restype   = ctypes.c_char_p
        lib.myln_version.argtypes  = []

        self.lib = lib

    def version(self) -> str:
        return self.lib.myln_version().decode()


# ── メインクラス ──────────────────────────────────────────
class MylnFrame:
    """
    MYLN-FRAME の Python ラッパー。
    どのプラットフォームでも ctypes だけで動く量産型ブリッジ。
    """

    SECURITY_CLASSES = ["SAFE", "LOW", "MEDIUM", "HIGH", "CRITICAL"]

    def __init__(
        self,
        size: str = "T",
        n_classes: int = 5,
        lib_path: Optional[str] = None,
    ):
        self._api    = _CAPI(lib_path)
        self._handle = self._api.lib.myln_new(size.encode(), n_classes)
        if not self._handle:
            raise RuntimeError(f"myln_new({size}, {n_classes}) failed")
        self._n_classes = n_classes

    def __del__(self):
        if hasattr(self, "_handle") and self._handle:
            self._api.lib.myln_free(self._handle)
            self._handle = None

    # ── チューニング ────────────────────────────────────────
    def tune_security(self, in_dim: int = 5) -> "MylnFrame":
        """セキュリティ監視用に重みを手動チューニングする。"""
        self._api.lib.myln_tune_security(self._handle, in_dim)
        return self  # メソッドチェーン用

    # ── 推論 ───────────────────────────────────────────────
    def infer(self, features: list) -> list:
        """
        特徴量リストを渡してクラス確率を返す。
        features: [proc_anomaly, cpu_spike, net_bytes, file_change, mem_pressure]
                  すべて 0.0〜1.0
        """
        n_in  = len(features)
        arr   = (ctypes.c_float * n_in)(*features)
        n_out = ctypes.c_int(0)
        ptr   = self._api.lib.myln_infer(
            self._handle, arr, n_in, ctypes.byref(n_out)
        )
        return [ptr[i] for i in range(n_out.value)]

    def predict(self, features: list, classes: Optional[list] = None) -> str:
        """最も確率の高いクラス名を返す。"""
        labels = classes or self.SECURITY_CLASSES
        probs  = self.infer(features)
        return labels[probs.index(max(probs))]

    def predict_with_score(self, features: list, classes: Optional[list] = None):
        """(クラス名, 確率) のタプルを返す。"""
        labels = classes or self.SECURITY_CLASSES
        probs  = self.infer(features)
        best   = probs.index(max(probs))
        return labels[best], probs[best]

    # ── メタ情報 ───────────────────────────────────────────
    @property
    def tag(self)       -> str: return self._api.lib.myln_tag(self._handle).decode()
    @property
    def dim(self)       -> int: return self._api.lib.myln_dim(self._handle)
    @property
    def n_classes(self) -> int: return self._api.lib.myln_n_classes(self._handle)
    @property
    def version(self)   -> str: return self._api.version()

    def __repr__(self):
        return f"MylnFrame(tag={self.tag!r}, dim={self.dim}, classes={self.n_classes})"
