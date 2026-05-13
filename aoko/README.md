# 🔵 青っ子（Aoko）- 青い三連星セキュリティシステム

> 「速さで勝負！3体ローテーションで鉄壁防御」
> たるっ子の軽量セキュリティ特化版

---

## アーキテクチャ

```
脅威イベント発生
      ↓
  conductor.py（指揮官）
  ├─ A号機：ファイル・プロセス監視
  ├─ B号機：ネットワーク・通信監視
  └─ C号機：AI攻撃パターン判定
      ↓
  多数決（2/3以上で脅威認定）
      ↓
  response.py（対応実行）
  ├─ LOW    → 記録のみ
  ├─ MEDIUM → ネット切断
  ├─ HIGH   → Vault隔離 + 通知
  └─ CRITICAL → 人間に判断委ねる
```

## モデル

- **ベース**: Qwen2.5-1.5B-Q4_K_M（約1GB・USB対応サイズ）
- **3号機とも同じモデル・異なるシステムプロンプト**
- llama-server で3ポート起動（11201/11202/11203）

## USBセット内容

```
/USB
├── aoko/
│   ├── model/qwen2.5-1.5b-q4.gguf  ← 約1GB
│   ├── conductor.py
│   ├── aoko_A.py
│   ├── aoko_B.py
│   ├── aoko_C.py
│   ├── response.py
│   └── launch.sh
├── clamav/  ← ウイルスDB
└── install/  ← 鬼丸・望丸インストーラー
```
