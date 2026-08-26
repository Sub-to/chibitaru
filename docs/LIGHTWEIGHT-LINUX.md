# ⚡ 軽量Linuxモード

低スペックな Linux 機（古いノート PC、シンクライアント、ARM SBC、
メモリ 1〜2GB のミニ PC）で **チビタルを丸ごと動かす**ためのモードです。

LLM 版が必要とする **940MB の GGUF モデルも llama-server も使いません**。
必要なのは `python3` だけです。

---

## 1. LLM版と軽量版のちがい

| | LLM版（青い三連星） | ⚡ 軽量版（MYLN-FRAME） |
|---|---|---|
| 判定エンジン | Qwen2.5-1.5B × 3 プロセス | MYLN-FRAME |
| モデルファイル | 約 940MB 必要 | **不要** |
| llama-server | 必要（`bin/` に約 30MB のバイナリ） | **不要** |
| 追加の Python パッケージ | なし | **なし**（標準ライブラリのみ） |
| メモリ | 約 1.5〜2GB | **約 20MB** |
| 1イベントの判定時間 | 数秒 | **1ms 未満** |
| 起動待ち | 20秒（サーバ3基の起動待機） | **即時** |
| 判定の粒度 | 自然言語で理由を説明できる | 5段階レベルのみ |

判定結果の形式（`level` / `action` / `verdicts`）は両者で同一なので、
`response.py` から下はまったく同じように動きます。

---

## 2. 起動

```bash
bash start-lite.sh              # 常駐監視
bash start-lite.sh --once       # 1回だけスキャンして終了（cron 向き）
bash start-lite.sh --selftest   # 判定エンジンの動作確認
```

`start.sh` のメニューからは **`5`** を選んでも同じです。

---

## 3. バックエンドの選び方

軽量モードは 3 段構えで、使えるものを自動で選びます。

```
1. native  aoko/lib/libmyln.so   ビルド済み C 実装（最速）
      ↓ 無ければ
2. python  aoko/myln_py.py       純Python互換コア（依存ゼロ・どこでも動く）
      ↓ 明示指定した時だけ
3. llm     aoko/conductor.py     Qwen2.5×3（要 llama-server + モデル）
```

現状 `aoko/lib/` に入っているのは **macOS arm64 用の `libmyln.dylib` だけ**です。
そのため Linux では自動的に **2 の純Pythonコア**が使われます。
`libmyln.so` をビルドして `aoko/lib/` に置けば、次回から 1 が使われます。

環境変数で明示指定もできます。

```bash
CHIBITARU_ENGINE=auto   bash start-lite.sh   # 既定。native → python
CHIBITARU_ENGINE=python bash start-lite.sh   # 純Pythonコアを強制
CHIBITARU_ENGINE=native bash start-lite.sh   # ビルド済みライブラリを要求
CHIBITARU_ENGINE=llm    python3 aoko/monitor.py   # LLM版を使う
```

> **注意**: 純Pythonコアは C 実装とは別実装です。
> 5段階のレベル判定が一致するようにチューニングしていますが、
> 確率値そのものはビット単位では一致しません。

---

## 4. 判定ロジック

`feature_extractor.py` がイベントを 5 次元ベクトルに変換し、
`myln_py.py` がそれを 0.0〜1.0 の危険度スコアへ畳み込みます。

```
[proc_anomaly, cpu_spike, net_bytes, file_change, mem_pressure]
       ↓  重み付き和（file 0.32 / proc 0.26 / net 0.22 / cpu 0.10 / mem 0.10）
       ↓  ＋ 同時に立った指標の数によるボーナス
   危険度スコア 0.0 〜 1.0
       ↓  最も近いクラス中心へ割り当て
 SAFE / LOW / MEDIUM / HIGH / CRITICAL
```

「同時に立った指標の数」で加点するのが要点です。
指標が 1 つだけ跳ねた場合（よくある誤検知）は加点されず、
複数の指標が連動した場合（本物の攻撃の特徴）だけスコアが伸びます。

実測値：

| イベント | スコア | 判定 |
|---|---|---|
| 平常時 | 0.000 | ✅ SAFE |
| 不審プロセス | 0.318 | 🟡 MEDIUM |
| バックドアポート通信 | 0.403 | 🟡 MEDIUM |
| Vault 大量変更（38件） | 0.534 | 🔴 HIGH |
| ランサムウェア | 1.000 | 💀 CRITICAL |

---

## 5. 常駐させる

### systemd がある場合（Arch / CachyOS / Debian / Ubuntu / Fedora）

```bash
bash install/install.sh     # → 3 を選択
systemctl --user daemon-reload
systemctl --user enable --now chibitaru-lite
journalctl --user -u chibitaru-lite -f
```

### systemd が無い場合（Alpine / OpenRC / 極小構成）

`crontab -e` に以下を追加します。

```cron
*/5 * * * * CHIBITARU_ENGINE=auto python3 /path/to/chibitaru/aoko/monitor.py --once >> /tmp/chibitaru.log 2>&1
```

---

## 6. 依存パッケージ

必須は `python3` のみです。以下は**無くても動きます**（機能が縮退するだけ）。

| コマンド | 用途 | 無い場合 |
|---|---|---|
| `notify-send` | デスクトップ通知 | `kdialog` → `zenity` → コンソール出力の順に代替 |
| `nmcli` / `ip` / `rfkill` | CRITICAL 時のネット切断 | 切断は行わず通知のみ |
| `ps` / `netstat` | プロセス・通信の監視 | そのチェックのみスキップ |
| `clamscan` | ウイルススキャン | メニューの `2` が使えない |

インストール例：

```bash
# Debian / Ubuntu
sudo apt install python3 libnotify-bin net-tools

# Arch / CachyOS
sudo pacman -S python libnotify net-tools

# Alpine
sudo apk add python3 libnotify net-tools
```

---

## 7. テスト

外部依存なしで実行できます。

```bash
python3 -m unittest discover -s tests -v
```

---

## 8. 困ったとき

**`[MYLN] ⚠️ python 起動失敗`**
→ `aoko/myln_py.py` が見つかっていません。リポジトリごとコピーしたか確認してください。

**`[MYLN] ⏭️ CHIBITARU_ENGINE=llm のため...`**
→ 環境変数が残っています。`unset CHIBITARU_ENGINE` してください。

**判定が厳しすぎる／緩すぎる**
→ `aoko/myln_py.py` の `_WEIGHTS`（特徴量の重み）と `_CENTERS`（クラス中心）を調整します。
変更後は `python3 tests/test_lite.py` で挙動を確認してください。

**Vault が読めなくなった**
→ HIGH 検知時の保護が掛かっています。解除：

```bash
python3 -c "import sys; sys.path.insert(0,'aoko'); import response; response.restore_vault_writable()"
```
