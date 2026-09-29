# ShuttleScope 機能ロードマップ B/D/E/C/A

作成: 2026-04-16

---

## 前提: アーキテクチャ確認

以下は **既にモデル・インフラが揃っている** ため、追加モデルマイグレーションなしで実装を開始できる。

| 項目 | 状態 |
|------|------|
| `Rally.video_timestamp_start/end` | ✅ 既存カラム（`models.py` L186-187） |
| `EventBookmark.video_timestamp_sec` | ✅ 既存カラム |
| `SharedSession`, `LiveSource`, `SessionParticipant` | ✅ 既存モデル（WebRTC/カメラソース対応済） |
| `doubles_cv_engine.py`, `doubles_role_inference.py` | ✅ 骨格実装済み |
| DashboardLivePage (FlashAdvice, IntervalReport) | ✅ 既存UI |

---

## B — 高速レビュー導線

### 目的
動画ローカル保存済み試合で、ラリー一覧をタイムスタンプ付きで表示し、クリックすると
その地点へビデオをジャンプさせる。失点パターン・得点パターン絞り込みも対応。

### 実装スコープ
- **Backend**: `GET /api/review/playlist?match_id=X[&winner=...&end_type=...&set_num=...]`
  - Rally + Set を JOIN し、video_timestamp_start が null でないラリーを返す
  - レスポンス: `{ has_timestamps: bool, rallies: [...] }`
- **Frontend**: `RallyClipNavigator` コンポーネント
  - ラリーリスト + フィルター（winner/end_type/set_num）
  - HTML5 `<video>` の `currentTime` を直接操作してジャンプ
  - video_local_path がある試合のみ有効化（`localfile://` プロトコル経由）
  - `DashboardReviewPage` の STEP 3（スコア推移）下に追加

### 制約
- `video_timestamp_start` が未記録のラリーはリストに表示するが「タイムスタンプ未設定」と表記
- 動画ファイルが存在しない場合はコンポーネント全体をグレーアウト

---

## D — セット間・試合中支援

### 目的
現場で試合中〜セット間に瞬時に読める「コーチ向け一言カード」を自動生成する。

### 実装スコープ
- `DashboardLivePage` に既存の FlashAdvice/IntervalReport に追加する形で実装
- **Backend**: `GET /api/analysis/quick_summary?match_id=X&as_of_set=N[&as_of_rally=R]`
  - 直近 N ラリーの偏り（相手配球ゾーン集中度、自軍の崩れ検出）
  - ルールベースで「一言カード」を生成（LLM 不要）
  - 判定ルール例:
    - 直近 5 ラリーで相手が同じゾーン(BL/BR)に 4 回以上 → 「相手 BL コーナーへの偏りあり」
    - 自軍 end_type=forced_error が直近 5 ラリーで 3 回以上 → 「強制エラー増加: 守備が崩れている可能性」
    - 自軍 score 連続失点 3 以上 → 「連続失点中: タイムアウト推奨」
- **Frontend**: `QuickSummaryCard` コンポーネント
  - DashboardLivePage の先頭に配置（試合選択後に表示）
  - カード形式で 1〜3 件のアドバイス表示、色分け（赤=警告/青=情報/緑=好調）

---

## E — データ資産化 (匿名化除く)

### 目的
試合データを JSON パッケージとしてエクスポート・インポートできるようにする。
チーム間共有・バックアップ・学習データ抽出に使う。

### 実装スコープ
- **Backend**:
  - `GET /api/export/package?match_id=X` → `PackageExport.json`
    - `{ version: "1.0", exported_at, match: {...}, sets: [...], rallies: [...], strokes: [...] }`
  - `POST /api/import/package` body: JSON パッケージ
    - 競合チェック: match.uuid が既存なら上書き確認フラグ `force=true` で上書き
    - Player は name マッチングで既存を再利用、未知なら新規作成
- **Frontend**: `MatchListPage` のマッチカード右上に「パッケージ出力」ボタン追加
  - インポートは SettingsPage のデータ管理タブに `<input type="file" accept=".json">` で実装

---

## C — マルチアングル同期 (iOS/ネットワークカメラ)

### 現状
`LiveSource`, `SharedSession`, `SessionParticipant`, `CameraSenderPage.tsx` は既に存在する。
WebRTC signalingの基盤 (`iphone_webrtc` source_kind) も定義済み。

### 追加実装スコープ
- カメラ上限: **4台**（`LiveSource.source_priority` 1〜4 で管理）
- **カメラ管理 UI** (`sessions.tsx` 拡張):
  - 接続デバイス一覧（`GET /api/sessions/{code}/devices`）
  - 各デバイスのカメラ有効化ボタン（最大 4 台）
  - 優先度設定（主カメラ/副カメラ/参考カメラ）
- **iOS カメラ送信側** (`CameraSenderPage.tsx`):
  - WebRTC getUserMedia → PeerConnection → シグナリングサーバへ送信
  - 既存の MJPEG/WebSocket ベースから WebRTC に移行（低遅延化）
- **シグナリングエンドポイント** (`backend/routers/sessions.py` 拡張):
  - `POST /api/sessions/{code}/webrtc/offer` — SDP offer 受付
  - `GET  /api/sessions/{code}/webrtc/answer/{participant_id}` — SDP answer 返却
  - `POST /api/sessions/{code}/webrtc/ice` — ICE candidate 交換
- **4カメラ合成ビュー** (アノテーターページ右パネル):
  - 2×2 グリッドで 4 カメラ同時表示
  - メインカメラ（クリックで拡大）切替
  - `annotation_mode=multi_camera` 対応

### 設計注意
- 合成・残像表現は実装しない（Dartfish回避）
- `source_kind` の拡張: `iphone_webrtc` / `ipad_webrtc` / `android_webrtc` / `pc_local` / `usb_camera`
- LAN内 STUN サーバ不要で動くよう、同一サブネット前提で実装

---

## A — ダブルス4人同時追跡 + 役割推定

### 現状
- `doubles_cv_engine.py`: YOLO artifacts → position summary
- `doubles_role_inference.py`: ルールベース役割推定骨格
- Stroke モデル: `partner_a`, `partner_b` カラム存在、`player_x/y`, `opponent_x/y` もある

### 追加実装スコープ

#### フェーズ 1: 位置データモデル
- 新モデル `PlayerPositionFrame` を追加 (migration 0006):
  ```
  id, match_id, set_id, rally_id, frame_num,
  player_a_x, player_a_y,
  player_b_x, player_b_y,
  partner_a_x, partner_a_y,  -- doubles のみ
  partner_b_x, partner_b_y,  -- doubles のみ
  shuttle_x, shuttle_y,
  source  -- yolo_tracked / manual / interpolated
  ```

#### フェーズ 2: YOLO 4人追跡
- `yolo_realtime.py` に `doubles_mode=True` パラメータ追加
- RTX 5060 Ti 到着後: `yolov8m.pt` (medium) または `yolov8l.pt` (large) に切替
- 検出クラス: `person` を最大 4 検出、コート座標系へ射影
- 追跡: ByteTrack で ID を維持し、4選手 ID をセッション内で固定

#### フェーズ 3: 役割推定ルール
- 前衛/後衛判定: コート Y 座標中央を閾値に F/B 分類
- 平行陣検出: player_a_y と partner_a_y の差が閾値以下
- ローテーション検出: 連続フレームでの前衛/後衛交代カウント
- 実装場所: `doubles_role_inference.py` 拡張

#### フェーズ 4: アノテーション UI 刷新
- 現状の縦並びボタン配列 → タブレット縦持ち最適化レイアウト
- 右パネル: 4カメラ映像 (フェーズ C 完了後)
- 左パネル: コート俯瞰 + 4選手リアルタイムポジション表示
- ダブルス専用タグ: 陣形ラベル付与ボタン

### 制約
- 役割分類モデル（ML）の学習は実績が 5 試合以上蓄積後
- ペア相性スコアは Phase 3 以降（蓄積待ち）
- 非打者位置は YOLO 追跡から得る（手動入力は対象外）

---

## 実装順序

```
[完了] Rally.video_timestamp_start/end 存在確認
  ↓
[39] B: RallyClipNavigator (backend playlist + frontend)
  ↓
[40] E: Package export/import (backend + UI)
  ↓
[D]  QuickSummaryCard (backend rules + frontend card)
  ↓
[C]  Multi-camera: WebRTC signaling + 4cam UI
  ↓
[A1] PlayerPositionFrame モデル追加
[A2] YOLO doubles_mode 拡張
[A3] 役割推定ルール実装
[A4] アノテーション UI 刷新
```

---

## 検討事項 (未決定)

- C のシグナリング方式: WebSocket ベース or Server-Sent Events
- A の YOLO モデルサイズ: 速度vs精度トレードオフ（5060 Ti 到着後に実測）
- ペア相性スコアのアルゴリズム: ベイズ勝率推定 vs 単純統計
