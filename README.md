# ShuttleScope

ShuttleScope は、バドミントンの試合アノテーションと試合分析を一体化した Windows デスクトップアプリです。  
Electron 上の React UI と、ローカル FastAPI バックエンド、SQLite を組み合わせて動作します。

現状は「試合中でも回る注釈入力」と「試合後すぐ使える分析」を主軸にしており、将来的な共有・映像連携・自動追跡まで見据えた構成になっています。

## What It Does

- 試合一覧・選手管理
- クイックスタートからの試合作成
- 試合中アノテーション
- ラリー、ショット、落点、例外終了、見逃しラリー、スコア補正
- マッチデーモードとセット間サマリー
- ダッシュボード分析
- ヒートマップ、ショット遷移、失点前分析、プレッシャー局面分析
- EPV / Markov 系分析
- ダブルス分析
- PDF / JSON レポート出力
- セッション共有、コーチビュー、コメント、ブックマーク
- ネットワーク診断と LAN 共有補助
- TrackNet ベースの自動追跡統合用土台

## Current Product Shape

### Annotator

- 試合中の高速入力を前提にした注釈画面
- 大きい操作ボタンとキーボード入力
- 動画なしでも使えるタイマーモード
- 見逃しラリー、スコア補正、途中終了対応
- クイックスタートから即座に試合開始
- セッション共有コードの発行

### Dashboard

- 試合、セット、相手、ラリー長、ショット種別ごとの集計
- コートヒートマップ
- 先手・返球・失点前傾向の分析
- ダブルス分析
- EPV / Markov、Shot Influence、各種比較表示
- 信頼度表示を前提にした分析 UI

### Sharing / Live Workflow

- 試合ごとの共有セッション作成
- コーチ向けライブビュー
- コメント投稿
- ブックマーク追加
- LAN モード
- 接続診断

## Tech Stack

- Desktop shell: Electron
- Frontend: React 18, TypeScript, Vite
- State / data: Zustand, TanStack Query
- Charts: Recharts, D3
- Backend: FastAPI
- Database: SQLite
- Analysis: NumPy, SciPy, scikit-learn
- Reporting: ReportLab, matplotlib
- Tracking integration: ONNX / TensorFlow / OpenVINO route for TrackNet

## Repository Layout

```text
shuttle-scope/
├─ CLAUDE.md
├─ LICENSE
├─ README.md
├─ private_docs/                  # private, ignored
└─ shuttlescope/
   ├─ electron/                   # Electron main / preload
   ├─ src/
   │  ├─ api/
   │  ├─ components/
   │  ├─ hooks/
   │  ├─ i18n/
   │  ├─ pages/
   │  ├─ store/
   │  ├─ styles/
   │  └─ types/
   ├─ backend/
   │  ├─ analysis/
   │  ├─ db/
   │  ├─ routers/
   │  ├─ tests/
   │  ├─ tracknet/
   │  └─ ws/
   ├─ docs/
   │  └─ validation/              # local validation notes, ignored
   ├─ scripts/
   └─ shuttlescope.db
```

## Roles

POC 段階ではローカルの role 切り替えを前提にしています。

- `analyst`
- `coach`
- `player`

`player` には一部分析をそのまま見せず、`RoleGuard` と confidence 表示を前提にしています。

## Setup

### Requirements

- Node.js 18+
- Python 3.10+
- Windows での利用を主対象
- `ffmpeg` があると動画ダウンロード系の補助が広がる

### Frontend / Electron

```bash
cd shuttlescope
npm install
npm run dev
```

本番ビルド:

```bash
cd shuttlescope
npm run build
```

起動補助スクリプト:

```bash
cd shuttlescope
npm run start
```

または `start.bat` を利用できます。

### Backend

```bash
cd shuttlescope/backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

既定では FastAPI は `http://127.0.0.1:8765` で起動します。

## Tests

Backend:

```bash
cd shuttlescope
.\backend\.venv\Scripts\python -m pytest -v
```

Frontend:

```bash
cd shuttlescope
npx vitest run --config vitest.config.ts
```

Build check:

```bash
cd shuttlescope
npm run build
```

## Data / Database

- 現状のアプリ DB は SQLite です
- 既定の DB ファイルは `shuttlescope/shuttlescope.db`
- 選手、試合、ラリー、ショット、共有セッションなどが保存されます
- 将来的な PostgreSQL 移行を見据えた構成です

## Scripts

`shuttlescope/scripts/` にはローカル検証用の補助スクリプトがあります。

- `generate_test_data.py`
- `generate_doubles_data.py`
- `generate_first_return_data.py`

## TrackNet Integration

TrackNet 連携の土台は入っていますが、重みファイルや生成物は Git には含めていません。

- backend 設定から有効化
- backend 種別は `auto`, `openvino`, `onnx_cpu`, `tensorflow_cpu`
- weights / ONNX はローカル管理

## Notes

- `private_docs/` は Git 管理対象外です
- `shuttlescope/docs/validation/` のメモも Git 管理対象外です
- ローカル DB、動画、weights、生成物は `.gitignore` で除外されています
- 日本語 UI 文言は `shuttlescope/src/i18n/ja.json` を基準にしています

## Status

ShuttleScope は既に注釈入力と分析の主機能を持つデスクトップアプリとして動作します。  
一方で、共有、映像統合、自動追跡、比較可視化、ネットワーク環境耐性は継続強化中です。
