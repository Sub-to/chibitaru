#!/usr/bin/env python3
"""
🖥 ちびたるダッシュボード - sysinfo.py
==========================================
動かしているPCの体力を調べる。

Surface 3 のような非力な機械（Atom / メモリ4GB以下）では
自動的に「軽量モード」に落として、電池とCPUを節約する。
標準ライブラリだけで判定する（psutil は使わない）。
"""

import os
import platform
import subprocess


def total_ram_gb() -> float:
    """搭載メモリ(GB)。分からなければ 0.0 を返す。"""
    system = platform.system()
    try:
        if system == "Windows":
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return stat.ullTotalPhys / (1024 ** 3)

        if system == "Linux":
            with open("/proc/meminfo", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        return int(line.split()[1]) / (1024 ** 2)

        if system == "Darwin":
            out = subprocess.run(["sysctl", "-n", "hw.memsize"],
                                 capture_output=True, text=True, timeout=5)
            return int(out.stdout.strip()) / (1024 ** 3)
    except Exception:
        pass
    return 0.0


def cpu_name() -> str:
    """CPU名（取れる範囲で）。"""
    try:
        if platform.system() == "Windows":
            return os.environ.get("PROCESSOR_IDENTIFIER", platform.processor()) or ""
        if platform.system() == "Linux":
            with open("/proc/cpuinfo", encoding="utf-8") as f:
                for line in f:
                    if line.lower().startswith("model name"):
                        return line.split(":", 1)[1].strip()
        if platform.system() == "Darwin":
            out = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"],
                                 capture_output=True, text=True, timeout=5)
            return out.stdout.strip()
    except Exception:
        pass
    return platform.processor() or ""


# 非力なCPUの目印（Surface 3 の Atom x7-Z8700 など）
_WEAK_CPU_HINTS = ("atom", "celeron", "pentium", "silver n", "gold n",
                   "z8700", "z8500", "z3735", "cherry trail", "bay trail")


def probe() -> dict:
    """このPCの素性をまとめて返す。"""
    ram = total_ram_gb()
    cpu = cpu_name()
    cores = os.cpu_count() or 1
    weak_cpu = any(h in cpu.lower() for h in _WEAK_CPU_HINTS)

    # メモリ4.5GB未満、または非力CPU、または2コア以下 → 軽量モード
    light = (0 < ram < 4.5) or weak_cpu or cores <= 2

    return {
        "os":       f"{platform.system()} {platform.release()}",
        "cpu":      cpu or "不明",
        "cores":    cores,
        "ram_gb":   round(ram, 1) if ram else None,
        "weak_cpu": weak_cpu,
        "light":    light,
        "arch":     platform.machine(),
        "python":   platform.python_version(),
    }


def describe(info: dict) -> str:
    """起動時に1行で出す用。"""
    ram = f'{info["ram_gb"]}GB' if info["ram_gb"] else "メモリ不明"
    mode = "軽量モード" if info["light"] else "通常モード"
    return f'{info["os"]} / {info["cores"]}コア / {ram} → {mode}'


if __name__ == "__main__":
    i = probe()
    print(describe(i))
    for k, v in i.items():
        print(f"  {k:9} {v}")
