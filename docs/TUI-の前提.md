# TUI シェルを書く前に（Phase 2 への申し送り）

VM の実画面で確かめた結果。ここを外すと画面が崩れる。

## 詰めるときは文字数ではなく表示幅で

`printf "%-14s"` は**文字数**で詰める。日本語は 1 文字で 2 桁を占めるので、
これで組むと右端が揃わない。実際に VM で 3 種類の幅にばらけた。

```python
import unicodedata

def dw(s):
    """端末上の表示幅。日本語と絵文字は 1 文字で 2 桁。"""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)

def pad(s, width, align="<"):
    fill = " " * max(0, width - dw(s))
    return s + fill if align == "<" else fill + s
```

`tools/measure.py` に同じものが入っている。TUI 側でも必ず使うこと。

## 絵文字は使ってよい（ただし条件つき）

最初は「絵文字が桁を壊す」と考えたが、**それは間違いだった**。
原因は bash の文字数詰めのほうで、表示幅で詰めれば絵文字も正しく揃う。
foot は絵文字を 2 桁として扱い、`east_asian_width` の判定と一致する。

ただし前提が二つある。

1. `fonts-noto-color-emoji` が要る。`fonts-noto-cjk` には絵文字が入っておらず、
   入れないと豆腐になる。豆腐は幅が変わるので桁も崩れる。
2. 端末が foot であること。絵文字の幅の扱いは端末ごとに違うので、
   別の端末に載せ替えるなら測り直す。

## 確認済みで安全なもの

VM の実画面で表示と桁揃えを確認した:

- ひらがな・カタカナ・漢字
- 罫線 `┌─┬─┐│├┼┤└┴┘`
- 記号 `▾ ▸ ▲ ● ○ ♪ × ÷ ≠ →`
- 絵文字 `🎤 🔵`（上の条件つき）

## 画面の作り

`labwc` は端末を装飾なしで全画面にする設定が入っている
（`install/setup.sh` の session 段）。窓を並べる用途がないため、
ペイン分割は TUI 自身が持つ。
