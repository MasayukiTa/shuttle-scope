# ShuttleScope — Court Calibration / YOLO ROI / Doubles Fixes Implementation
**Date:** 2026-04-11

---

## 1. 概要

このセッションで実装した内容の全記録。  
大きく5テーマに分かれる。

1. 試合登録フォーム（ダブルス対応）修正
2. YouTube URL 再生バグ修正
3. コートグリッドオーバーレイ（フロントエンド）
4. ダブルスアノテーション UI 再設計
5. コートキャリブレーション バックエンド＋YOLO ROI 統合

---

## 2. 試合登録フォーム修正

### 変更ファイル
- `src/pages/MatchListPage.tsx`

### 問題
- `player_a`（対象選手）が選択不可
- `partner_a` / `partner_b` で新規選手を暫定登録できない
- `mens_doubles` がフォーマット選択肢に存在しない
- ダブルス時のレイアウトが分かりにくい（A側/B側が混在）

### 実装内容
- ローカル `PlayerCombobox` コンポーネント追加
  - フリーテキスト検索 + 登録済み選手サジェスト
  - 「暫定登録して作成」ボタン（`createProvisionalPlayer` 呼び出し）
- `mens_doubles` をフォーマット選択肢に追加
- ダブルスの選手欄を A側（左）/ B側（右）の2列レイアウトに変更
- `resetPlayerFields()` で全 combobox 状態リセット
- `handleSubmit` で4選手すべての暫定登録フローを処理

---

## 3. YouTube URL 再生バグ修正

### 変更ファイル
- `src/pages/AnnotatorPage.tsx`（約 line 1037 付近）

### 問題
YouTube URL を動画ソースに設定しても「カメラ映像待機中...」のまま再生されない。

### 根本原因
`detectStreamingSite` で YouTube URL を検知 → `setVideoSourceMode('webview')` が実行される。
`videoSourceMode === 'webview'` の render ブロックはカメラストリーム（null）の場合に早期 return するため、
`streamingSiteName` チェックが走らず `StreamingDownloadPanel` に到達しない。

### 修正
```diff
- setVideoSourceMode(site ? 'webview' : 'local')
+ setVideoSourceMode('local')  // webview はカメラ専用。YouTube は local + streamingSiteName で処理
```

---

## 4. コートグリッドオーバーレイ（CourtGridOverlay）

### 新規ファイル
- `src/components/video/CourtGridOverlay.tsx`

### 機能
- 6点キャリブレーション: TL / TR / BR / BL（4コーナー）＋ NetL / NetR（ネット支柱）
- 上半面（TL,TR,NR,NL）・下半面（NL,NR,BR,BL）を各 3×3 グリッドで台形補間（`lerp`）
- ネットライン：オレンジ（`#ff9900`）
- グリッドライン：ホワイト（`#ffffff`）strokeWidth=1.5, opacity=0.85
- キャリブレーション点：ドラッグで任意タイミングに調整可能
- 表示/非表示トグル（visible prop）
- 再キャリブレーションボタン
- 永続化：localStorage `court-calib-{matchId}` → バックエンド POST（優先度はバックエンド > localStorage）

### バックエンド同期（後述 §6 で実装）
- マウント時: `GET /api/matches/{id}/court_calibration` → 失敗時 localStorage フォールバック
- 6点完了時: `POST /api/matches/{id}/court_calibration` で保存（ドラッグ完了ごとにも POST）

### 変更ファイル（統合）
- `src/components/annotator/AnnotatorVideoPane.tsx`
  - `courtGridMatchId?: string`, `courtGridVisible?: boolean` props 追加
  - `CourtGridOverlay` レンダリング追加
- `src/pages/AnnotatorPage.tsx`
  - `const [courtGridVisible, setCourtGridVisible] = useState(false)` 追加
  - CV オーバーレイグループにトグルボタン追加
  - `AnnotatorVideoPane` に `courtGridMatchId` / `courtGridVisible` props 渡し

---

## 5. ダブルスアノテーション UI 再設計

### 変更ファイル
- `src/pages/AnnotatorPage.tsx`
- `src/store/annotationStore.ts`

### 問題（3つのバグ）

**Bug 1:** `setHitter` が `currentPlayer` を同期しないため、着地ゾーンが逆コート側に表示される。
```diff
- setHitter: (h) => set({ currentHitter: h }),
+ setHitter: (h) => set({
+   currentHitter: h,
+   currentPlayer: (h === 'player_b' || h === 'partner_b') ? 'player_b' : 'player_a',
+ }),
```

**Bug 2:** 打者セレクタ表示条件が `isRallyActive && inputStep === 'idle'` だったため、
ラリー開始直後（`inputStep === 'land_zone'`）に選択不能。
```diff
- isRallyActive && inputStep === 'idle'
+ inputStep !== 'rally_end'
```
（ラリー開始前～打者選択中～着地ゾーン入力中すべてで表示）

**Bug 3:** 打者セレクタが現チームの2人しか表示しないため、チーム切替後に相方が消える。

### 実装: 4プレイヤー常時表示パネル
```tsx
// A側2人 | 区切り | B側2人 を常時表示
<button onClick={() => store.setHitter('player_a')}  ...>{nameA}</button>
<button onClick={() => store.setHitter('partner_a')} ...>{namePA}</button>
<div className="w-px self-stretch mx-0.5 bg-gray-600" />
<button onClick={() => store.setHitter('partner_b')} ...>{namePB}</button>
<button onClick={() => store.setHitter('player_b')}  ...>{nameB}</button>
```
- 選択中：A側=青、B側=オレンジ
- 現チーム（currentPlayer）の2人が明るく、相手チームはやや暗く
- `inputStep !== 'rally_end'` の間は常時表示

---

## 6. コートキャリブレーション バックエンド

### 新規ファイル
- `backend/routers/court_calibration.py`

### エンドポイント
| メソッド | パス | 概要 |
|---|---|---|
| POST | `/api/matches/{match_id}/court_calibration` | 6点保存、ホモグラフィ計算 |
| GET  | `/api/matches/{match_id}/court_calibration` | キャリブレーション取得（未設定=404） |

### アルゴリズム
- **DLT ホモグラフィ**: 4コーナー対応から 8×9 行列を構成し SVD の最右特異ベクトルを 3×3 に reshape
  - 画像正規化座標（0-1）→ コート正規化座標（TL=0,0 / TR=1,0 / BR=1,1 / BL=0,1）
- **逆ホモグラフィ**: `np.linalg.inv` でコート座標 → 画像座標（SVGオーバーレイ再描画用）
- **18ゾーン分類**: col ∈ {left,center,right} × row ∈ {A_front,A_mid,A_back,B_front,B_mid,B_back}
- **ROI 多角形**: 4コーナーの正規化座標をそのまま保存（Ray casting でコート内外判定）

### 保存データ（MatchCVArtifact, artifact_type="court_calibration"）
```json
{
  "points": [[x,y], ...],          // 6点の正規化座標
  "homography": [[...],[...],[...]], // 3×3 H 行列
  "homography_inv": [...],           // 逆ホモグラフィ
  "roi_polygon": [[x,y],[x,y],[x,y],[x,y]],  // 4コーナー
  "net_court_coords": { "left": [...], "right": [...], "y_avg": 0.500 },
  "container_size": { "w": 1280, "h": 720 },
  "calibrated_at": "2026-04-11T..."
}
```

### `main.py` 登録
```python
from backend.routers import court_calibration
app.include_router(court_calibration.router, prefix="/api")
```

---

## 7. フロントエンド ホモグラフィユーティリティ

### 新規ファイル
- `src/utils/courtHomography.ts`

### 関数
| 関数 | 概要 |
|---|---|
| `applyHomography(H, x, y)` | 3×3 H 行列を正規化座標に適用 |
| `courtCoordToZone(cx, cy)` | コート座標 → 18ゾーン情報 |
| `pixelNormToZone(H, x, y)` | 画像座標 → 18ゾーン（一発変換） |
| `isInsideCourt(x, y, polygon)` | Ray casting ROI 判定 |

---

## 8. YOLO ROI フィルタ統合

### 変更ファイル
- `backend/routers/video_import.py`（`_run_yolo` 関数）

### 変更内容
YOLO ジョブ開始時にコートキャリブレーションを読み込み、各フレームの検出を ROI でフィルタリング:

```python
from backend.routers.court_calibration import load_calibration_standalone, is_inside_court

calib = load_calibration_standalone(match_id)
roi_polygon = calib["roi_polygon"] if calib else None

# フレーム処理ループ内
if roi_polygon:
    players = [p for p in players if is_inside_court(
        p["foot_point"][0], p["foot_point"][1], roi_polygon
    )]
    # foot_point がない場合は bbox 下辺中央を使用
```

- キャリブレーション未設定の場合は全検出をそのまま使用（後方互換）
- `foot_point`（YOLO 推定足元座標）を優先、なければ bbox 下辺中央

---

## 9. TrackNet homography ゾーン精緻化

### 変更ファイル
- `backend/routers/video_import.py`（`_run_tracknet` 関数末尾）

### 変更内容
TrackNet 解析完了後、コートキャリブレーションが設定済みなら各 track point に homography を適用してゾーンを上書き:

```python
from backend.routers.court_calibration import load_calibration_standalone, pixel_to_court_zone

calib = load_calibration_standalone(match_id)
if calib and "homography" in calib:
    H = calib["homography"]
    for pt in track:
        xn, yn = pt.get("x_norm"), pt.get("y_norm")
        if xn is not None and yn is not None:
            zone_info = pixel_to_court_zone(xn, yn, H)
            pt["zone"]    = zone_info["zone_name"]  # 既存 zone を homography で上書き
            pt["court_x"] = zone_info["court_x"]
            pt["court_y"] = zone_info["court_y"]
            pt["zone_id"] = zone_info["zone_id"]
```

- キャリブレーション未設定時は TrackNet モデルのゾーン推定をそのまま使用
- `zone_name` 例: `"B_mid_left"` → CV アシストの `landing_zone` 候補として活用可能

---

## 10. POST debounce & YOLO 再実行案内

### 変更ファイル
- `src/components/video/CourtGridOverlay.tsx`

### (1) ドラッグ中 POST 連打を防ぐ debounce
`postTimerRef`（useRef）で 400ms debounce を実装。ドラッグ完了後 400ms 無操作で1回だけ POST。

```tsx
const postTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

// savePts 内
if (pts.length === TOTAL_POINTS) {
  if (postTimerRef.current) clearTimeout(postTimerRef.current)
  postTimerRef.current = setTimeout(() => postToBackend(pts), 400)
}
```

### (2) 保存完了後 YOLO 再実行案内
POST 成功時に `savedNotice` state を 6秒間 true にし、画面上部にトースト表示:

```
[↻] ROI 保存完了 — YOLO を再実行すると精度が上がります
```

---

## 11. 未着手（設計のみ）

### 選手 ID 紐付け（bbox → player_a/b 名前タグ）
YOLO 検出 bbox にプレイヤー名を紐付ける機能は設計のみで未実装。
静止フレーム手動タグ付け → カラーヒストグラム or 位置ヒューリスティックで追跡する実装が必要。

---

## 10. ファイル変更一覧

| ファイル | 種別 | 内容 |
|---|---|---|
| `src/pages/MatchListPage.tsx` | 変更 | PlayerCombobox・mens_doubles・ダブルスレイアウト |
| `src/pages/AnnotatorPage.tsx` | 変更 | YouTube修正・コートグリッドトグル・4プレイヤーパネル |
| `src/store/annotationStore.ts` | 変更 | `setHitter` → `currentPlayer` 同期 |
| `src/components/video/CourtGridOverlay.tsx` | 新規 | SVGグリッド・6点キャリブレーション・バックエンド同期 |
| `src/components/annotator/AnnotatorVideoPane.tsx` | 変更 | CourtGridOverlay 統合 |
| `src/utils/courtHomography.ts` | 新規 | ホモグラフィ・18ゾーン・ROI判定 |
| `backend/routers/court_calibration.py` | 新規 | DLTホモグラフィ・POST/GETエンドポイント |
| `backend/main.py` | 変更 | court_calibration router 登録 |
| `backend/routers/video_import.py` | 変更 | `_run_yolo` ROI フィルタ、`_run_tracknet` homography ゾーン精緻化 |
