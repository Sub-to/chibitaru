# USB に入れて T440s で動かす

内蔵ディスクには触れず、USB メモリに Debian 13 を入れて
そこから起動する。元の環境はそのまま残る。

---

## 用意するもの

| | |
|---|---|
| 作業用 USB | 4GB 以上。インストーラを書き込む。中身は消える |
| 本命 USB | **32GB 以上・USB 3.0 必須**。ここが OS になる |
| T440s | 12GB 版なので 8g プロファイルになる |

**USB 3.0 は妥協しないこと。** USB 2.0 だと起動に何分もかかり、
使い物にならない。差し込み口が青いものを選ぶ。

T440s の USB 3.0 ポートは**左側面の 2 つ**。

---

## ① インストーラを作る（母艦で）

Debian 13 の netinst ISO を落とす。約 700MB。

```bash
curl -fLO https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/debian-13.1.0-amd64-netinst.iso
```

> 版が上がっていたら <https://www.debian.org/download> で最新を確認する。

### Raspberry Pi Imager で書く（おすすめ）

母艦に入っている 1.9.6 は `.iso` のカスタムイメージに対応している。
`dd` より安全 — 書き込み先が製品名と容量で出るので、内蔵ディスクと
取り違えにくい。書き込んだあとの検証もしてくれる。

1. Raspberry Pi Imager を起動
2. **「デバイスを選択」** — カスタムイメージなので何でもよい。
   フィルタなしのままで進む
3. **「OS を選択」** → 一番下までスクロール →
   **「カスタムイメージを使う」** → 落とした `.iso` を選ぶ
4. **「ストレージを選択」** → 本命 USB を選ぶ。
   製品名と容量（32GB など）で確認する
5. **「次へ」**
6. ⚠ **「OS カスタマイズ設定を適用しますか？」と聞かれたら
   必ず「いいえ」「設定を編集しない」を選ぶ**

   ここが唯一の落とし穴。Raspberry Pi 用の設定（Wi-Fi・ホスト名・
   SSH 鍵）を Debian の ISO に書き込むと壊れる。カスタムイメージなら
   本来聞かれないが、版によっては出る。

7. 書き込み → 検証まで待つ

### dd で書く場合

Imager を使わないなら、書き込み先を必ず確認してから。
**間違えると母艦のディスクが消える。**

```bash
lsblk -o NAME,SIZE,TYPE,TRAN,MOUNTPOINTS
```

`TRAN` が `usb` で、`SIZE` が挿した USB と一致する行を探す。
`nvme0n1` のような内蔵ディスクを選ばないこと。

```bash
sudo dd if=debian-13.1.0-amd64-netinst.iso of=/dev/sdX bs=4M status=progress oflag=sync
```

`/dev/sdX` は上で確かめた名前。`/dev/sdX1` のような数字付きではなく、
数字なしのほうを指定する。

---

## ② T440s を USB から起動する

1. T440s の電源を入れ、ThinkPad のロゴが出たら **F12**
   （反応しなければ、電源投入直後に **Enter** → メニューから F12）
2. 作業用 USB を選ぶ
3. **本命 USB もこの時点で挿しておく**

起動しない場合は **F1** で BIOS に入り:
- `Startup` → `UEFI/Legacy Boot` を `Both` に
- `Security` → `Secure Boot` を `Disabled` に

---

## ③ インストール

**ここが一番間違えやすい。** インストール先の選択だけは慎重に。

```
言語                  日本語
インストール先ディスク  ← ここ！
```

ディスク選択の画面で、**内蔵 SSD ではなく本命 USB を選ぶ**。
見分け方:

- 内蔵 SSD は `ATA` や `SAMSUNG` `INTEL` などの型番が出て、容量が 128GB/256GB
- USB は `USB` `SanDisk` `Kingston` などが出て、容量が 32GB/64GB

**容量で見分けるのが一番確実。** 迷ったら中断してよい。

続けて:

```
パーティション  → ガイド（ディスク全体を使う）
ソフトウェアの選択:
  □ Debian デスクトップ環境    ← チェックを外す
  □ GNOME                      ← 外す
  ■ SSH サーバー               ← 入れる
  ■ 標準システムユーティリティ  ← 入れる
```

デスクトップ環境は入れない。この OS が自前で持つ。

GRUB のインストール先を聞かれたら、**本命 USB を指定する**。
内蔵ディスクを選ぶと、USB を抜いた時に元の環境が起動しなくなる。

---

## ④ USB から起動して仕上げる

インストールが終わったら作業用 USB を抜いて再起動。
F12 で本命 USB を選ぶ。

ログインしたら:

```bash
sudo apt-get update && sudo apt-get install -y git
git clone https://github.com/Sub-to/chibitaru.git
cd chibitaru && git checkout os-v2
sudo bash install/setup.sh
```

10〜20 分かかる（USB の速度による）。終わったら再起動。

---

## ⑤ 確認する

再起動すると自動ログインして Vault シェルが出る。
SSH で入って中身を見る:

```bash
ssh ユーザー名@T440sのIP
```

```bash
# プロファイルは 8g になっているか
cat /etc/chibitaru/profile

# USB 対策が効いているか
findmnt -no OPTIONS /          # noatime があるか
systemd-analyze cat-config systemd/journald.conf | grep Storage

# zram
swapon --show

# 動画のハードウェアデコード ← T440s で一番見たいところ
vainfo | grep -E "driver|H264.*VLD"

# 実測
sudo python3 tools/measure.py
```

---

## 12GB を 4GB のふりをさせる

T440s は 12GB なので 8g プロファイルになる。
**4g プロファイルを実機で試したい場合**は、カーネルに嘘の搭載量を
伝えればよい。

`/etc/default/grub` の該当行に `mem=4G` を足す:

```
GRUB_CMDLINE_LINUX_DEFAULT="quiet mem=4G"
```

```bash
sudo update-grub && sudo reboot
```

戻すときは `mem=4G` を消して `update-grub` し直す。
これで**同じ実機のまま両方のプロファイルを検証できる**。

---

## T440s で特に見たいこと

VM では確かめられなかった部分。

| 見るもの | なぜ |
|---|---|
| `vainfo` の H.264 | Haswell は Gen7.5 なので `i965` が使われるはず。動画が GPU に降りるかは消費電力に直結する |
| whisper の所要時間 | Haswell は AVX2 を持つので現実的なはず。実際に何秒かかるか |
| USB 起動の体感 | 起動時間、アプリの立ち上がり。USB 3.0 でどこまで実用になるか |
| 消費電力 | RAPL が読める世代。`powerstat` や `/sys/class/powercap` で実測できる |

---

## うまくいかない時

**USB から起動しない**
BIOS で Secure Boot を無効に、UEFI/Legacy を Both に。

**画面が出ない（黒いまま）**
Ctrl+Alt+F2 で別のコンソールに移れる。移れたら labwc の問題:
```bash
journalctl --user -u labwc -b --no-pager | tail -30
cat ~/.local/share/labwc/*.log 2>/dev/null
```

**遅すぎる**
USB 2.0 ポートに挿さっている可能性がある。左側面の青い口に挿し直す。
```bash
lsblk -o NAME,TRAN,RM /dev/sdX   # 速度の確認は下で
udevadm info -q property -n /dev/sdX | grep -i speed
```

**元の環境に戻したい**
USB を抜いて再起動するだけ。内蔵ディスクには何も触れていない。
