#!/usr/bin/env bash
# 🐣 タルっ子AI ─ Step 2: LoRA ファインチューニング
# base モデルのダウンロードと LoRA 訓練を実行する

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="/opt/homebrew/bin/python3"
BASE_MODEL_ID="mlx-community/Qwen2.5-0.5B-Instruct-8bit"
BASE_MODEL_DIR="$HOME/aiset/tarukko/base"
ADAPTERS_DIR="$SCRIPT_DIR/adapters"
DATA_DIR="$SCRIPT_DIR/data"

echo ""
echo "🐣 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "    タルっ子AI ─ Step 2: LoRA 訓練"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ─── 訓練データ確認 ───────────────────────────────
if [ ! -f "$DATA_DIR/train.jsonl" ]; then
    echo "❌ 訓練データが見つかりません！"
    echo "   先に ① データ生成.py を実行してください。"
    echo "   → python3 tarukko/gen.py"
    exit 1
fi

TRAIN_COUNT=$(wc -l < "$DATA_DIR/train.jsonl")
echo "📊 訓練データ: $TRAIN_COUNT 件"
echo ""

# ─── ベースモデル ダウンロード ────────────────────
if [ ! -f "$BASE_MODEL_DIR/config.json" ]; then
    echo "⬇️  ベースモデルをダウンロード中..."
    echo "    $BASE_MODEL_ID"
    echo "    （約600MB・数分かかります）"
    echo ""
    mkdir -p "$BASE_MODEL_DIR"
    # hf コマンドを優先（huggingface-cli は非推奨）
    if command -v hf &>/dev/null; then
        hf download "$BASE_MODEL_ID" --local-dir "$BASE_MODEL_DIR"
    else
        python3 -c "from huggingface_hub import snapshot_download; snapshot_download('$BASE_MODEL_ID', local_dir='$BASE_MODEL_DIR')"
    fi
    echo "✅ ダウンロード完了！"
else
    echo "✅ ベースモデル: 既にダウンロード済み"
fi
echo ""

# ─── LoRA ファインチューニング ────────────────────
echo "🔥 LoRA ファインチューニング開始！"
echo "   （30分〜2時間かかります。放置でOKです）"
echo ""

mkdir -p "$ADAPTERS_DIR"

"$PYTHON" -m mlx_lm lora \
    --model         "$BASE_MODEL_DIR" \
    --train \
    --data          "$DATA_DIR" \
    --fine-tune-type lora \
    --num-layers    8 \
    --batch-size    2 \
    --iters         200 \
    --learning-rate 1e-4 \
    --steps-per-eval 100 \
    --save-every    50 \
    --adapter-path  "$ADAPTERS_DIR"

echo ""
echo "✅ 訓練完了！アダプター保存先: $ADAPTERS_DIR"
echo ""
echo "🐣 次のステップ: bash tarukko/fuse.sh"
echo ""
