# ShuttleScope Master Gaps P2/P3/P4 Implementation
**Date:** 2026-04-11  
**Based on:** `ShuttleScope_MASTER_REMAINING_GAPS_2026-04-11_v1.md`

---

## Priority 2: Court calibration end-to-end closure

### 変更ファイル
- `src/components/video/CourtGridOverlay.tsx`

### 実装内容

**キャリブレーション取得元バッジ**

`CalibSource = 'backend' | 'local' | 'none'` 状態を追加。

| 取得元 | バッジ | 色 |
|---|---|---|
| バックエンド DB から正常取得 | `✓ backend` | 緑 |
| localStorage フォールバック | `⚠ local only` | 黄（ツールチップ付き） |
| 未設定 / キャリブレーション中 | 表示なし | — |

取得元の変化タイミング:
- マウント時: `fetch GET` 成功 → `'backend'`, 失敗+localStorage復元 → `'local'`
- POST 成功時: `'backend'` に更新
- 再キャリブレーション開始時: `'none'` にリセット

**優先度ルール（ドキュメント化）**

1. バックエンド DB（GET 200）
2. localStorage キャッシュ（GET 4xx/5xx のフォールバック）
3. 未設定（どちらもなければキャリブレーション案内を表示）

---

## Priority 3: CV assist quality tuning — threshold 環境変数化

### 変更ファイル
- `backend/cv/candidate_builder.py`

### 実装内容

全しきい値を `os.environ.get` で上書き可能にした。デフォルト値は変わらない。

| 環境変数 | デフォルト | 意味 |
|---|---|---|
| `CV_CONF_HIGH` | 0.72 | auto_filled 境界 |
| `CV_CONF_MEDIUM` | 0.48 | suggested 境界 |
| `CV_TRACKNET_MIN_CONF` | 0.38 | TrackNet 有効最低信頼度 |
| `CV_HITTER_WINDOW_SEC` | 0.6 | ヒッター時刻マッチ許容幅（秒） |
| `CV_LAND_SEARCH_SEC` | 3.0 | 着地ゾーン探索幅（秒） |
| `CV_FRONT_Y` | 0.42 | front/mid 境界 Y（正規化） |
| `CV_BACK_Y` | 0.60 | mid/back 境界 Y（正規化） |
| `CV_ROLE_STABILITY` | 0.65 | ロール安定判定最低割合 |

**使い方（実映像チューニング）:**
```bash
CV_CONF_HIGH=0.65 CV_CONF_MEDIUM=0.40 python -m backend.main
```

起動時に現在値を DEBUG ログに出力するため、設定の確認が容易。

---

## Priority 4: Device bootstrap — setup_doctor 診断精度向上

### 変更ファイル
- `backend/tools/setup_doctor.py`

### 実装内容

TrackNet・YOLO の各診断に `failure_class` フィールドを追加:

| failure_class | 意味 | 推奨アクション |
|---|---|---|
| `package_missing` | パッケージが importできない | `bootstrap_windows.ps1` でインストール |
| `weight_missing` | パッケージはあるが重みファイルが存在しない | bootstrap または手動配置 |
| `backend_load_failed` | ファイルはあるがロード失敗（互換性・メモリ等） | エラー内容を確認 |
| `None` | 正常 | — |

**表示改善:**
- `summarize_report` の READY 行に `(backend名)` を追加: `TrackNet: READY (openvino)`
- NOT READY 時に failure_class と詳細を 1行で表示: `TrackNet issue: [weight_missing] ...`
- `_model_status_label()` ヘルパーで統一ラベル生成

**推奨メッセージも failure_class ごとに分岐:**
- `package_missing`: bootstrap スクリプト実行を案内
- `weight_missing`: weights_dir パスを明示して重みダウンロードを案内
- `backend_load_failed`: エラー文字列を直接表示

---

## 残り（P2/P3/P4 内で人間検証が必要なもの）

- 実映像で TrackNet homography ゾーン精緻化の品質を確認（P2）
- 実映像で YOLO ROI フィルタが有効プレイヤーを除外しないことを確認（P2）
- 実映像でしきい値を調整した候補品質を確認（P3）
- 実際の新規デバイスで bootstrap → setup_doctor → 起動フローを確認（P4）
