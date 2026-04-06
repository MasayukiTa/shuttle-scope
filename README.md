# ShuttleScope

ShuttleScope は、バドミントンの試合動画を対象にしたデスクトップ型のアノテーション / 分析アプリです。  
Electron 上で React の UI を動かし、ローカルの FastAPI バックエンドと SQLite を使って、動画・ラリー・ストローク・分析結果を一体で扱います。

## 現在の実装範囲

- 動画アノテーション
- ラリー / ストローク入力
- キーボード中心の入力フロー
- 解析ダッシュボード
- コートヒートマップ
- ショット遷移マトリクス
- ラリー長 / セット / 時間帯分析
- EPV / Markov 系の詳細分析
- 対戦相手分析
- ダブルス分析
- コーチ / アナリスト / 選手のロール切り替え
- PDF / JSON ベースのレポート出力
- ストリーミング動画ダウンロード補助

## アーキテクチャ

- デスクトップシェル: Electron
- レンダラー: React 18 + TypeScript + Vite
- 状態管理 / データ取得: Zustand, TanStack Query
- グラフ: Recharts, D3.js
- バックエンド: FastAPI
- DB: SQLite
- 解析: NumPy, SciPy, scikit-learn
- レポート: ReportLab, matplotlib

フロントエンドは Electron IPC ではなく、`localhost` 上の FastAPI に HTTP で接続します。  
この構成は、将来的なサーバー移行を見据えたものです。

## リポジトリ構成

```text
shuttle-scope/
├─ CLAUDE.md
├─ README.md
├─ private_docs/                 # ローカル専用の機密資料（Git管理外）
└─ shuttlescope/
   ├─ electron/                  # Electron main / preload
   ├─ src/
   │  ├─ api/
   │  ├─ components/
   │  │  ├─ analysis/
   │  │  ├─ annotation/
   │  │  ├─ common/
   │  │  ├─ court/
   │  │  └─ video/
   │  ├─ hooks/
   │  ├─ i18n/
   │  ├─ pages/
   │  └─ styles/
   ├─ backend/
   │  ├─ analysis/
   │  ├─ db/
   │  ├─ routers/
   │  ├─ tests/
   │  └─ utils/
   ├─ scripts/
   └─ docs/
      └─ validation/             # ローカル検証メモ（Git管理外）
```

## 主な画面

### Annotator

- 動画を見ながらラリー単位で入力
- ストローク番号や直前ショットに応じて候補を絞るアダプティブ入力
- キーボードショートカット中心の入力
- サーブ / レシーブ / 終了種別 / 着地点などを記録

### Dashboard

- 概要 KPI
- ラリー終了タイプ
- ショットタイプ分布
- ラリー長分布
- コートヒートマップ
- スコア推移
- ショット別得点 / 失点
- セット比較
- ラリー長別勝率
- プレッシャー下の傾向
- ショット遷移マトリクス
- 時間帯別パフォーマンス
- ロングラリー後の傾向
- 対戦相手分析
- ダブルス分析
- EPV / Markov 分析

## ロール

POC 段階では `localStorage` を使った簡易ロール切り替えです。

- `analyst`
- `coach`
- `player`

`player` には一部の分析を見せず、`RoleGuard` と `ConfidenceBadge` を使って表示制御と不確実性表示を行っています。

## セットアップ

### 前提

- Node.js 18 以上
- Python 3.10 以上
- Windows 環境を前提に調整済み
- 動画ダウンロード補助を使う場合は `ffmpeg` があると便利

### フロントエンド / Electron

```bash
cd shuttlescope
npm install
npm run dev
```

本番ビルド確認:

```bash
cd shuttlescope
npm run build
```

### バックエンド

```bash
cd shuttlescope/backend
python -m venv .venv
.venv/Scripts/activate
pip install -r requirements.txt
python main.py
```

FastAPI は通常 `http://127.0.0.1:8765` で起動します。  
ヘルスチェック:

```text
GET /api/health
```

## テスト

バックエンド:

```bash
cd shuttlescope
.\backend\.venv\Scripts\python -m pytest -v
```

フロントエンド:

```bash
cd shuttlescope
npx vitest run --config vitest.config.ts
```

## テストデータ生成スクリプト

`shuttlescope/scripts/` にはローカル検証用の補助スクリプトがあります。

- `generate_test_data.py`
- `generate_doubles_data.py`
- `generate_first_return_data.py`

これらはローカル DB に検証データを追加する用途です。

## 重要な運用ルール

- 機密資料は `private_docs/` に置き、Git に含めない
- 検証メモは `shuttlescope/docs/validation/` に置き、Git に含めない
- ローカル DB、動画、生成物、キャッシュはコミットしない
- 日本語 UI 文言は `shuttlescope/src/i18n/ja.json` を優先する

## 補足

現時点では README は実装済み機能の概要とローカル開発手順に絞っています。  
ライセンスやデータ利用条件は、別途確定後に専用ドキュメントとして追加する前提です。
