#!/usr/bin/env python3
"""
🐣 tarukkoAI ─ Step 1: 訓練データ生成
Vault の全ノートから LJP を使って Q&A ペアを自動生成する。
生成されたデータは data/train.jsonl に保存される。

使い方:
  python3 tarukko/①データ生成.py
"""

import os, re, json, glob, datetime
from pathlib import Path

# ─── 設定 ────────────────────────────────────────
VAULT_PATH  = "/Users/masudatakaaki/Ofsaver1"
MODEL_PATH  = "/Users/masudatakaaki/aiset/llm-jp/LLM-jp-4-8b-instruct-MLX-8bit"
OUT_DIR     = Path(__file__).parent / "data"
TRAIN_FILE  = OUT_DIR / "train.jsonl"
VALID_FILE  = OUT_DIR / "valid.jsonl"
QA_PER_NOTE = 5      # ノート1件あたりの Q&A ペア数
MIN_CHARS   = 100    # この文字数未満のノートはスキップ
MAX_CHARS   = 3000   # LJP に渡す最大文字数

# tarukkoのキャラクター設定（system prompt に焼き込む）
TARUKKO_PERSONA = (
    "あなたはtarukkoという小さくてかわいいAIアシスタントです。"
    "ユーザーの知識ベース（Obsidian Vault）に詳しく、"
    "短くわかりやすく、親しみやすい言葉で答えます。"
    "敬語は使いますが堅すぎず、自然な話し言葉で応答します。"
)

# スキップするパス
SKIP_DIRS = [".obsidian", ".claude", ".claudian", "inbox", "memory"]


# ─── ノート読み込み ───────────────────────────────
def load_notes() -> list[dict]:
    notes = []
    for fp in glob.glob(f"{VAULT_PATH}/**/*.md", recursive=True):
        if any(s in fp for s in SKIP_DIRS):
            continue
        try:
            text = Path(fp).read_text(encoding="utf-8")
            # frontmatter 除去
            clean = re.sub(r'^---.*?---\s*', '', text, flags=re.DOTALL).strip()
            if len(clean) < MIN_CHARS:
                continue
            notes.append({
                "path":    os.path.relpath(fp, VAULT_PATH),
                "title":   Path(fp).stem,
                "content": clean[:MAX_CHARS],
            })
        except Exception:
            continue
    return notes


# ─── LJP で Q&A 生成 ──────────────────────────────
def load_ljp():
    from mlx_lm import load
    model, tok = load(MODEL_PATH)
    if not getattr(tok, "chat_template", None):
        j = Path(MODEL_PATH) / "chat_template.jinja"
        if j.exists():
            tok.chat_template = j.read_text(encoding="utf-8")
    return model, tok


def clean_ljp(text: str) -> str:
    text = re.sub(r'<\|channel\|>\s*\S+\s*<\|message\|>\s*', '', text)
    for tag in ["end", "return", "start"]:
        text = re.sub(rf'<\|{tag}\|>.*', '', text, flags=re.DOTALL)
    return text.strip()


def generate_qa(model, tok, note: dict) -> list[dict]:
    """ノート1件から Q&A ペアを生成する"""
    from mlx_lm import generate

    prompt_text = (
        f"以下のノートを読んで、このノートに関する自然な日本語の質問と回答を"
        f"{QA_PER_NOTE}セット作ってください。\n"
        "出力形式（JSON配列）:\n"
        '[{"q": "質問文", "a": "回答文"}, ...]\n\n'
        f"ノートタイトル: {note['title']}\n\n"
        f"ノート内容:\n{note['content']}"
    )

    messages = [
        {"role": "system", "content": "あなたは日本語の質問応答データを作成するAIです。"},
        {"role": "user",   "content": prompt_text},
    ]

    try:
        prompt = tok.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
    except Exception:
        prompt = (
            f"<|start|>system<|message|>あなたは日本語の質問応答データを作成するAIです。<|end|>"
            f"<|start|>user<|message|>{prompt_text}<|end|>"
            f"<|start|>assistant"
        )

    raw = generate(model, tok, prompt=prompt, max_tokens=1024, verbose=False)
    raw = clean_ljp(raw)

    # JSON 配列を抽出
    try:
        m = re.search(r'\[.*?\]', raw, flags=re.DOTALL)
        if not m:
            return []
        pairs = json.loads(m.group())
        result = []
        for p in pairs:
            q = str(p.get("q", "")).strip()
            a = str(p.get("a", "")).strip()
            if q and a and len(q) > 5 and len(a) > 5:
                result.append({"q": q, "a": a})
        return result
    except Exception:
        return []


# ─── JSONL 形式に変換 ─────────────────────────────
def to_jsonl_entry(q: str, a: str) -> dict:
    """mlx-lm LoRA 用の chat 形式"""
    return {
        "messages": [
            {"role": "system",    "content": TARUKKO_PERSONA},
            {"role": "user",      "content": q},
            {"role": "assistant", "content": a},
        ]
    }


# ─── メイン ───────────────────────────────────────
def main():
    print()
    print("🐣 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("    tarukkoAI ─ Step 1: 訓練データ生成")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print()

    OUT_DIR.mkdir(exist_ok=True)

    # ノート読み込み
    notes = load_notes()
    print(f"📚 対象ノート: {len(notes)} 件")
    print(f"📝 1件あたり: {QA_PER_NOTE} Q&Aペア")
    print(f"📊 予想生成数: ~{len(notes) * QA_PER_NOTE} ペア")
    print()

    # LJP 読み込み
    print("⏳ LJP（先生AI）を読み込み中... 数分かかります")
    model, tok = load_ljp()
    print("✅ LJP 準備完了！")
    print()

    # 生成ループ
    all_pairs = []
    for i, note in enumerate(notes, 1):
        print(f"  [{i:2d}/{len(notes)}] {note['title'][:40]}", end="", flush=True)
        pairs = generate_qa(model, tok, note)
        all_pairs.extend(pairs)
        print(f" → {len(pairs)}件")

    print()
    print(f"✅ 合計 {len(all_pairs)} ペア生成完了！")
    print()

    # 訓練/検証に分割（9:1）
    split = max(1, len(all_pairs) * 9 // 10)
    train_pairs = all_pairs[:split]
    valid_pairs = all_pairs[split:]

    # JSONL 書き出し
    with open(TRAIN_FILE, "w", encoding="utf-8") as f:
        for p in train_pairs:
            f.write(json.dumps(to_jsonl_entry(p["q"], p["a"]),
                               ensure_ascii=False) + "\n")

    with open(VALID_FILE, "w", encoding="utf-8") as f:
        for p in valid_pairs:
            f.write(json.dumps(to_jsonl_entry(p["q"], p["a"]),
                               ensure_ascii=False) + "\n")

    print(f"💾 保存完了:")
    print(f"   訓練: {TRAIN_FILE} ({len(train_pairs)}件)")
    print(f"   検証: {VALID_FILE} ({len(valid_pairs)}件)")
    print()
    print("🐣 次のステップ: bash tarukko/②訓練.sh")
    print()


if __name__ == "__main__":
    main()
