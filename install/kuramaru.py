#!/usr/bin/env python3
"""
蔵丸（くらまる）- Obsidian Vault 守護エージェント
===================================================
禁書庫を常に巡回し、品質問題を検出・報告・修正提案を行う守護者。

機能:
  1. Vault 全体スキャン（起動時 + 定期）
  2. ファイル変更監視（watchdog によるリアルタイム）
  3. 品質チェック:
       - フロントマター不完全
       - 壊れた Wikiリンク
       - 孤立ノート（どこからもリンクされていない）
       - inbox 滞留ファイル（X日以上）
       - MOC 未登録ノート
  4. レポート生成 → inbox/蔵丸レポート.md
  5. Claude API による自動修正提案（オプション）

使い方:
  python3 蔵丸.py                   # 一回スキャン＋レポート
  python3 蔵丸.py --watch           # 常駐監視モード
  python3 蔵丸.py --watch --fix     # 常駐 + Claude API 自動修正
  python3 蔵丸.py --scan-only       # スキャンのみ（レポート非生成）
"""

import os
import re
import sys
import time
import shutil
import argparse
import datetime
import subprocess
import configparser
import urllib.request
import urllib.error
import json
from pathlib import Path
from typing import Optional

# ─── 設定 ─────────────────────────────────────────────────────────────────────

CONFIG_FILE = Path(__file__).parent / "config.ini"
cfg = configparser.ConfigParser()
if CONFIG_FILE.exists():
    cfg.read(str(CONFIG_FILE), encoding="utf-8")

VAULT_PATH       = Path(cfg.get("vault", "path", fallback=str(Path.home() / "Ofsaver1")))
REPORT_PATH      = VAULT_PATH / "inbox" / "蔵丸レポート.md"
SCAN_INTERVAL    = 300          # 定期スキャン間隔（秒）
INBOX_STALE_DAYS = 5            # inbox 滞留と見なす日数
IGNORE_DIRS      = {".obsidian", ".claude", "__pycache__", ".git"}
IGNORE_FILES     = {"蔵丸レポート.md"}   # スキャン対象から除外するファイル名

PDF_IMPORT_SCRIPT = Path(__file__).parent / "pdf_import_ljp.py"
PYTHON_BIN        = "/opt/homebrew/bin/python3"

# 必須フロントマターフィールド（どれか1つあればOK）
REQUIRED_TITLE  = {"タイトル", "title"}
REQUIRED_DATE   = {"作成日", "date", "日付"}
REQUIRED_TAGS   = {"タグ", "tags"}

# MOC と対応ドメインフォルダのマッピング
MOC_MAP = {
    "MOC/テクノロジーMOC.md":         "ノート/テクノロジー",
    "MOC/化学MOC.md":                 "ノート/化学",
    "MOC/歴史MOC.md":                 "ノート/歴史",
    "MOC/眼鏡学MOC.md":               "ノート/眼鏡学",
    "MOC/振り返りMOC.md":             "振り返り",
    "MOC/ニュースMOC.md":             "ニュース",
}

# 望丸設定
NOZOMARU_DIR      = VAULT_PATH / "望丸" / "世界情勢"
NOZOMARU_MOC      = VAULT_PATH / "望丸" / "蔵丸管理" / "MOC_世界情勢.md"
NOZOMARU_BACKLINK = "望丸/蔵丸管理/MOC_世界情勢"
NOZOMARU_ALERT    = VAULT_PATH / "望丸" / "蔵丸管理" / "高重要度アラート.md"

# bosai.go.jp 防災監視設定
BOSAI_REPORT_PATH = VAULT_PATH / "望丸" / "蔵丸管理" / "防災アラート.md"
BOSAI_CHECK_INTERVAL = 600   # 10分ごとにチェック
JMA_EQ_API   = "https://www.jma.go.jp/bosai/quake/data/list.json"
JMA_WARN_API = "https://www.jma.go.jp/bosai/warning/data/warning/011000.json"  # 全国警報

# ─── ドメイン自動判定ルール ───────────────────────────────────────────────────
DOMAIN_RULES = {
    "眼鏡学": ["眼鏡", "視機能", "コンタクト", "検眼", "オプトメトリー",
               "レンズ", "視力", "屈折", "調節", "両眼視", "VT"],
    "テクノロジー": ["MSX", "PC", "AI", "LLM", "Arduino", "ESP32",
                    "プログラム", "ソフト", "コード", "Python", "Linux",
                    "ランドセル", "機械学習"],
    "歴史": ["歴史", "史", "古代", "江戸", "明治", "大正", "昭和"],
    "化学": ["化学", "分子", "元素", "反応", "有機", "無機"],
    "趣味": ["FFXI", "ファイナルファンタジー", "ゲーム", "鉄道",
             "アニメ", "音楽", "Black Mage", "Mage"],
}

# ドメイン → 保存先フォルダ
DOMAIN_DEST = {
    "眼鏡学":    "ノート/眼鏡学",
    "テクノロジー": "ノート/テクノロジー",
    "歴史":      "ノート/歴史",
    "化学":      "ノート/化学",
    "趣味":      "趣味",
    "書籍":      "参考資料/書籍",
    "未分類":    "参考資料",
}

# ─── inbox 自動処理 ───────────────────────────────────────────────────────────

class InboxProcessor:
    """
    inbox に投入されたファイルを自動で振り分け・処理する。

    対応:
      .pdf       → LJP で自動インポート → ノート生成
      フォルダ   → 内容・名前からドメイン判定 → 適切なフォルダへ移動
      .txt       → ドメイン判定 → 参考資料/書籍/ または趣味/ へ移動
      .md        → フロントマター解析 → 適切なフォルダへ移動
      その他     → ドメイン判定 → 参考資料/ へ移動
    """

    def __init__(self):
        self.log: list[str] = []

    def detect_domain(self, name: str, content: str = "") -> str:
        """ファイル名・内容のキーワードからドメインを推測。"""
        text = (name + " " + content[:500]).lower()
        for domain, keywords in DOMAIN_RULES.items():
            if any(k.lower() in text for k in keywords):
                return domain
        return "未分類"

    def dest_path(self, domain: str, name: str) -> Path:
        """保存先フォルダを返す。"""
        folder = DOMAIN_DEST.get(domain, "参考資料")
        dest = VAULT_PATH / folder
        dest.mkdir(parents=True, exist_ok=True)
        return dest / name

    def _log(self, msg: str):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        print(f"  [蔵丸 📦] {msg}", flush=True)
        self.log.append(line)

    # ── PDF ──────────────────────────────────────────────────────────────────

    def process_pdf(self, path: Path):
        """PDF を pdf_import_ljp.py で処理してノートを自動生成。"""
        self._log(f"PDF 検出: {path.name} → LJP インポート開始...")
        if not PDF_IMPORT_SCRIPT.exists():
            self._log(f"⚠️ pdf_import_ljp.py が見つかりません: {PDF_IMPORT_SCRIPT}")
            return

        try:
            result = subprocess.run(
                [PYTHON_BIN, str(PDF_IMPORT_SCRIPT), str(path)],
                capture_output=True, text=True, timeout=900,  # LJPモデルロード込みで最大15分
            )
            if result.returncode == 0:
                self._log(f"✅ PDF インポート完了: {path.name}")
                # インポート成功後、PDF を参考資料/書籍/ に移動
                domain = self.detect_domain(path.stem)
                dest = VAULT_PATH / "参考資料" / "書籍" / path.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(path), str(dest))
                self._log(f"📁 PDF を移動: 参考資料/書籍/{path.name}")
            else:
                self._log(f"❌ PDF インポート失敗: {path.name}\n{result.stderr[:200]}")
        except subprocess.TimeoutExpired:
            self._log(f"⏱️ PDF インポートタイムアウト: {path.name}")
        except Exception as e:
            self._log(f"❌ PDF 処理エラー: {e}")

    # ── フォルダ ──────────────────────────────────────────────────────────────

    def process_folder(self, path: Path):
        """フォルダを内容・名前から判定して移動。"""
        # viz_ 画像フォルダ（PDFスキャン結果）
        imgs = list(path.glob("viz_*.jpg")) + list(path.glob("viz_*.png"))
        if imgs:
            dest_base = VAULT_PATH / "眼鏡学" / "スキャン"
            dest_base.mkdir(parents=True, exist_ok=True)
            dest = dest_base / path.name
            shutil.move(str(path), str(dest))
            self._log(f"✅ スキャン画像フォルダ → 眼鏡学/スキャン/{path.name}")
            return

        # その他フォルダ → ドメイン判定して書籍フォルダへ
        domain = self.detect_domain(path.name)
        if domain in ("テクノロジー", "未分類"):
            dest_base = VAULT_PATH / "参考資料" / "書籍"
        else:
            dest_base = VAULT_PATH / DOMAIN_DEST.get(domain, "参考資料")
        dest_base.mkdir(parents=True, exist_ok=True)
        dest = dest_base / path.name
        shutil.move(str(path), str(dest))
        self._log(f"✅ フォルダ移動: {path.name} → {dest.relative_to(VAULT_PATH)}")

    # ── テキスト ──────────────────────────────────────────────────────────────

    def process_txt(self, path: Path):
        """テキストファイルをドメイン判定して移動。"""
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            content = ""
        domain = self.detect_domain(path.stem, content)

        if domain == "趣味":
            dest = VAULT_PATH / "趣味" / path.name
        else:
            dest_base = VAULT_PATH / "参考資料" / "書籍"
            dest_base.mkdir(parents=True, exist_ok=True)
            dest = dest_base / path.name

        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(dest))
        self._log(f"✅ テキスト移動: {path.name} → {dest.relative_to(VAULT_PATH)}")

    # ── Markdown ──────────────────────────────────────────────────────────────

    def process_md(self, path: Path):
        """Markdown をフロントマター解析して適切なフォルダへ移動。"""
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            text = ""
        meta = parse_frontmatter(text)

        # ドメインフィールドから判定
        domain = meta.get("ドメイン", meta.get("domain", ""))
        if not domain:
            domain = self.detect_domain(path.stem, text)

        dest_folder = DOMAIN_DEST.get(domain, "参考資料")
        dest = VAULT_PATH / dest_folder / path.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(dest))
        self._log(f"✅ ノート移動: {path.name} → {dest.relative_to(VAULT_PATH)}")

    # ── メイン処理 ────────────────────────────────────────────────────────────

    def process(self, path: Path):
        """パスの種別を判定して適切な処理を呼び出す。"""
        # 蔵丸レポートは除外
        if path.name == "蔵丸レポート.md":
            return
        # 隠しファイルは除外
        if path.name.startswith("."):
            return

        self._log(f"新着: {path.name}")

        if path.is_dir():
            self.process_folder(path)
        elif path.suffix.lower() == ".pdf":
            self.process_pdf(path)
        elif path.suffix.lower() == ".txt":
            self.process_txt(path)
        elif path.suffix.lower() == ".md":
            self.process_md(path)
        else:
            # その他：ドメイン判定して参考資料へ
            domain = self.detect_domain(path.stem)
            dest_base = VAULT_PATH / DOMAIN_DEST.get(domain, "参考資料")
            dest_base.mkdir(parents=True, exist_ok=True)
            dest = dest_base / path.name
            shutil.move(str(path), str(dest))
            self._log(f"✅ その他ファイル移動: {path.name} → {dest.relative_to(VAULT_PATH)}")

    def process_all_inbox(self):
        """inbox 内の全ファイル・フォルダを一括処理。"""
        inbox = VAULT_PATH / "inbox"
        if not inbox.exists():
            return
        items = [p for p in inbox.iterdir()
                 if not p.name.startswith(".") and p.name != "蔵丸レポート.md"]
        if not items:
            return
        self._log(f"inbox に {len(items)}件 → 一括処理開始")
        for item in items:
            try:
                self.process(item)
            except Exception as e:
                self._log(f"❌ 処理エラー ({item.name}): {e}")

    def append_to_report(self):
        """処理ログをレポートに追記。"""
        if not self.log or not REPORT_PATH.exists():
            return
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        addition = f"\n\n## 📦 蔵丸 自動処理ログ（{ts}）\n"
        addition += "\n".join(f"- {l}" for l in self.log)
        addition += "\n"
        with open(REPORT_PATH, "a", encoding="utf-8") as f:
            f.write(addition)


# ─── 問題クラス ───────────────────────────────────────────────────────────────

class Issue:
    FAIL = "FAIL"
    WARN = "WARN"
    INFO = "INFO"

    ICONS = {FAIL: "🔴", WARN: "🟡", INFO: "🔵"}

    def __init__(self, level: str, check: str, path: str, detail: str):
        self.level  = level
        self.check  = check
        self.path   = path
        self.detail = detail

    def __repr__(self):
        icon = self.ICONS.get(self.level, "⚪")
        return f"{icon} [{self.check}] {self.path}\n     → {self.detail}"


# ─── ユーティリティ ──────────────────────────────────────────────────────────

def parse_frontmatter(text: str) -> dict:
    """YAML フロントマターを辞書として返す。なければ空辞書。"""
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        return {}
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip().lower()] = v.strip()
    return meta


def extract_wikilinks(text: str) -> list[str]:
    """[[...]] 形式のリンクをすべて抽出する。"""
    return re.findall(r"\[\[([^\]|#]+?)(?:\|[^\]]+)?\]\]", text)


def get_all_md_files() -> list[Path]:
    """Vault 内の全 .md ファイルを返す（除外ディレクトリ・ファイルを除く）。"""
    files = []
    for f in VAULT_PATH.rglob("*.md"):
        if any(d in f.parts for d in IGNORE_DIRS):
            continue
        if f.name in IGNORE_FILES:
            continue
        files.append(f)
    return files


def rel(path: Path) -> str:
    """Vault ルートからの相対パスを返す。"""
    try:
        return str(path.relative_to(VAULT_PATH))
    except ValueError:
        return str(path)


def build_link_index(files: list[Path]) -> dict[str, str]:
    """
    ステム（拡張子なしファイル名）→ 絶対パス の辞書を作成。
    リンク解決に使う。
    """
    index = {}
    for f in files:
        index[f.stem.lower()] = str(f)
        # フォルダ/ファイル 形式も登録
        index[rel(f).replace("\\", "/").lower().removesuffix(".md")] = str(f)
    return index


# ─── チェック群 ──────────────────────────────────────────────────────────────

def check_frontmatter(files: list[Path]) -> list[Issue]:
    """フロントマターの必須フィールドが揃っているか確認。"""
    issues = []
    for f in files:
        # inbox・テンプレートは除外
        parts = f.parts
        if "inbox" in parts or f.stem.startswith("_"):
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        meta = parse_frontmatter(text)
        meta_keys = set(meta.keys())

        missing = []
        if not (REQUIRED_TITLE & meta_keys):
            missing.append("タイトル")
        if not (REQUIRED_DATE & meta_keys):
            missing.append("作成日")
        if not (REQUIRED_TAGS & meta_keys):
            missing.append("タグ")

        if missing:
            issues.append(Issue(
                Issue.WARN, "frontmatter",
                rel(f),
                f"必須フィールドなし: {', '.join(missing)}"
            ))
    return issues


def check_broken_links(files: list[Path], link_index: dict) -> list[Issue]:
    """壊れた Wikiリンクを検出。"""
    issues = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        links = extract_wikilinks(text)
        for link in links:
            # リンクの正規化
            key = link.lower().strip().removesuffix(".md")
            key_stem = Path(key).name
            if key not in link_index and key_stem not in link_index:
                issues.append(Issue(
                    Issue.FAIL, "broken_link",
                    rel(f),
                    f"リンク先が見つかりません: [[{link}]]"
                ))
    return issues


def check_orphaned_notes(files: list[Path]) -> list[Issue]:
    """どこからもリンクされていない孤立ノートを検出。"""
    # 全テキストを結合してリンクを収集
    all_links: set[str] = set()
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
            for lnk in extract_wikilinks(text):
                all_links.add(lnk.lower().strip())
                all_links.add(Path(lnk).name.lower().strip())
        except Exception:
            continue

    issues = []
    skip_dirs = {"inbox", "MOC"}
    for f in files:
        if any(d in f.parts for d in skip_dirs):
            continue
        if f.stem.startswith("_"):
            continue
        stem = f.stem.lower()
        rel_path = rel(f).replace("\\", "/").lower().removesuffix(".md")
        if stem not in all_links and rel_path not in all_links:
            issues.append(Issue(
                Issue.INFO, "orphaned",
                rel(f),
                "どこからもリンクされていない孤立ノート"
            ))
    return issues


def check_nozomaru_backlinks() -> list[Issue]:
    """
    望丸/世界情勢/ 内の記事にバックリンクが付いているか確認。
    付いていない記事には自動で追記する（auto_fix=True）。
    """
    issues = []
    if not NOZOMARU_DIR.exists():
        return issues

    backlink_snippet = NOZOMARU_BACKLINK
    auto_fixed = 0
    missing = 0

    for f in NOZOMARU_DIR.rglob("*.md"):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        if backlink_snippet not in text:
            # 自動修復: バックリンクフッターを追記
            try:
                with open(f, "a", encoding="utf-8") as fp:
                    fp.write("\n---\n")
                    fp.write(f"*🗺️ [[望丸/蔵丸管理/MOC_世界情勢|世界情勢 MOC]] | [[望丸/望丸_ダッシュボード|望丸ダッシュボード]]*\n")
                auto_fixed += 1
            except Exception as e:
                missing += 1
                issues.append(Issue(
                    Issue.WARN, "nozomaru_backlink",
                    rel(f),
                    f"バックリンクなし（自動修復失敗: {e}）"
                ))

    if auto_fixed > 0:
        issues.append(Issue(
            Issue.INFO, "nozomaru_backlink",
            "望丸/世界情勢/",
            f"バックリンクを自動追加: {auto_fixed}件 ✅"
        ))
    if missing > 0:
        issues.append(Issue(
            Issue.WARN, "nozomaru_backlink",
            "望丸/世界情勢/",
            f"バックリンク追加失敗（手動確認が必要）: {missing}件"
        ))
    return issues


def fetch_bosai_alerts() -> list[Issue]:
    """
    JMA API から最新地震・警報情報を取得し、重要なものをレポートに含める。
    結果を望丸/蔵丸管理/防災アラート.md にも書き込む。
    """
    issues = []
    now = datetime.datetime.now()

    alerts = []

    # ── 地震情報取得 ──────────────────────────────────────────────
    try:
        req = urllib.request.Request(
            JMA_EQ_API,
            headers={"User-Agent": "Mozilla/5.0 (compatible; Kuramaru/1.0)"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read()
            # エンコーディングを自動判定（UTF-8 → UTF-8-sig → latin-1 の順）
            for enc in ("utf-8", "utf-8-sig", "shift_jis", "latin-1"):
                try:
                    eq_list = json.loads(raw.decode(enc))
                    break
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
            else:
                raise ValueError("JSON decode failed")

        # 直近6時間の地震を抽出
        cutoff = now - datetime.timedelta(hours=6)
        recent_eqs = []
        for eq in eq_list[:50]:  # 最新50件をチェック
            try:
                # 時刻フィールドは "at" または "rdt"
                t_str = eq.get("at", eq.get("rdt", ""))
                if not t_str:
                    continue
                t = datetime.datetime.fromisoformat(t_str.replace("Z", "+00:00"))
                t_local = t.replace(tzinfo=None)  # naive に
                mag = float(eq.get("mag", 0) or 0)
                max_int = eq.get("maxi", "")
                area = eq.get("en_anm", eq.get("anm", "不明"))
                if t_local >= cutoff:
                    recent_eqs.append({
                        "time": t_local.strftime("%H:%M"),
                        "mag": mag,
                        "max_int": max_int,
                        "area": area,
                    })
                    if mag >= 5.0 or (max_int and max_int >= "5"):
                        issues.append(Issue(
                            Issue.FAIL, "bosai_地震",
                            "JMA地震情報",
                            f"⚠️ M{mag} 最大震度{max_int} {area} ({t_local.strftime('%H:%M')})"
                        ))
            except Exception:
                continue

        alerts.append(f"## 🌏 地震情報（直近6時間: {len(recent_eqs)}件）\n")
        for eq in recent_eqs[:10]:
            icon = "🔴" if eq["mag"] >= 5.0 else "🟡" if eq["mag"] >= 4.0 else "🔵"
            alerts.append(f"- {icon} {eq['time']} M{eq['mag']} 震度{eq['max_int'] or '?'} {eq['area']}")
        if not recent_eqs:
            alerts.append("- ✅ 有感地震なし")

    except Exception as e:
        alerts.append(f"## 🌏 地震情報\n- ⚠️ 取得失敗: {e}")

    # ── 防災アラートファイルに書き込み ───────────────────────────────
    try:
        ts = now.strftime("%Y-%m-%d %H:%M")
        lines = [
            "---",
            f"更新日時: {ts}",
            "タグ: [蔵丸, 防災, JMA, 自動生成]",
            "---",
            "",
            "# 🚨 防災アラート（蔵丸監視）",
            f"> 更新: {ts} | [[MOC/ニュースMOC|ニュースMOC]] | [[望丸/望丸_ダッシュボード|望丸]]",
            "",
        ] + alerts + [
            "",
            "---",
            f"*蔵丸 自動収集 | JMA API | {ts}*",
        ]
        BOSAI_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        BOSAI_REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    except Exception as e:
        issues.append(Issue(Issue.WARN, "bosai_書込", "防災アラート.md", f"書込失敗: {e}"))

    return issues


def check_inbox_nonempty(files: list[Path]) -> list[Issue]:
    """
    inbox にファイル・フォルダがある時点で警告。
    ルール: 読み込んだら即・適切なフォルダに移動すること。
    inbox は常に空に保つ。.md 以外（PDF・txt等）も検出する。
    """
    issues = []
    now = datetime.datetime.now()
    inbox_path = VAULT_PATH / "inbox"
    if not inbox_path.exists():
        return issues

    # inbox 直下の全アイテム（ファイル＋フォルダ）を検出
    for item in inbox_path.iterdir():
        # 蔵丸レポートは除外
        if item.name == "蔵丸レポート.md":
            continue
        # 隠しファイルは除外
        if item.name.startswith("."):
            continue

        mtime = datetime.datetime.fromtimestamp(item.stat().st_mtime)
        days  = (now - mtime).days
        kind  = "フォルダ" if item.is_dir() else f"ファイル({item.suffix or '不明'})"

        if days >= INBOX_STALE_DAYS:
            issues.append(Issue(
                Issue.FAIL, "inbox_要移動",
                rel(item),
                f"⚠️ {kind} が {days}日間滞留！処理して適切なフォルダへ移動してください。"
            ))
        else:
            age = f"{days}日前" if days > 0 else "本日"
            issues.append(Issue(
                Issue.WARN, "inbox_要移動",
                rel(item),
                f"{kind} | {age}追加 → inbox は常に空に！適切なフォルダへ移動してください。"
            ))
    return issues


def check_moc_missing(files: list[Path]) -> list[Issue]:
    """ドメインフォルダにあるノートで MOC に未登録のものを検出。"""
    issues = []
    for moc_rel, domain_rel in MOC_MAP.items():
        moc_path    = VAULT_PATH / moc_rel
        domain_path = VAULT_PATH / domain_rel
        if not moc_path.exists() or not domain_path.exists():
            continue
        moc_text = moc_path.read_text(encoding="utf-8", errors="replace")

        for f in files:
            if not str(f).startswith(str(domain_path)):
                continue
            if f.stem.startswith("_"):
                continue
            # MOC テキスト内でファイル名が言及されているか
            if f.stem not in moc_text and rel(f) not in moc_text:
                issues.append(Issue(
                    Issue.WARN, "moc_missing",
                    rel(f),
                    f"{moc_rel} に未登録"
                ))
    return issues


# ─── スキャン ────────────────────────────────────────────────────────────────

_last_bosai_check: float = 0  # 最終防災チェック時刻


def run_scan() -> list[Issue]:
    """全チェックを実行して Issue リストを返す。"""
    global _last_bosai_check

    print(f"  [蔵丸] スキャン開始: {VAULT_PATH}", flush=True)
    files      = get_all_md_files()
    link_index = build_link_index(files)

    issues = []
    issues += check_frontmatter(files)
    issues += check_broken_links(files, link_index)
    issues += check_orphaned_notes(files)
    issues += check_inbox_nonempty(files)
    issues += check_moc_missing(files)

    # ── 望丸バックリンク自動修復（失敗してもVault監視は続く） ─────────
    try:
        issues += check_nozomaru_backlinks()
    except Exception as e:
        print(f"  [蔵丸] ⚠️ 望丸バックリンクチェック失敗（Vault監視は継続）: {e}", flush=True)

    # ── 防災情報（10分ごと・失敗してもVault監視は続く） ──────────────
    now_t = time.time()
    if now_t - _last_bosai_check >= BOSAI_CHECK_INTERVAL:
        print("  [蔵丸] 🚨 防災情報チェック中...", flush=True)
        try:
            bosai_issues = fetch_bosai_alerts()
            issues += bosai_issues
            _last_bosai_check = now_t
            if any(i.level == Issue.FAIL for i in bosai_issues):
                print("  [蔵丸] ⚠️ 重要な防災アラートを検出！", flush=True)
        except Exception as e:
            print(f"  [蔵丸] ⚠️ 防災情報取得失敗（Vault監視は継続）: {e}", flush=True)
            _last_bosai_check = now_t  # 失敗してもタイマーリセット（連続失敗防止）

    print(f"  [蔵丸] スキャン完了: {len(files)}ファイル / {len(issues)}件の問題", flush=True)
    return issues


# ─── レポート生成 ────────────────────────────────────────────────────────────

def write_report(issues: list[Issue]):
    """inbox/蔵丸レポート.md に結果を書き込む。"""
    now     = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    fails   = [i for i in issues if i.level == Issue.FAIL]
    warns   = [i for i in issues if i.level == Issue.WARN]
    infos   = [i for i in issues if i.level == Issue.INFO]

    lines = [
        "---",
        f"更新日時: {now}",
        "タグ: [蔵丸, 品質管理, 自動生成]",
        "---",
        "",
        "# 👁️ 蔵丸レポート",
        f"> 禁書庫の巡回報告 ── {now} 更新",
        "",
        f"| 分類 | 件数 |",
        f"|------|------|",
        f"| 🔴 FAIL（要対処） | {len(fails)}件 |",
        f"| 🟡 WARN（推奨対処） | {len(warns)}件 |",
        f"| 🔵 INFO（参考情報） | {len(infos)}件 |",
        f"| **合計** | **{len(issues)}件** |",
        "",
    ]

    for level, group, heading in [
        (Issue.FAIL, fails, "🔴 FAIL ── 要対処"),
        (Issue.WARN, warns, "🟡 WARN ── 推奨対処"),
        (Issue.INFO, infos, "🔵 INFO ── 参考情報"),
    ]:
        lines.append(f"## {heading}")
        if not group:
            lines.append("_問題なし ✅_")
        else:
            # チェック種別ごとにグループ化
            by_check: dict[str, list[Issue]] = {}
            for i in group:
                by_check.setdefault(i.check, []).append(i)
            for check, items in by_check.items():
                lines.append(f"\n### `{check}` （{len(items)}件）")
                for item in items:
                    lines.append(f"- `{item.path}`")
                    lines.append(f"  - {item.detail}")
        lines.append("")

    lines += [
        "---",
        f"*蔵丸 自動生成 | Vault: {VAULT_PATH} | ファイル数: {len(get_all_md_files())}*",
    ]

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"  [蔵丸] レポート更新 → {rel(REPORT_PATH)}", flush=True)


# ─── Claude API 修正提案 ─────────────────────────────────────────────────────

def suggest_fixes_with_claude(issues: list[Issue]):
    """重大な問題を Claude API に送って修正提案をもらう。"""
    try:
        import anthropic
    except ImportError:
        print("  [蔵丸] anthropic ライブラリなし。pip install anthropic で導入可能。")
        return

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("  [蔵丸] ANTHROPIC_API_KEY が未設定。--fix オプションは使えません。")
        return

    critical = [i for i in issues if i.level == Issue.FAIL]
    if not critical:
        print("  [蔵丸] 重大な問題なし。Claude 呼び出しをスキップ。")
        return

    client = anthropic.Anthropic(api_key=api_key)

    # 各問題ごとに修正提案を取得
    suggestions = []
    for issue in critical[:5]:  # 上位5件まで
        try:
            # 問題のあるファイルを読み込む
            target = VAULT_PATH / issue.path
            content = target.read_text(encoding="utf-8", errors="replace") if target.exists() else "（ファイル不明）"

            response = client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=500,
                messages=[{
                    "role": "user",
                    "content": (
                        f"Obsidian ノートの問題を修正してください。\n\n"
                        f"問題種別: {issue.check}\n"
                        f"詳細: {issue.detail}\n"
                        f"ファイル: {issue.path}\n\n"
                        f"ノート内容（先頭500文字）:\n{content[:500]}\n\n"
                        f"修正案を簡潔に（3行以内）教えてください。"
                    )
                }]
            )
            suggestion = response.content[0].text.strip()
            suggestions.append(f"\n### {issue.path}\n{suggestion}")
        except Exception as e:
            suggestions.append(f"\n### {issue.path}\n（提案取得エラー: {e}）")

    if suggestions:
        # レポートに修正提案を追記
        existing = REPORT_PATH.read_text(encoding="utf-8")
        addition = "\n\n## 🤖 Claude 修正提案\n" + "\n".join(suggestions) + "\n"
        REPORT_PATH.write_text(existing + addition, encoding="utf-8")
        print(f"  [蔵丸] Claude 修正提案をレポートに追記しました。")


# ─── 監視モード ──────────────────────────────────────────────────────────────

def _get_inbox_items(inbox_dir: Path) -> list[Path]:
    """inbox 内の処理対象アイテム一覧（レポート・隠しファイルを除く）。"""
    if not inbox_dir.exists():
        return []
    return [p for p in inbox_dir.iterdir()
            if not p.name.startswith(".") and p.name not in IGNORE_FILES]


def _process_inbox_items(items: list[Path], processor: "InboxProcessor"):
    """アイテムリストを処理してレポートに追記。"""
    for item in items:
        if item.exists():
            try:
                processor.process(item)
            except Exception as e:
                print(f"  [蔵丸] ⚠️ 処理エラー ({item.name}): {e}", flush=True)
    if processor.log:
        processor.append_to_report()
        processor.log.clear()


def watch_mode(enable_fix: bool = False, enable_auto: bool = False):
    """ファイル変更を監視しながら定期スキャンを行うデーモンモード。"""
    processor = InboxProcessor() if enable_auto else None
    inbox_dir = VAULT_PATH / "inbox"

    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler

        class VaultHandler(FileSystemEventHandler):
            def __init__(self):
                self.pending = False
                self.new_inbox_items: list = []

            def on_created(self, event):
                p = Path(event.src_path)
                if enable_auto and p.parent == inbox_dir:
                    if not p.name.startswith(".") and p.name not in IGNORE_FILES:
                        self.new_inbox_items.append(p)
                        print(f"  [蔵丸 📥] inbox 新着: {p.name}", flush=True)

            def on_any_event(self, event):
                if event.src_path.endswith(".md"):
                    self.pending = True

        handler  = VaultHandler()
        observer = Observer()
        observer.schedule(handler, str(VAULT_PATH), recursive=True)
        observer.start()
        use_watchdog = True
        print("  [蔵丸] watchdog リアルタイム監視を開始しました。")
    except ImportError:
        use_watchdog = False
        print("  [蔵丸] watchdog 未インストール。ポーリングモードで動作します。")

    # ── ★ 起動時: inbox に既存ファイルがあれば即処理 ─────────────────
    if enable_auto and processor:
        existing = _get_inbox_items(inbox_dir)
        if existing:
            print(f"  [蔵丸] 📦 起動時 inbox 処理: {len(existing)}件", flush=True)
            _process_inbox_items(existing, processor)
        else:
            print("  [蔵丸] 📭 inbox は空です。", flush=True)

    if enable_auto:
        print("  [蔵丸] 🤖 自動処理 ON ── inbox への投入ファイルを自動振り分け")
    print(f"  [蔵丸] 常駐監視モード開始（{SCAN_INTERVAL}秒ごとにスキャン）")
    print("  Ctrl+C で終了")

    last_scan    = 0
    # ポーリング用: 前回チェック時の inbox スナップショット
    seen_inbox: set[str] = {p.name for p in _get_inbox_items(inbox_dir)}

    try:
        while True:
            now = time.time()
            trigger = False

            # ── inbox 新着の自動処理（watchdog あり） ────────────────────
            if use_watchdog and enable_auto and processor and handler.new_inbox_items:
                items = handler.new_inbox_items[:]
                handler.new_inbox_items.clear()
                time.sleep(1.5)  # 書き込み完了を待つ
                _process_inbox_items([i for i in items if i.exists()], processor)
                trigger = True

            # ── inbox ポーリング（watchdog なし時のフォールバック） ───────
            if not use_watchdog and enable_auto and processor:
                current = {p.name: p for p in _get_inbox_items(inbox_dir)}
                new_names = set(current.keys()) - seen_inbox
                if new_names:
                    new_items = [current[n] for n in new_names]
                    print(f"  [蔵丸 📥] inbox 新着（ポーリング検出）: {len(new_items)}件", flush=True)
                    _process_inbox_items(new_items, processor)
                    trigger = True
                seen_inbox = set(current.keys())

            # ── 通常の変更検出（watchdog あり） ──────────────────────────
            if use_watchdog and handler.pending:
                handler.pending = False
                trigger = True
                print("  [蔵丸] ファイル変更を検出 → 即時スキャン", flush=True)

            # ── 定期スキャン ──────────────────────────────────────────────
            if now - last_scan >= SCAN_INTERVAL:
                trigger = True

            if trigger:
                issues = run_scan()
                write_report(issues)
                if enable_fix:
                    suggest_fixes_with_claude(issues)
                last_scan = now

            time.sleep(5)
    except KeyboardInterrupt:
        print("\n  [蔵丸] 監視終了。またね。")
        if use_watchdog:
            observer.stop()
            observer.join()


# ─── メイン ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="蔵丸 - Obsidian Vault 守護エージェント",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""使い方:
  python3 蔵丸.py                        # 一回スキャン＋レポート
  python3 蔵丸.py --auto                 # inbox を即時一括処理 + スキャン
  python3 蔵丸.py --watch               # 常駐監視モード
  python3 蔵丸.py --watch --auto        # 常駐 + inbox 自動振り分け（★推奨）
  python3 蔵丸.py --watch --auto --fix  # 常駐 + 自動振り分け + Claude 修正
  python3 蔵丸.py --scan-only           # スキャンのみ（コンソール出力）
"""
    )
    parser.add_argument("--watch",     action="store_true", help="常駐監視モードで起動")
    parser.add_argument("--fix",       action="store_true", help="Claude API で修正提案（--watch と併用）")
    parser.add_argument("--auto",      action="store_true", help="inbox ファイルを自動振り分け")
    parser.add_argument("--scan-only", action="store_true", help="スキャンのみ、レポートを書かない")
    args = parser.parse_args()

    print()
    print("╔══════════════════════════════════════════════════╗")
    print("║  👁️  蔵丸  ─  禁書庫の守護者                   ║")
    print("╚══════════════════════════════════════════════════╝")
    print(f"  Vault: {VAULT_PATH}")
    print()

    if not VAULT_PATH.exists():
        print(f"  エラー: Vault が見つかりません: {VAULT_PATH}")
        return

    if args.watch:
        watch_mode(enable_fix=args.fix, enable_auto=args.auto)
    else:
        # 一回処理モード: --auto なら inbox を一括処理してからスキャン
        if args.auto:
            print("  [蔵丸] 📦 inbox 一括処理を開始しますわ...")
            processor = InboxProcessor()
            processor.process_all_inbox()
            if processor.log:
                # レポートがまだない場合は仮スキャンで先に生成
                if not REPORT_PATH.exists():
                    issues_pre = run_scan()
                    write_report(issues_pre)
                processor.append_to_report()
            print()

        issues = run_scan()
        if args.scan_only:
            for i in issues:
                print(f"  {i}")
        else:
            write_report(issues)
            if args.fix:
                suggest_fixes_with_claude(issues)
        print()
        # 結果サマリー
        fails = sum(1 for i in issues if i.level == Issue.FAIL)
        warns = sum(1 for i in issues if i.level == Issue.WARN)
        infos = sum(1 for i in issues if i.level == Issue.INFO)
        print(f"  🔴 FAIL: {fails}件  🟡 WARN: {warns}件  🔵 INFO: {infos}件")
        if not args.scan_only:
            print(f"  📋 レポート: {rel(REPORT_PATH)}")
        print()


if __name__ == "__main__":
    main()
