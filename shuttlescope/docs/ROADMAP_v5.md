# ShuttleScope ROADMAP v5

作成日: 2026-04-06  
前バージョン実装済み: V4（QuickStart、例外処理、11点インターバル、Numpad落点入力）

---

## 優先度マトリクス

| Phase | 内容 | 依存 | 難易度 | 優先 |
|-------|------|------|--------|------|
| P1 | 見逃しラリー・スコア補正入力 | なし | ★☆☆ | 最高 |
| P2 | 映像ソースモード分岐 + 手動タイマー | なし | ★★☆ | 高 |
| P3 | TrackNet + OpenVINO（バッチ補助） | P2 | ★★★ | 中 |
| P4 | デュアルモニター | P2 | ★★☆ | 中 |
| P5 | TrackNet リアルタイム補助 | P3, P4 | ★★★ | 低 |

---

## 共通ガードレール

- 新規 UI / 解析は既存の `RoleGuard` とプレイヤー向け制限を壊さない
- 解析系 UI / API は既存の confidence / sample size 表示を維持する
- `is_skipped=true` を導入する場合、保存だけでなく分析・レポート・スコア推移まで一貫して整合を取る
- TrackNet 系は「実装できたか」ではなく「現場で耐えるか」を採用基準にする
- 各 Phase の完了条件には `build` / `pytest` だけでなく validation メモ更新を含める

---

## Phase 1: 見逃しラリー・スコア補正入力

### 背景

試合中にアナリストが一瞬見逃すケースは頻繁に発生する:
- サーブが速すぎて追えなかった
- メモを取っていて気づいたら点が入っていた
- セット全体を見逃した（途中参加）

現状は全ストロークを入力しないとスコアが進まないため、これらのケースで入力が止まる。

### T1-1: 見逃しラリー入力（SkipRally）

**概要**: ストロークなしで「得点者だけ記録」するラリーを登録できるようにする

**DB変更**:
```
rallies テーブル:
  is_skipped BOOLEAN DEFAULT FALSE  追加
```
- `is_skipped=true` のラリーは rally_length=0、strokes なし
- 解析では shot 系分析から除外、スコア推移には含める
- 集計系では「総ラリー数」には含めるが、「stroke 数」「zone 系母数」には含めない
- confidence の分母が rally ベースか stroke ベースかをエンドポイントごとに再確認する

**バックエンド変更**:
- `backend/routers/strokes.py` の `/strokes/batch` : strokes 空配列を許容
- `backend/db/database.py` の `add_columns_if_missing` に追加
- `backend/db/models.py` の Rally に `is_skipped` 追加
- `backend/routers/analysis.py` :
  - shot / heatmap / transition など stroke 前提の分析から除外
  - `score_progression` ではスコア更新対象として維持
  - `set_summary` ではラリー数に含めつつ、ショット分析からは除外
- `backend/routers/reports.py` : skipped rally を含む/除外する指標の境界を明示

**フロントエンド変更**:
- `src/store/annotationStore.ts` : `skipRally(winner: 'player_a' | 'player_b')` アクション追加
- `src/hooks/useKeyboard.ts` : ショートカット（未確定、例: `Shift+Enter`）
- `src/pages/AnnotatorPage.tsx` :
  - ラリー未開始（idle）時に「見逃しラリー」ボタンを表示
  - 得点者選択ダイアログ（シンプルな2択）

**UI イメージ**:
```
[▶ ラリー開始]  [? 見逃しラリー]

↓ 見逃しクリック

[A 得点]  [B 得点]   ← タップして即確定
```

---

### T1-2: スコア手動補正（ScoreCorrection）

**概要**: 複数ラリー見逃した場合や入力ミスで実スコアとズレた場合に現在スコアを手動で合わせる

**仕様**:
- 現在スコアと実スコアの差分ラリー数を `is_skipped=true` のダミーラリーとして自動生成
- 例: 内部スコア 5-3、実際 8-4 → player_a 3点 + player_b 1点のスキップラリーを補完

**UI**:
```
スコア補正ボタン → ダイアログ
  現在: A 5 - B 3
  修正後: A [8▲▼] - B [4▲▼]
  [補正実行]
```

**フロントエンド変更**:
- `src/pages/AnnotatorPage.tsx` : スコア補正ダイアログ（`showScoreCorrection` state）
- `src/store/annotationStore.ts` : `applyScoreCorrection(targetA, targetB)` アクション
- `src/components/analysis/ScoreProgression.tsx` : 補正後も表示破綻しないことを確認
- `src/components/analysis/SetIntervalSummary.tsx` : skipped rally を含むセット要約の表現を確認

---

### T1-3: セット強制終了（QuickSetEnd）

**概要**: セット途中から見ていて「このセット 21-15 で終わった」と分かっている場合、残りラリーを補完せずにセット終了できる

**UI**:
```
セット管理 > [セット強制終了]
→ ダイアログ: 最終スコア A [21] - B [15]
→ [終了] → 差分をスキップラリーとして自動登録 → 次セットへ
```

**フロントエンド変更**:
- `src/pages/AnnotatorPage.tsx` : `handleForceEndSet(finalA, finalB)` 実装

---

### T1-4: i18n・型定義

**変更ファイル**:
- `src/types/index.ts` : Rally に `is_skipped?: boolean` 追加
- `src/i18n/ja.json` :
  ```json
  "skip_rally": {
    "button": "見逃しラリー",
    "title": "得点者を選択",
    "hint": "ストロークなしで得点を記録します",
    "score_correction": "スコア補正",
    "force_set_end": "セット強制終了",
    "target_score": "実際のスコア"
  }
  ```

---

## Phase 2: 映像ソースモード分岐 + 手動タイマー

### 背景

アノテーションの状況は複数あり、映像の有無・種別によって UI と timestamp 取得方法が変わる:

| モード | 映像 | timestamp取得 | TrackNet |
|--------|------|--------------|----------|
| `local` | ローカルファイル | video.currentTime | ○ |
| `webview` | 組み込みブラウザ（中継） | 手動タイマー | △（低fps） |
| `none` | なし（現地観戦） | 手動タイマー | ✕ |

### T2-1: VideoSourceMode 型定義と状態管理

**変更ファイル**:
- `src/types/index.ts` :
  ```typescript
  export type VideoSourceMode = 'local' | 'webview' | 'none'
  ```
- `src/pages/AnnotatorPage.tsx` :
  - `videoSourceMode` state 追加（初期値は video_url/video_local_path 有無で自動判定）
  - モード切替 UI（3択セレクター）

---

### T2-2: 手動タイマー（MatchTimer）

**概要**: `none` / `webview` モード時に試合開始からの経過時間を計測し、timestamp_sec として使用

**UI**:
```
[▶ 試合開始] → [● 00:14:32.5] [⏸ 一時停止] [⏹ リセット]
```

**実装**:
- `src/hooks/useMatchTimer.ts` : 新規フック
  ```typescript
  interface MatchTimer {
    elapsedSec: number
    isRunning: boolean
    start(): void
    pause(): void
    reset(): void
  }
  ```
- タイマーは `none`/`webview` モードのみ有効
- `local` モードは `videoRef.current.currentTime` を使用（変更なし）
- `src/pages/AnnotatorPage.tsx` : `getTimestamp()` 関数でモードによる分岐を吸収

---

### T2-3: none モード UI

**概要**: 動画パネルを完全に非表示にし、アノテーションパネルをフルスクリーンで使用

**変更**:
- `src/pages/AnnotatorPage.tsx` :
  - `videoSourceMode === 'none'` 時: 動画エリア非表示、アノテーションパネルを `flex-1`
  - ショートカットガイドの Space（再生/一時停止）を非表示
  - タイマーをスコア表示エリアの隣に配置

---

### T2-4: webview モード改善

**概要**: 既存の WebViewPlayer を webview モードとして正式に統合

**変更**:
- `src/pages/AnnotatorPage.tsx` :
  - webview モード時: タイマーを有効化
  - YouTube Live 等のライブ URL を検出した場合は自動で webview モードを推奨
  - `video.currentTime` を使わないよう分岐

---

### T2-5: 最低限の設定永続化

**概要**: 映像ソースモードとタイマー関連の運用設定は P2 の時点で再起動後も保持する

**変更**:
- `src/hooks/useSettings.ts` : `videoSourceMode` / timer 関連の読み書き対応
- `src/pages/AnnotatorPage.tsx` : 前回使用モードの復元
- 将来の `backend/routers/settings.py` 導入を見据え、フロント側の設定キーを整理

**備考**:
- P2 時点では localStorage ベースで良い
- P3 着手前に TrackNet 設定も同じ経路へ寄せる

---

## Phase 3: TrackNet + OpenVINO 統合

### 背景・方針

- ターゲット: **i5-1235U**（Intel Iris Xe 内蔵 GPU）
- ランタイム: **OpenVINO** (Intel製、Iris Xe 最適化) + フォールバック ONNX CPU
- 処理モード: **バッチ優先**（試合後一括解析）、補助モード（ストローク確定時）
- on/off: 設定ページから切替・永続化

### P3 採用条件

- 基準機でバッチ解析が「手動入力の後処理」として許容できる速度で完了すること
- OpenVINO 非対応環境では CPU-only フォールバックで最低限クラッシュせず動くこと
- モデル未導入時に UI / 起動が壊れず、無効状態で通常運用できること
- 推論結果が低信頼な場合は提案しない、または明確に弱い提案として表示すること

### P3 非目標

- すべての Windows マシンで同一性能を保証すること
- WebView / 配信映像でリアルタイム補助を安定提供すること
- AI 推定のみで確定入力を完結させること

### T3-1: モデル準備

**概要**: TrackNet v2 ウェイトを ONNX 変換 → OpenVINO IR 形式に変換

**追加ファイル**:
- `backend/tracknet/` ディレクトリ
  - `model.py` : TrackNet v2 定義（PyTorch）
  - `convert.py` : ONNX → OpenVINO IR 変換スクリプト
  - `weights/` : ウェイトファイル置き場（.gitignore 対象）
  - `inference.py` : 推論クラス（OpenVINO / ONNX 切替）

**依存追加** (`backend/requirements.txt`):
```
openvino>=2024.0
onnxruntime-directml  # OpenVINO 非対応環境フォールバック
```

**初回セットアップフロー**:
```
アプリ初回起動 → TrackNet有効設定 → ウェイト自動ダウンロード or 手動配置案内
```

**追加方針**:
- 参照環境を「基準機」として明記し、他環境はベストエフォートとする
- モデル未配置時はエラー終了ではなく「未導入」状態を返す

---

### T3-2: 推論バックエンド

**変更ファイル**:
- `backend/tracknet/inference.py` :
  ```python
  class TrackNetInference:
      def load(self, backend: str = 'openvino')  # 'openvino' | 'onnx_cpu'
      def predict_frames(self, frames: list[np.ndarray]) -> list[TrackNetResult]
      # TrackNetResult: { x, y, visibility, frame_idx }
  ```
- `backend/routers/tracknet.py` : 新規ルーター
  ```
  POST /api/tracknet/batch/{match_id}
    → 動画全体を解析、rallies の hit_zone / land_zone を自動補完
    → 非同期（BackgroundTasks）、進捗は job_id で取得
  
  GET  /api/tracknet/status/{job_id}
    → { status, progress, completed_rallies, total_rallies }
  
  POST /api/tracknet/stroke_hint
    body: { video_path, timestamp_sec, window_sec: 0.5 }
    → 周辺フレームからゾーン推定を返す（補助モード用）
  ```
- `backend/main.py` : tracknet ルーター登録

---

### T3-3: フレームサンプリング・最適化

**軽量化設計**:
```
全解像度 1920×1080 → ROI クロップ（コート領域 約50%） → 640×360 リサイズ
30fps 動画 → 3フレームに1回サンプリング（10fps相当）
推論: OpenVINO + Iris Xe で推定 15〜25fps 処理能力
→ リアルタイムの 1.5〜2.5倍速でバッチ処理可能
```

**負荷制御**:
- バッチ処理は `threading.Thread` で別スレッド（FastAPI スレッドをブロックしない）
- CPU 使用率上限設定（設定ページ: `max_cpu_pct: 50` など）
- バッチ中は UI に「解析中」バッジを表示、キャンセル可能

**性能検証項目**:
- 基準機で 1 試合あたりの概算処理時間を記録
- CPU-only 時の劣化を記録
- 解析中に annotator / dashboard の操作性が著しく落ちないか確認

---

### T3-4: 設定ページ UI

**変更ファイル**:
- `src/pages/SettingsPage.tsx` (または新規):
  ```
  [TrackNet 解析]
    有効 ○ 無効 ●
    
    処理モード:
      ○ バッチ（試合後に一括解析）← デフォルト
      ○ ストローク補助（確定時に周辺フレームを推論）
    
    推論バックエンド:
      ○ OpenVINO（推奨・Iris Xe 対応）
      ○ ONNX CPU（フォールバック）
    
    CPU使用上限: [50]%
    
    [モデルステータス: インストール済み v2.1]
    [モデルをダウンロード / 更新]
  ```
- `src/hooks/useSettings.ts` : 設定の読み書き（localStorage / config API）

**追加要件**:
- OpenVINO / CPU 切替時に未対応バックエンドを自動で無効化する
- モデル未導入時は設定を保持しつつ、実行時に案内を出す

---

### T3-5: アノテーション画面への統合

**変更ファイル**:
- `src/pages/AnnotatorPage.tsx` :
  - バッチ解析ボタン（動画がある場合のみ表示）:
    ```
    [🔍 TrackNet で自動解析]  → バッチ開始 → 進捗表示
    ```
  - 補助モード時: hit_zone / land_zone に AI 推定値が薄くプリセット表示
    - アナリストが上書き or そのまま確定
    - 確定率が低い場合（visibility < 0.5）は提案しない
  - AI 提案がある場合も、最終決定権は必ずアナリスト側に残す

---

## Phase 4: デュアルモニター

### T4-1: Electron ディスプレイ検出

**変更ファイル**:
- `electron/main.ts` :
  ```typescript
  // IPC: ディスプレイ一覧を返す
  ipcMain.handle('get-displays', () => {
    return screen.getAllDisplays().map(d => ({
      id: d.id,
      label: `${d.size.width}×${d.size.height}`,
      isPrimary: d.id === screen.getPrimaryDisplay().id,
      bounds: d.bounds,
    }))
  })
  
  // IPC: 別ウィンドウで動画を開く
  ipcMain.handle('open-video-window', (_, src: string, displayId: number) => {
    const display = screen.getAllDisplays().find(d => d.id === displayId)
    const win = new BrowserWindow({
      x: display.bounds.x,
      y: display.bounds.y,
      width: display.bounds.width,
      height: display.bounds.height,
      fullscreen: true,
      frame: false,
      title: 'ShuttleScope Video',
      webPreferences: { preload: ... }
    })
    win.loadURL(`${RENDERER_URL}#/video-only?src=${encodeURIComponent(src)}`)
  })
  ```

---

### T4-2: preload・型定義

**変更ファイル**:
- `electron/preload.ts` :
  ```typescript
  getDisplays: () => ipcRenderer.invoke('get-displays'),
  openVideoWindow: (src: string, displayId: number) => 
    ipcRenderer.invoke('open-video-window', src, displayId),
  ```
- `src/types/electron.d.ts` : 型定義追加

---

### T4-3: Video Only ページ

**新規ファイル**:
- `src/pages/VideoOnlyPage.tsx` :
  - URL パラメータから src を取得
  - VideoPlayer / WebViewPlayer を全画面表示
  - キーボードコントロール（Space: 再生/停止、←→: シーク）
  - 閉じるボタン（ESC）

---

### T4-4: アノテーション画面への統合

**変更ファイル**:
- `src/pages/AnnotatorPage.tsx` :
  - 起動時に `getDisplays()` を呼び出し
  - 2枚以上のディスプレイがある場合のみ「別モニタで動画表示」ボタンを表示
  - ボタン押下 → `openVideoWindow(src, secondaryDisplayId)`
  - 別ウィンドウを開いたら本体側の動画エリアを非表示（アノテーションパネル拡大）

**異常系**:
- 対象ディスプレイが見つからない場合は主画面内表示へフォールバック
- モニター抜去時は VideoOnlyWindow を閉じて本体側へ戻す
- `videoSourceMode === 'none'` の場合は別モニタ起動ボタンを出さない

```
[別モニタで動画表示 □] ← ディスプレイ2枚以上の場合のみ表示
```

---

## Phase 5: TrackNet リアルタイム補助（将来）

### T5-1: WebView フレームキャプチャ

**概要**: WebViewPlayer で表示中の中継映像からフレームを定期取得

**制約**:
- `webContents.capturePage()` は非同期で 5〜10fps 程度が上限
- CPU 負荷が高いため、on 状態でも低頻度（2fps）でのみ動作
- DRM / サイト実装 / GPU 構成により取得可否が変わる可能性が高い
- 将来フェーズであり、P5 は「成立検証」が主目的

**実装概要**:
- Electron IPC: `capture-webview-frame` → base64 PNG を返す
- バックエンド: `/api/tracknet/frame_hint` エンドポイント（単フレーム推論）
- 結果をアノテーション画面の hit_zone / land_zone に反映

**Go / No-Go 条件**:
- 低頻度でも現場で意味のあるヒント精度が出る
- annotator 操作のレスポンスを壊さない
- 一般的な中継サイトで再現可能な導線が確保できる
- いずれかを満たさない場合、P5 は実験機能のまま据え置く

---

### T5-2: タイムラグ補正

- キャプチャ → 推論 → UI 反映の遅延を計測
- 遅延が 2 秒以上の場合は自動的にリアルタイムモードを無効化し警告

---

## 横断的タスク

### TX-1: is_skipped のバックエンド修正

- `backend/routers/strokes.py` : empty strokes 許容
- `backend/db/database.py` : `add_columns_if_missing` に `is_skipped INTEGER DEFAULT 0` 追加
- `backend/analysis/` 系: `is_skipped=true` を解析から除外するフィルタを追加
- `backend/routers/reports.py` : skipped rally を含む指標 / 除外する指標を整理
- `src/components/analysis/` 系: score progression / set summary / sample size 表示の崩れ確認

### TX-2: 設定永続化基盤

- 現状: 設定は localStorage のみ
- 追加: `backend/routers/settings.py` でサーバー側にも保存（TrackNet設定など、アプリ再起動後も保持）
- `GET /api/settings` / `PUT /api/settings`
- P2 時点では localStorage 先行、P3 で API 化して一本化

### TX-3: テスト追加

- `backend/tests/test_skip_rally.py` : スキップラリーの保存・集計テスト
- `backend/tests/test_score_correction.py` : スコア補正の整合性テスト
- `backend/tests/test_tracknet_inference.py` : 推論エンドポイントのモックテスト
- `backend/tests/test_reports.py` / `backend/tests/test_analysis_endpoints.py` : skipped rally 導入後の既存分析回帰確認

---

## ファイル変更一覧

### Phase 1（見逃し入力）

| ファイル | 変更種別 |
|----------|---------|
| `backend/db/models.py` | Rally.is_skipped 追加 |
| `backend/db/database.py` | add_columns_if_missing 追加 |
| `backend/routers/strokes.py` | empty strokes 許容 |
| `backend/routers/analysis.py` | skipped rally 対応・分母調整 |
| `backend/routers/reports.py` | skipped rally を含む/除外する集計整理 |
| `src/types/index.ts` | Rally.is_skipped 型追加 |
| `src/store/annotationStore.ts` | skipRally / applyScoreCorrection アクション |
| `src/pages/AnnotatorPage.tsx` | 見逃しUI・スコア補正ダイアログ・強制セット終了 |
| `src/components/analysis/ScoreProgression.tsx` | skipped rally / 補正後の表示確認 |
| `src/components/analysis/SetIntervalSummary.tsx` | skipped rally 混在時の要約確認 |
| `src/i18n/ja.json` | skip_rally.* キー追加 |

### Phase 2（映像モード分岐）

| ファイル | 変更種別 |
|----------|---------|
| `src/types/index.ts` | VideoSourceMode 型追加 |
| `src/hooks/useMatchTimer.ts` | 新規 |
| `src/hooks/useSettings.ts` | 最低限の設定永続化 |
| `src/pages/AnnotatorPage.tsx` | モード切替UI・タイマー統合 |
| `src/i18n/ja.json` | timer.* キー追加 |

### Phase 3（TrackNet）

| ファイル | 変更種別 |
|----------|---------|
| `backend/tracknet/inference.py` | 新規 |
| `backend/tracknet/model.py` | 新規 |
| `backend/tracknet/convert.py` | 新規 |
| `backend/routers/tracknet.py` | 新規 |
| `backend/routers/settings.py` | 新規 |
| `backend/main.py` | ルーター登録 |
| `backend/requirements.txt` | openvino 追加 |
| `src/pages/SettingsPage.tsx` | 新規 or 拡張 |
| `src/hooks/useSettings.ts` | 新規 |
| `src/pages/AnnotatorPage.tsx` | バッチ解析ボタン・AI提案表示 |
| `src/i18n/ja.json` | tracknet.* / settings.* キー追加 |

### Phase 4（デュアルモニター）

| ファイル | 変更種別 |
|----------|---------|
| `electron/main.ts` | IPC追加 |
| `electron/preload.ts` | API追加 |
| `src/types/electron.d.ts` | 型追加 |
| `src/pages/VideoOnlyPage.tsx` | 新規 |
| `src/App.tsx` | ルート追加 |
| `src/pages/AnnotatorPage.tsx` | デュアルモニターUI |

---

## 実装手順（推奨順）

```
P1-T1-1: 見逃しラリー（SkipRally）
  → P1-T1-2: スコア補正
  → P1-T1-3: セット強制終了
  → P1-T1-4: i18n / 型
  → TX-1: analysis / reports 回帰確認
  → npm run build ✓ + pytest ✓ + validation doc

P2-T2-1: VideoSourceMode 型
  → P2-T2-2: useMatchTimer フック
  → P2-T2-3: none モード UI
  → P2-T2-4: webview モード整理
  → P2-T2-5: 最低限の設定永続化
  → npm run build ✓ + validation doc

P4-T4-1: Electron ディスプレイ検出
  → P4-T4-2: preload / 型
  → P4-T4-3: VideoOnlyPage
  → P4-T4-4: アノテーション統合
  → npm run build ✓ + validation doc

P3-T3-1: モデル準備（オフライン）
  → 基準機での go / no-go 確認
  → P3-T3-2: 推論バックエンド
  → P3-T3-3: サンプリング最適化
  → P3-T3-4: 設定UI
  → P3-T3-5: アノテーション統合
  → pytest ✓ + validation doc
```
