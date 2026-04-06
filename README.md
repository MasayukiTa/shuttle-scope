# ShuttleScope

バドミントン動画アノテーション・解析デスクトップアプリ

## 概要

ShuttleScope は、バドミントンの試合映像をアノテーションし、ショット・ラリー・得失点パターンを統計解析するデスクトップアプリケーションです。  
アナリスト・コーチ・選手の3ロールに対応し、ロール別に表示内容を制御します。

## 主な機能

### アノテーション
- 試合動画の再生・フレーム単位シーク
- キーボードショートカットによるショット種別入力（18種類）
- コート9ゾーン/12ゾーン着地点入力
- ラリー確定・スコア連動

### 解析ダッシュボード
- 概要: ラリー終了タイプ分布、ショット種別分布、ラリー長分布
- ショット分析: 勝率・得失点ショット比較、ラリー長×勝率、時間帯別パフォーマンス
- 詳細解析: ショット遷移マトリクス（D3.js ヒートマップ）、EPV（Expected Pattern Value）、スコア推移
- 大会比較: 大会レベル別勝率・平均ラリー長
- セット別: セット進行に伴う勝率変化
- ダブルス: コートカバレッジ、パートナー比較、サーブ/レシーブ分析、打球分担
- 相手分析、ファーストリターン分析、インターバルレポート

### レポート
- PDF形式のコーチ向けレポート生成（ReportLab）
- コートヒートマップ画像（matplotlib）

## アーキテクチャ

```
shuttle-scope/
└── shuttlescope/
    ├── electron/          # Electron メイン/プリロード
    ├── src/               # React + TypeScript レンダラー
    │   ├── pages/         # 画面コンポーネント
    │   ├── components/    # 共通・解析・コート・動画コンポーネント
    │   ├── styles/        # カラーシステム（colors.ts）
    │   └── i18n/          # 日本語翻訳
    ├── backend/           # FastAPI バックエンド
    │   ├── routers/       # エンドポイント（players, matches, rallies, strokes, sets, analysis, reports）
    │   ├── analysis/      # 解析ロジック（Markov, EPV, Bayesian, ショット影響度）
    │   ├── db/            # SQLAlchemy モデル・DB接続
    │   └── utils/         # 動画ダウンロード、バリデーション
    └── scripts/           # テストデータ生成スクリプト
```

**通信:** Electron Renderer ↔ FastAPI (`localhost:8765`) over HTTP  
**DB:** SQLite（POC）→ PostgreSQL（将来移行予定）

## セットアップ

### 前提条件
- Node.js 18+
- Python 3.11+
- ffmpeg（高画質ダウンロード用、任意）

### フロントエンド

```bash
cd shuttlescope
npm install
npm run dev       # 開発モード
npm run build     # ビルド確認
```

### バックエンド

```bash
cd shuttlescope/backend
python -m venv .venv
.venv/Scripts/activate   # Windows
pip install -r requirements.txt
python ../backend/main.py
```

### テスト

```bash
cd shuttlescope
# バックエンド
.\backend\.venv\Scripts\python -m pytest

# フロントエンドビルド確認
npm run build
```

## 技術スタック

| レイヤー | 技術 |
|---|---|
| デスクトップシェル | Electron 33 |
| レンダラー | React 18 + TypeScript + Vite |
| UIコンポーネント | Radix UI + Tailwind CSS |
| チャート | Recharts + D3.js |
| 状態管理 | TanStack Query + Zustand |
| バックエンド | FastAPI + Uvicorn |
| ORM | SQLAlchemy 2.0 |
| 解析 | NumPy / SciPy / scikit-learn / pandas |
| レポート生成 | ReportLab + matplotlib |
| 動画取得 | yt-dlp |
| テスト | pytest + Vitest |

## カラーシステム

全チャートは `src/styles/colors.ts` で定義した coolwarm パレット（matplotlib 準拠）に統一:

- 連続値ヒートマップ: 深青 `#3b4cc0` → 白 `#dddddd` → 深赤 `#b40426`
- 勝ち: `WIN = #3b4cc0`、負け: `LOSS = #b40426`
- 単系列棒グラフ: `BAR = #8db0fe`、複合折れ線: `LINE = #f38a64`

## ロールモデル

| ロール | 表示内容 |
|---|---|
| analyst | 全データ・生データ・操作UI |
| coach | 解析・レポート・戦術分析 |
| player | 成長指向のフィードバックのみ（弱点直接表示なし） |

> POC段階のロール切り替えは localStorage ベース（本番認証ではありません）

## ライセンス

Private — 社内研究プロジェクト
