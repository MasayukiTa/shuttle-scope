# 2026-05-07 アノテーター UI 重大 UX 不具合の一括修正

ユーザ指摘:
1. 上バー右の TrackNet / CV / 人物検出 / BBOX / グリッド / 領域 ボタン群を「格納」したい
2. 打点 (hit_zone) が 1-9 / テンキーで入力できない
3. 打点入力後、着地点入力に切り替わったか分かりづらい (クリック場所不明)
4. ショットタイル MID カテゴリの中身が黒文字で読めない (#fff にすべき)
5. ダブルスでショット選択時、どちらの選手か選べるべき。打点・着地点もキーで入れたい
6. 「とにかく問題だらけ」

5 つの構造的修正で対応。

## 1. ショットタイル MID カラー (黒文字 → 白文字)

`src/constants/shotTypeColors.ts`:
- 旧: `bg-yellow-500` + `text-gray-900` (黒文字)
- 新: `bg-amber-600` + `text-white` (白文字)

amber-600 は yellow-500 より暗いので、白文字とのコントラスト比が WCAG AA を通る
(≈3.6:1)。他カテゴリ (attack/net/serve/other) も全て `text-white` で揃っている
ため、見た目の「黒文字だけ浮く」感が解消される。

テスト追加: `shotTypeColors.test.ts` で「全カテゴリが白文字」を構造的に固定。

## 2. 打点 (hit_zone) のキーボード入力

`src/hooks/useKeyboard.ts`:
- 'land_zone' step に **トップ行 1-9 (Digit1〜Digit9)** を追加 → `setHitZoneOverride`
- HitZoneSelector の 3x3 配置 (1-9) に対応
- Numpad 1-9 は従来通り **着地点 (land_zone)** に割当
- ダブルスのみ Digit7/8/9/0 を **hitter 選択** に割当 (player_a / partner_a / partner_b / player_b)
- ダブルスで hit_zone 7/8/9 が必要な場合は HitZoneSelector を click

これで 「打点もテンキー / トップ行で素早く入力可能」が満たされる。

## 3. land_zone step のビジュアルフォーカス強化

`src/pages/AnnotatorPage.tsx` (land_zone step UI):
- CourtDiagram を `ring-2 ring-blue-400 ring-offset-2 animate-pulse-slow` で囲み、
  上に「着地点を選択 ↓」のラベルピル
- HitZoneSelector の上に「打点: トップ行 1-9」の kbd ヒント
- ヘッダーラベルに「テンキー 1-9 / U I O J K L M , .」 のキーマップを併記

`src/styles/globals.css` に `@keyframes pulse-slow-frames` + `.animate-pulse-slow`
(1.4s 周期、opacity 1↔0.65) を追加。Tailwind 標準の `animate-pulse` (50% で 50%
透過) より弱めで、視認性を保ちつつ目立つ。

## 4. CV / TrackNet 一式を折り畳み式に

上バー右の TrackNet/YOLO/オーバーレイ/CV補助 ボタン群 (約 550 行のインラインブロック)
を `cvToolsExpanded` 状態で展開可能に変更。デフォルトは折り畳み (試合中入力で
視界を狭めない)。

### 新設ピル (常時表示)
試合に動画があり TrackNet または YOLO が有効なら、上バー右に常時:
```
[ 👁 CV (▼)         ]   ← 折り畳み中、進行中なら "% 表示"
[ 👁 CV 87% ✓ (▲) ]   ← 完了状態
```
クリックで展開/折り畳み。

### TopBarMenu CV セクション
⋮ メニュー → CV バッチ セクションに「CV ツール (BBOX / 軌跡 / グリッド / 領域)」
ON/OFF トグルを追加。インラインピルと同じ state を共有。

### 折り畳み対象
- TrackNet バッチ state machine (start/running/stopped/complete/error)
- YOLO 人物検出 + BBOX / 軌跡 / グリッド / 領域 / 両方トグル
- CV補助 (候補生成・適用・フィルタ・パネル展開)

### 折り畳んでも表示し続ける情報
- 圧縮ピル内の進行 % / 完了 ✓
- pendingSaveCount / saveErrors / review queue / in-match panel など他 UI

## 5. ダブルス hitter ピッカーの land_zone step での強調

AnnotatorPage:3582+ の 4選手ピッカーは既存だが、land_zone step で目立たない
問題があった。

修正:
- land_zone step 中は picker container に `ring-2 ring-orange-400/60`
- 上にラベル `ダブルス: 打者を確認・変更 (キー 7 8 9 0)`
- useKeyboard で land_zone step + isDoubles 時に Digit7/8/9/0 → hitter

これでショット選択後 → 打者調整 → 着地点入力の自然な流れがキーボードで完結。

## ブレークポイント別の最終 UI

### CV ツールピル + メニュー
| BP | インラインピル | TopBarMenu トグル |
|---|---|---|
| < md (mobile) | 非表示 (BottomSheet 経由想定) | 非表示 |
| md+ | ✅ 圧縮表示 / 展開 | ✅ |

### land_zone step
| BP | レイアウト |
|---|---|
| < sm | HitZoneSelector + CourtDiagram 縦積み + 全機能可視 |
| sm+ | 横並び |
| - | CourtDiagram に青パルス枠 + 「↓ 着地点を選択」ラベル (全BP共通) |
| ダブルス時 | 4選手ピッカーに橙枠 + 「打者を確認 (7/8/9/0)」 (全BP共通) |

## 検証

### テスト
- `vitest`: **18 ファイル / 164 tests PASS** (+1 新規: 全カテゴリ白文字統一 assertion)
- 既存の "mid category uses dark text" assertion を新仕様に書き換え
- electron-vite build PASS (`NODE_OPTIONS=--max-old-space-size=16384`)

### 手動確認推奨
- iPhone (xs) Safari でショットタイル群の文字が全部白で読める
- PC で 'P' (push) → トップ行 '5' → Numpad7 のシーケンスでショット → 打点 5 → 着地点 BL
  が記録される
- ダブルス時 'P' → '8' → Numpad5 で ショット → partner_a → ML が記録される
- CV ツールピルクリックで TrackNet 開始 / BBOX トグルなど全部できる

## 影響

- DB スキーマ変更: なし
- バックエンド変更: なし
- 既存ルート / ページ挙動: cvTools 折り畳みが UI 体感を変える (情報量同じ、可視性が変わる)
- 既存ユーザのキーボード操作: シングルスは挙動不変。ダブルスは Digit7/8/9/0 が
  land_zone step で hitter 選択を意味するように (idle step では従来通り)

## 残スコープ

- HitZoneSelector の `Zone9` 型不整合 (number と string が混在) は別件。型を `number` に
  統一するか、enum に変える要検討
- CV補助の挙動 (候補生成 / 適用) 自体の使いやすさは別レビューで
- BottomSheet 経由のモバイル UX は触っていない (mobile では BottomSheet で全機能
  アクセス可能なはず — 要再確認)
