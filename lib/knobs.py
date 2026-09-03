#!/usr/bin/env python3
"""
設定の目録 — この機体で触れるものを一枚の表にする。

ここに一行足せば、その設定は声でも文字でも画面からでも触れるように
なる。判定（何を言われたか）と実行（どう変えるか）を別の場所に書くと
片方だけ増えて食い違う。実際そうなっていた —— 音量は声で変えられる
のに配色は変えられず、電池は画面が 2 本合算するのに声は 1 本しか
見ていなかった（T440s は電池を 2 つ持つ）。

読めなかった時は None を返す。0 を返してはいけない。「測れなかった」
を「ゼロだった」として扱うと、動いているものを壊れていると誤診する。
この落とし穴には何度も落ちた。
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


# ── 道具 ──────────────────────────────────────────────────
def sh(*args: str, timeout: int = 5) -> tuple[int, str]:
    """外を呼ぶ。無ければ 127 を返す（0 ではなく）。"""
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or p.stderr).strip()
    except FileNotFoundError:
        return 127, f"{args[0]} がありません"
    except subprocess.SubprocessError as e:
        return 1, str(e)


def read_first(path, default=None):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return default


# ── 音量 ──────────────────────────────────────────────────
def volume_get() -> int | None:
    rc, out = sh("wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@")
    if rc != 0:
        return None
    try:
        return round(float(out.split()[1]) * 100)
    except (IndexError, ValueError):
        return None


def volume_set(v: int) -> tuple[bool, str]:
    # 音を消したまま音量だけ上げても鳴らない。上げるなら消音も解く。
    sh("wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0")
    rc, err = sh("wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{v}%")
    return (True, f"音量を {v}% にしました") if rc == 0 else (False, f"変えられませんでした（{err}）")


def mute_set(on: bool) -> tuple[bool, str]:
    rc, err = sh("wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1" if on else "0")
    if rc != 0:
        return False, f"変えられませんでした（{err}）"
    return True, "音を消しました" if on else "音を戻しました"


# ── 画面の明るさ ──────────────────────────────────────────
def _backlight() -> Path | None:
    """
    明るさを持つ口を選ぶ。acpi_video0 と intel_backlight が両方ある
    機体では、段階の多いほう（＝実際のハードを触っているほう）を採る。
    名前で決め打ちすると機体が変わった時に外す。
    """
    best, best_max = None, 0
    for d in Path("/sys/class/backlight").glob("*"):
        raw = read_first(d / "max_brightness")
        if not raw:
            continue
        try:
            mx = int(raw)
        except ValueError:
            continue
        if mx > best_max:
            best, best_max = d, mx
    return best


def brightness_get() -> int | None:
    d = _backlight()
    if d is None:
        return None
    cur, mx = read_first(d / "brightness"), read_first(d / "max_brightness")
    try:
        cur, mx = int(cur), int(mx)
    except (TypeError, ValueError):
        return None
    return round(100 * cur / mx) if mx > 0 else None


def brightness_set(v: int) -> tuple[bool, str]:
    d = _backlight()
    if d is None:
        return False, "明るさを変えられる画面がありません"
    try:
        mx = int(read_first(d / "max_brightness"))
    except (TypeError, ValueError):
        return False, "明るさの段階を読めませんでした"
    # 0 にしない。真っ暗になると、明るさを戻す操作そのものが見えなくなる。
    raw = max(1, round(mx * v / 100))
    try:
        (d / "brightness").write_text(str(raw))
    except OSError:
        return False, "明るさを書き換える許可がありません"
    return True, f"明るさを {v}% にしました"


# ── 計器（見るだけ） ──────────────────────────────────────
def battery() -> tuple[int | None, float | None, str]:
    """
    残量(%)・電圧(V)・状態。

    T440s は電池を 2 つ持つ（内蔵と着脱式）。合算して 1 つに見せる。
    片方だけ見ると「98%」と出ているのに急に切れる、ということが起きる。
    """
    total_now = total_full = 0
    volts, status = [], []
    for b in sorted(Path("/sys/class/power_supply").glob("BAT*")):
        now = read_first(b / "energy_now") or read_first(b / "charge_now")
        full = read_first(b / "energy_full") or read_first(b / "charge_full")
        if now and full:
            total_now += int(now)
            total_full += int(full)
        v = read_first(b / "voltage_now")
        if v:
            volts.append(int(v) / 1e6)
        s = read_first(b / "status")
        if s:
            status.append(s)

    pct = round(100 * total_now / total_full) if total_full else None
    volt = max(volts) if volts else None
    if any(s == "Charging" for s in status):
        mark = "充電"
    elif read_first("/sys/class/power_supply/AC/online") == "1":
        mark = "電源"
    else:
        mark = "電池"
    return pct, volt, mark


def wifi() -> tuple[str | None, int | None]:
    """
    つないでいる口の名前と、電波の強さ(0〜100%)。

    dBm をそのまま出すと -48 のような負の数になり、良いのか悪いのか
    分かりにくい。カーネルが出す品質値（0〜70）を割合に直して返す。
    """
    try:
        lines = Path("/proc/net/wireless").read_text().splitlines()[2:]
    except OSError:
        return None, None
    for line in lines:
        parts = line.split()
        if len(parts) < 4:
            continue
        try:
            quality = float(parts[2].rstrip("."))
            level = float(parts[3].rstrip("."))
        except ValueError:
            continue
        # 圏外は 0 や -256 が出る。つないでいないものは出さない。
        if level in (0, -256) or quality <= 0:
            continue
        return parts[0].rstrip(":"), max(0, min(100, round(quality / 70 * 100)))
    return None, None


def temperature() -> int | None:
    """一番熱いところ。どのセンサが CPU かは機体で違うので最大を採る。"""
    temps = []
    for z in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
        v = read_first(z)
        if v:
            try:
                t = int(v) / 1000
                if 0 < t < 150:      # 明らかに嘘の値は捨てる
                    temps.append(t)
            except ValueError:
                pass
    return round(max(temps)) if temps else None


def memory() -> tuple[float, float]:
    """使用量と搭載量を GB で。"""
    info = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            k, _, v = line.partition(":")
            info[k] = int(v.split()[0])
    except (OSError, ValueError):
        return 0.0, 0.0
    return ((info.get("MemTotal", 0) - info.get("MemAvailable", 0)) / 1048576,
            info.get("MemTotal", 0) / 1048576)


def disk_free() -> int | None:
    """入れものの空き(%)。"""
    try:
        st = __import__("os").statvfs("/")
    except OSError:
        return None
    if st.f_blocks <= 0:
        return None
    return round(100 * st.f_bavail / st.f_blocks)


# ── 見た目（chibitaru-theme に任せる） ────────────────────
SYS_THEME = Path("/etc/chibitaru/theme")


def user_theme() -> Path:
    """その人の好み。機械ぜんたいの既定（/etc）より優先する。"""
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / "chibitaru" / "theme"


def _theme_conf(key: str, default: str) -> str:
    # 既定を読んでから好みで上書き。順番を逆にすると、変えたはずの
    # 設定が古いまま見える。
    value = default
    for path in (SYS_THEME, user_theme()):
        for line in (read_first(path) or "").splitlines():
            k, _, v = line.partition("=")
            if k.strip() == key and v.strip():
                value = v.strip()
    return value


def theme_get() -> str:
    return _theme_conf("CHIBITARU_THEME", "mocha")


def _theme_cmd(*args: str) -> tuple[int, str]:
    """
    見た目を変える。特権は要らない。

    設定はその人の ~/.config に書き、画面は自分で立てた labwc を
    畳むだけで立ち上がり直す。ここに sudo を挟んでいた時期があるが、
    合言葉を聞き返されて画面の中で入力待ちのまま固まった。
    声で操る画面では、特権が要る作りそのものが穴になる。
    """
    return sh("chibitaru-theme", *args, timeout=25)


def theme_set(name: str) -> tuple[bool, str]:
    if name not in BY_KEY["theme"].choices:
        return False, f"配色は {' か '.join(BY_KEY['theme'].choices)} です"
    rc, err = _theme_cmd(name, "--apply")
    return (True, f"配色を {name} にしました") if rc == 0 else (False, f"変えられませんでした（{err}）")


def font_get() -> int | None:
    try:
        return int(_theme_conf("CHIBITARU_FONT_SIZE", "14"))
    except ValueError:
        return None


def font_set(size: int) -> tuple[bool, str]:
    rc, err = _theme_cmd("--size", str(size), "--apply")
    return (True, f"文字の大きさを {size} にしました") if rc == 0 else (False, f"変えられませんでした（{err}）")


# ══════════════════════════════════════════════════════════
@dataclass
class Knob:
    """
    触れるもの、ひとつ分。

    words は「その言葉が出たらこれのこと」という手がかり。声から拾う
    ときにも、Qwen に何が触れるか教えるときにも同じものを使う。
    二重に持つと、片方だけ増えて食い違う。
    """
    key: str
    label: str                       # 画面と声に出す名前
    words: tuple[str, ...]           # こう言われたらこれ
    kind: str                        # percent / choice / gauge / danger
    get: Callable | None = None
    set: Callable | None = None
    choices: tuple[str, ...] = ()
    # 選ぶものの言い換え。「緑にして」で fallout に届くように。
    # 正式な名前だけを見ていると、人は正式な名前で呼ばない。
    aliases: dict = field(default_factory=dict)
    lo: int = 0
    hi: int = 100
    step: int = 10                   # 「上げて」で動く幅
    unit: str = "%"
    confirm: bool = False            # 声では実行せず、押させる


CATALOG: list[Knob] = [
    # ── 危ないもの。声では実行しない ──
    Knob("power", "電源", ("電源", "でんげん", "シャットダウン", "終了して", "切って"),
         "danger", confirm=True),
    Knob("reboot", "再起動", ("再起動", "リブート", "立ち上げ直"),
         "danger", confirm=True),

    # ── 変えられるもの ──
    # 「温度」「湿度」は音量の聞き間違い。温度は変えられないので
    # 音量に寄せる。実機で whisper が実際にそう間違えた。
    Knob("volume", "音量",
         ("音量", "ボリューム", "ボリウム", "音を", "音が", "ミュート",
          "うるさ", "聞こえ", "温度を", "おんど", "湿度"),
         "percent", volume_get, volume_set, step=10),
    # 「明るさ」だけでは「明るくして」を拾えない。活用する語は
    # 語幹で持つ。実機で「明るくして」が素通りした。
    Knob("brightness", "明るさ",
         ("明る", "あかる", "輝度", "画面を", "まぶし", "暗く", "くらく", "照度"),
         "percent", brightness_get, brightness_set, step=15),
    Knob("theme", "配色", ("配色", "色", "テーマ", "はいしょく"),
         "choice", theme_get, theme_set,
         choices=("mocha", "latte", "fallout"), unit="",
         aliases={
             "mocha":   ("濃い", "暗い", "夜", "青", "モカ"),
             "latte":   ("薄い", "明るい", "昼", "白", "ラテ"),
             "fallout": ("緑", "みどり", "蛍光", "フォールアウト", "廃墟"),
         }),
    Knob("font", "文字の大きさ", ("文字", "フォント", "大きさ"),
         "percent", font_get, font_set, lo=10, hi=24, step=2, unit=""),

    # ── 見るだけ ──
    Knob("battery", "電池", ("電池", "バッテリ", "残り"), "gauge",
         lambda: battery()[0]),
    Knob("wifi", "電波", ("電波", "wifi", "ワイファイ", "つながっ"), "gauge",
         lambda: wifi()[1]),
    Knob("temp", "温度", ("熱", "温度"), "gauge", temperature, unit="°"),
    Knob("mem", "記憶", ("記憶", "メモリ", "空き"), "gauge",
         lambda: (lambda u, t: round(100 * u / t) if t else None)(*memory())),
    Knob("disk", "入れもの", ("入れもの", "ディスク", "容量"), "gauge", disk_free),
]

BY_KEY = {k.key: k for k in CATALOG}


def find(text: str) -> Knob | None:
    """言われた文から、どれのことか探す。上から順に、最初に当たったもの。"""
    for k in CATALOG:
        for w in k.words:
            if w in text:
                return k
    return None


def fmt(k: Knob) -> str:
    """いまの値を人が読む形に。読めなかった時は「──」で、0 と区別する。"""
    if k.kind == "danger":
        return "確認が要る"
    if k.get is None:
        return "──"
    v = k.get()
    return "──" if v is None else f"{v}{k.unit}"


def apply(k: Knob, text: str) -> tuple[int, str]:
    """
    言われた文のとおりに動かす。

    画面からも声からもここを通す。「上げて」の解釈を二箇所に書くと、
    片方だけ直して食い違う。実際そうなっていた。
    """
    if k.kind == "danger":
        return 3, f"{k.label}は押して確かめてください"
    if k.set is None:
        return 0, f"{k.label}は {fmt(k)} です（見るだけ）"

    if k.kind == "choice":
        for c in k.choices:
            # 正式な名前が先。言い換えは、名前で当たらなかった時だけ見る。
            if c in text or any(a in text for a in k.aliases.get(c, ())):
                ok, msg = k.set(c)
                return (0 if ok else 1), msg
        return 4, f"{k.label}は {'/'.join(k.choices)} から選んでください"

    now = k.get() if k.get else None

    m = re.search(r"(\d{1,3})", text)
    if m:
        target = int(m.group(1))
    elif re.search(r"(最大|いっぱい|全開)", text):
        target = k.hi
    elif re.search(r"(最小|最低)", text):
        target = k.lo
    elif k.key == "volume" and re.search(r"(消して|ミュート|黙)", text):
        ok, msg = mute_set(True)
        return (0 if ok else 1), msg
    else:
        if now is None:
            return 1, f"{k.label}を読めませんでした"
        # 「もっと」と言われたら大きく動かす。同じ幅しか動かないと
        # 言い直しても変わらず、伝わっていないように感じる。
        step = k.step * 2 if re.search(r"(もっと|ずっと|かなり|うんと)", text) else k.step
        if re.search(r"(上げ|大きく|でかく|あげ|明るく|強く)", text):
            if now >= k.hi:
                return 0, f"{k.label}はもう最大です"
            target = min(k.hi, now + step)
        elif re.search(r"(下げ|小さく|さげ|抑え|暗く|弱く)", text):
            if now <= k.lo:
                return 0, f"{k.label}はもう最小です"
            target = max(k.lo, now - step)
        else:
            return 0, f"いまの{k.label}は {fmt(k)} です"

    target = max(k.lo, min(k.hi, target))
    ok, msg = k.set(target)
    return (0 if ok else 1), msg


def describe() -> str:
    """
    いま触れるものの一覧を文にする。Qwen に渡す説明も、人が見る一覧も
    ここから作る。表と説明を別々に書くと、必ずどちらかが古くなる。
    """
    rows = []
    for k in CATALOG:
        if k.kind == "danger":
            rows.append(f"{k.key}\t{k.label}\t確認が要る")
        elif k.kind == "choice":
            rows.append(f"{k.key}\t{k.label}\t{'/'.join(k.choices)}")
        elif k.kind == "gauge":
            rows.append(f"{k.key}\t{k.label}\t見るだけ")
        else:
            rows.append(f"{k.key}\t{k.label}\t{k.lo}〜{k.hi}{k.unit}")
    return "\n".join(rows)
