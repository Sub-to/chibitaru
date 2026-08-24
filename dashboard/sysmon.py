#!/usr/bin/env python3
"""
🖥 ちびたるダッシュボード - sysmon.py
==========================================
このPC自身の状態を見る（CPU・メモリ・ディスク・温度・消費電力・電池）。

Linuxでは /proc と /sys を直接読む。標準ライブラリのみ、外部コマンド不要。
読めないものは None を返すだけで、他の項目は普通に出す。

温度と電力は機種によって置き場所が違うので、候補を順に試す。
"""

import glob
import os
import platform
import shutil
import subprocess
import threading
import time
from pathlib import Path

_OS = platform.system()
_lock = threading.Lock()

# CPU使用率とRAPL電力は「前回との差分」で出すので、前回値を覚えておく
_prev_cpu: tuple[int, int] | None = None      # (idle, total)
_prev_rapl: tuple[float, int] | None = None   # (時刻, µJ)
_cache: dict = {}
_cache_at: float = 0.0
_MIN_INTERVAL = 0.7   # これより短い間隔で呼ばれたら前回値を使い回す


def _read(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return None


def _read_int(path: str) -> int | None:
    v = _read(path)
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# ─────────────────────────────────────────────
#  CPU
# ─────────────────────────────────────────────

def cpu() -> dict:
    """CPU使用率(%)・周波数(MHz)・ロードアベレージ。"""
    global _prev_cpu
    out = {"percent": None, "mhz": None, "load": None, "cores": os.cpu_count()}

    try:
        out["load"] = [round(x, 2) for x in os.getloadavg()]
    except (OSError, AttributeError):
        pass

    if _OS == "Linux":
        line = _read("/proc/stat")
        if line:
            parts = line.split("\n")[0].split()
            if parts and parts[0] == "cpu":
                vals = [int(x) for x in parts[1:] if x.isdigit()]
                if len(vals) >= 4:
                    idle = vals[3] + (vals[4] if len(vals) > 4 else 0)  # idle + iowait
                    total = sum(vals)
                    if _prev_cpu:
                        d_idle = idle - _prev_cpu[0]
                        d_total = total - _prev_cpu[1]
                        if d_total > 0:
                            out["percent"] = round(100 * (1 - d_idle / d_total), 1)
                    _prev_cpu = (idle, total)

        # 周波数（可変なので現在値。取れなければ /proc/cpuinfo から）
        khz = _read_int("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq")
        if khz:
            out["mhz"] = round(khz / 1000)
        else:
            info = _read("/proc/cpuinfo") or ""
            for l in info.split("\n"):
                if "cpu MHz" in l:
                    try:
                        out["mhz"] = round(float(l.split(":")[1]))
                    except (ValueError, IndexError):
                        pass
                    break

    return out


# ─────────────────────────────────────────────
#  メモリ / ディスク
# ─────────────────────────────────────────────

def memory() -> dict:
    """メモリ使用量(GB)と使用率。"""
    out = {"total": None, "used": None, "percent": None, "swap_percent": None}

    if _OS == "Linux":
        info = _read("/proc/meminfo")
        if info:
            kb = {}
            for line in info.split("\n"):
                if ":" in line:
                    k, v = line.split(":", 1)
                    num = v.strip().split()[0] if v.strip() else "0"
                    if num.isdigit():
                        kb[k] = int(num)
            total = kb.get("MemTotal", 0)
            avail = kb.get("MemAvailable", kb.get("MemFree", 0))
            if total:
                used = total - avail
                out["total"] = round(total / 1048576, 1)
                out["used"] = round(used / 1048576, 1)
                out["percent"] = round(100 * used / total, 1)
            sw_total = kb.get("SwapTotal", 0)
            if sw_total:
                sw_free = kb.get("SwapFree", 0)
                out["swap_percent"] = round(100 * (sw_total - sw_free) / sw_total, 1)
    else:
        try:  # macOS / Windows は概算でよい
            import ctypes
            if _OS == "Windows":
                import sysinfo
                total = sysinfo.total_ram_gb()
                out["total"] = round(total, 1)
        except Exception:
            pass

    return out


def disk(path: str = "/") -> dict:
    """ディスクの空き。"""
    try:
        u = shutil.disk_usage(path)
        return {
            "total":   round(u.total / 1073741824, 1),
            "used":    round(u.used / 1073741824, 1),
            "free":    round(u.free / 1073741824, 1),
            "percent": round(100 * u.used / u.total, 1) if u.total else None,
            "path":    path,
        }
    except Exception:
        return {"total": None, "used": None, "free": None, "percent": None, "path": path}


# ─────────────────────────────────────────────
#  温度
# ─────────────────────────────────────────────

# 拾いたいセンサー名（前にあるものほど優先）
_TEMP_PREFER = ("coretemp", "x86_pkg_temp", "k10temp", "cpu_thermal",
                "acpitz", "pch_", "soc")


def temperature() -> dict:
    """CPU温度(℃)。機種差があるので候補を順に探す。"""
    out = {"cpu": None, "source": None, "all": []}
    if _OS != "Linux":
        return out

    found: list[tuple[str, float]] = []

    # ① hwmon（coretemp など、いちばん正確）
    for d in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
        name = _read(f"{d}/name") or "hwmon"
        for f in sorted(glob.glob(f"{d}/temp*_input")):
            v = _read_int(f)
            if v is None:
                continue
            c = v / 1000.0
            if not (-20 < c < 150):     # 明らかにおかしい値は捨てる
                continue
            label = _read(f.replace("_input", "_label")) or name
            found.append((f"{name}:{label}", round(c, 1)))

    # ② thermal_zone（hwmonが無い機種向け）
    if not found:
        for d in sorted(glob.glob("/sys/class/thermal/thermal_zone*")):
            v = _read_int(f"{d}/temp")
            if v is None:
                continue
            c = v / 1000.0
            if not (-20 < c < 150):
                continue
            found.append((_read(f"{d}/type") or "thermal", round(c, 1)))

    if not found:
        return out

    out["all"] = [{"name": n, "c": c} for n, c in found[:8]]

    # 優先センサーがあればそれ、無ければ一番高い値を代表にする
    for pref in _TEMP_PREFER:
        for n, c in found:
            if pref in n.lower():
                out["cpu"], out["source"] = c, n
                return out
    n, c = max(found, key=lambda x: x[1])
    out["cpu"], out["source"] = c, n
    return out


# ─────────────────────────────────────────────
#  消費電力 / 電池
# ─────────────────────────────────────────────

def power() -> dict:
    """
    消費電力(W)と電池の状態。
    ① 電池の放電電力（いちばん現実的な「今の消費電力」）
    ② CPUパッケージ電力(RAPL) ※読める場合のみ
    """
    global _prev_rapl
    out = {"watt": None, "source": None, "battery": None,
           "status": None, "cpu_watt": None, "time_left": None}
    if _OS != "Linux":
        return out

    # ── 電池 ──
    for bat in sorted(glob.glob("/sys/class/power_supply/BAT*")):
        cap = _read_int(f"{bat}/capacity")
        status = _read(f"{bat}/status")
        if cap is not None:
            out["battery"] = cap
        if status:
            out["status"] = status

        # power_now は µW。無ければ 電流×電圧 で出す
        pw = _read_int(f"{bat}/power_now")
        if pw is None:
            cur = _read_int(f"{bat}/current_now")     # µA
            vol = _read_int(f"{bat}/voltage_now")     # µV
            if cur is not None and vol is not None:
                pw = abs(cur) * vol / 1_000_000       # → µW
        if pw:
            out["watt"] = round(abs(pw) / 1_000_000, 1)
            out["source"] = "電池"

            # 残り時間（放電中のみ）
            energy = _read_int(f"{bat}/energy_now")   # µWh
            if energy and out["watt"] and (status or "").lower() == "discharging":
                hours = (energy / 1_000_000) / out["watt"]
                out["time_left"] = f"{int(hours)}時間{int(hours % 1 * 60):02d}分"
        break

    # ── CPUパッケージ電力（RAPL）──
    # 新しめのカーネルでは root しか読めないことがある。読めたら出す。
    rapl = "/sys/class/powercap/intel-rapl:0/energy_uj"
    uj = _read_int(rapl)
    if uj is not None:
        now = time.time()
        if _prev_rapl:
            dt = now - _prev_rapl[0]
            duj = uj - _prev_rapl[1]
            if dt > 0 and duj >= 0:     # カウンタ一周時は捨てる
                out["cpu_watt"] = round(duj / 1_000_000 / dt, 1)
        _prev_rapl = (now, uj)
        if out["watt"] is None and out["cpu_watt"] is not None:
            out["watt"] = out["cpu_watt"]
            out["source"] = "CPU(RAPL)"

    return out


def uptime() -> str | None:
    """起動してからの時間。"""
    if _OS != "Linux":
        return None
    v = _read("/proc/uptime")
    try:
        sec = float(v.split()[0])
    except (AttributeError, ValueError, IndexError):
        return None
    d, rem = divmod(int(sec), 86400)
    h, m = divmod(rem // 60, 60)
    return f"{d}日{h}時間" if d else f"{h}時間{m}分"


# ─────────────────────────────────────────────
#  まとめ
# ─────────────────────────────────────────────

def snapshot() -> dict:
    """画面に出す一式。短時間に連続で呼ばれたら前回値を返す。"""
    global _cache, _cache_at
    with _lock:
        if _cache and (time.time() - _cache_at) < _MIN_INTERVAL:
            return _cache
        data = {
            "cpu":    cpu(),
            "memory": memory(),
            "disk":   disk("/"),
            "temp":   temperature(),
            "power":  power(),
            "uptime": uptime(),
            "os":     _OS,
        }
        _cache, _cache_at = data, time.time()
        return data


if __name__ == "__main__":
    import json
    snapshot()          # 1回目はCPU差分の基準づくり
    time.sleep(1.0)
    print(json.dumps(snapshot(), ensure_ascii=False, indent=2))
