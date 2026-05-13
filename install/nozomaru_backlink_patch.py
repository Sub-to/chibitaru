#!/usr/bin/env python3
"""
望丸バックリンクパッチ（ThinkPad適用用）
==========================================
望丸の記事保存処理に、Obsidianバックリンクを自動付与するパッチ。

【適用方法】ThinkPadが復帰したら：
  1. このファイルを ~/nozomaru/ にコピー
  2. 望丸のRSSコレクタ（collector/rss_collector.py 等）で
     save_article() 関数を修正する

【差し替えるフッター部分（元コード例）】
    footer = f"*望丸 自動収集 | {datetime_str}*"

【修正後】
    footer = build_nozomaru_footer(datetime_str)
"""

# ── 挿入する関数 ──────────────────────────────────────────────────────────────

BACKLINK_FOOTER = """
---
*🗺️ [[望丸/蔵丸管理/MOC_世界情勢|世界情勢 MOC]] | [[望丸/望丸_ダッシュボード|望丸ダッシュボード]]*
"""

def build_nozomaru_footer(datetime_str: str, category: str = "") -> str:
    """
    望丸記事のフッターを生成する。
    Obsidianバックリンク付き。

    使い方（望丸のsave_article内で）:
        footer = build_nozomaru_footer(datetime_str, article.get('category',''))
        content += f"\\n---\\n*望丸 自動収集 | {datetime_str}*" + BACKLINK_FOOTER
    """
    return (
        f"\n---\n"
        f"*望丸 自動収集 | {datetime_str}*\n"
        f"\n---\n"
        f"*🗺️ [[望丸/蔵丸管理/MOC_世界情勢|世界情勢 MOC]] | "
        f"[[望丸/望丸_ダッシュボード|望丸ダッシュボード]]*\n"
    )


# ── 既存記事への一括バックリンク追加（移行用） ──────────────────────────────

import os
from pathlib import Path

VAULT_PATH = Path.home() / "Ofsaver1"
NOZOMARU_DIR = VAULT_PATH / "望丸" / "世界情勢"
BACKLINK_SNIPPET = "望丸/蔵丸管理/MOC_世界情勢"


def patch_existing_articles():
    """既存の全望丸記事にバックリンクを追加する（一回だけ実行）。"""
    if not NOZOMARU_DIR.exists():
        print(f"望丸フォルダが見つかりません: {NOZOMARU_DIR}")
        return

    fixed = 0
    skipped = 0
    for f in NOZOMARU_DIR.rglob("*.md"):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
            if BACKLINK_SNIPPET in text:
                skipped += 1
                continue
            with open(f, "a", encoding="utf-8") as fp:
                fp.write("\n---\n")
                fp.write("*🗺️ [[望丸/蔵丸管理/MOC_世界情勢|世界情勢 MOC]] | "
                         "[[望丸/望丸_ダッシュボード|望丸ダッシュボード]]*\n")
            fixed += 1
        except Exception as e:
            print(f"  エラー ({f.name}): {e}")

    print(f"バックリンク追加完了: {fixed}件 / スキップ(既存): {skipped}件")


# ── 望丸 RSS コレクタへの差し込みパッチ ─────────────────────────────────────
#
# collector/rss_collector.py 内の記事保存部分を以下のように修正する:
#
# 【変更前】
#   content = f"""---
#   ...frontmatter...
#   ---
#   # {title}
#   ...本文...
#   ---
#   *望丸 自動収集 | {collected_at}*
#   """
#
# 【変更後】
#   from nozomaru_backlink_patch import build_nozomaru_footer
#   content = f"""---
#   ...frontmatter...
#   ---
#   # {title}
#   ...本文...
#   """ + build_nozomaru_footer(collected_at, category)
#
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("望丸バックリンクパッチ - 既存記事への一括適用")
    print(f"対象フォルダ: {NOZOMARU_DIR}")
    print()
    patch_existing_articles()
