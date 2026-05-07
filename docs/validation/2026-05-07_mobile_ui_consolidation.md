# 2026-05-07 モバイル UI 仕上げ一括対応

`private_docs/2026-05-04_mobile_tile_hybrid_ui_implementation_plan.md`、
`private_docs/ShuttleScope_RESPONSIVE_UI_SPEC.md`、
`private_docs/RESPONSIVE_HEATMAP_IMPL_PLAN.md` の残作業を本コミットで一括対応。
ユーザの「iOS フォント縮小でタイル崩壊」「実装が進まない」をブロッカーとして
取り除くことが主目的。

private_docs は機密のため、本ドキュメントは概念単位の記載にとどめる。

## 1. iOS フォント縮小耐性 (タイル崩壊対策)

ユーザの最大の痛点。原因は `globals.css` の `font-size: 16px !important` が
input/select/textarea/contenteditable 限定で、**通常 `<button>` には適用されて
いなかった** こと。HitZoneSelector は `cellSize={60}` 固定 px、
ShotTypePanel は Tailwind 静的クラスでフォントスケール変動を吸収できず、
iOS の accessibility フォント縮小設定でタイルが崩れていた。

### 変更
- `globals.css`: `button[data-tile="true"]` および `button[data-tile="hit-zone"]` に
  `font-size: 16px !important / line-height: 1.15 / min-width: 7ch / min-height: 44px /
  touch-action: manipulation / overflow: hidden` を一括適用。
- `HitZoneSelector.tsx`: 9-zone セルに `data-tile="hit-zone"` を付与、
  `cellSize` は `Math.max(cellSize, 44)` で WCAG 2.5.5 推奨タッチターゲットを下回らない。
- `ShotTypePanel.tsx`: ショット種別ボタンに `data-tile="true"` を付与。

これにより iOS でフォント縮小しても min-w/min-h が崩壊を防ぎ、フォントは
16px に固定される。タイルレイアウトの崩壊を構造的に防止。

## 2. `useBreakpoint` 4 段階レスポンシブ hook

既存 `useIsMobile` は md=768px の単一しきい値。SPEC は xs / sm / md / lg / xl / 2xl
の 6 段階を要求していた。

### 追加
- `src/hooks/useBreakpoint.ts`: `bp` (現在の階級) + `atLeast(name)` + `below(name)` を返す。
- `BREAKPOINTS` 定数を `tailwind.config.js` の screens (xs:480, sm:640, md:768, lg:1024,
  xl:1200, 2xl:1440) と完全一致させる。乖離防止テスト付き。
- 既存 `useIsMobile` は後方互換のため残す。新規実装は `useBreakpoint` を使う。

## 3. iPad 縦持ち / 横持ち向けサイドバー (220px ラベル付き)

`App.tsx` のサイドバーは `w-16` (64px) のアイコン主体だった。lg+ (1024px〜) で
ラベル付き 220px に拡張。

### 変更
- `App.tsx:144` 付近: `md:flex w-16 lg:w-56` で md は icon-only / lg+ は
  icon+full-label の縦ナビ。NavLink / Logout / ThemeToggle 全て対応。
- `lg:flex-row lg:gap-3 lg:px-3` でレイアウト切替。
- ロゴ帯にも lg+ で "ShuttleScope" 文字列を表示。

`useBreakpoint` を使わず純 Tailwind 分岐で、SSR 安全 + リサイズ追従コスト 0。

## 4. Phase C `LiveInputPage` MVP scaffold

試合中専用フルブリード入力ページ。AnnotatorPage は機能豊富すぎて試合進行中に
向かないので、最小操作に絞った別ページを設計。

### 追加
- `src/pages/LiveInputPage.tsx` (約 200 行)
  - ルート `/live/:matchId` (App.tsx に登録)
  - フルブリード化: `App.tsx` の `isFullBleedPage` 判定を `/live` パスにも拡張、
    サイドバー / ボトムナビが非表示
  - 2 モードトグル: RALLY (ストローク入力) / RESULT (得点者・終了種別)
  - ストロークは `useAnnotationStore.inputShotType`、得点確定は
    `buildBatchPayload` / `buildSkippedRallyPayload` で `/strokes/batch` に POST
  - LiveInputPage は basic mode 固定 (試合中の素早い入力前提) で
    annotation_mode=`manual_record` を保存
- i18n: `annotator.live.tab_rally` / `annotator.live.tab_result` /
  `annotator.loading` / `annotator.back_to_matches` を ja/en 追加

### MVP の scope に含まれない (TODO、本 PR 後)
- キーボード操作 (現状は AnnotatorPage の useKeyboard が前提)
- 動画プレビューと一時停止連動
- オフライン同期 (useOfflineSync)
- ダブルス 4-quad 打者選択 (AnnotatorPage 既存実装を移植する)
- L-Audio: スコアコール時の音声フィードバック

これらは AnnotatorPage 側に既に実装済なので、必要になったら参照して移植する。
DB スキーマ変更ゼロ、本番 migration 不要。

## 5. Prediction タブの短縮ラベル

スマホ縦持ち (`md:` 未満) で predict / pair / lineup / forecast の長いラベルが
タブをはみ出していた。`useBreakpoint().below('md')` で `labelShort` に切り替え。

### 変更
- `src/pages/PredictionPage.tsx:200-218`: 各タブに `labelShort` を追加
- i18n に `prediction.title_short` / `pair_simulation_short` / `lineup_optimizer_short` /
  `human_forecast_short` を ja/en 追加

## 6. 汎用 `PlayerSelectorSheet`

既存 `BottomSheet.tsx` は AnnotatorPage 専用だったため、選手選択を mobile-first で
再利用できる薄いラッパーを抽出。

### 追加
- `src/components/common/PlayerSelectorSheet.tsx`
  - md 以上: 中央モーダル風、md 未満: 下からせり上がるシート
  - 検索インクリメンタルフィルタ (名前 / チーム名)
  - 選択直後に onSelect + onClose
  - 7 ケースの component test 付き

呼び出し側は `players={...}` を fetch して渡すだけ。既存ページの
`SearchableSelect` と置き換える経路は次のサイクルで段階移行。

## 7. 確認項目 (既に実装済 — 計画と現コードが乖離していなかった)

調査の結果、以下は既に実装済だったため変更不要:

- ダブルス 4-quad 打者選択 → `AnnotatorPage.tsx:3582+` で 4 ボタン横並び +
  キーボード 7/8/9/0 マッピング実装済
- autoFlip (auto / semi-auto / manual) → `SettingsModePanel.tsx:130-145`
- iOS 自動ズーム防止 (input/select/textarea) → `globals.css:212-241`
- Dashboard / Settings タブ横スクロール → 各 nav コンポーネントで適用済
- MatchListPage モバイルカード分岐 → `:891` (md:hidden) と `:1045` (md:table)

## 検証

### 追加した frontend テスト
- `src/hooks/__tests__/useBreakpoint.test.ts` (8 ケース) — 全 6 階級 + リサイズ + 値整合
- `src/components/common/__tests__/PlayerSelectorSheet.test.tsx` (7 ケース)

### 既存テスト
- 触らない範囲で 129 ケースが PASS していることを再確認 (build + vitest run)

### Build
- `npm run build`: PASS (`NODE_OPTIONS=--max-old-space-size=16384`)

## 影響

- DB スキーマ変更: なし
- バックエンドコード変更: なし
- 本番 migration: 不要
- Frontend bundle 増分: ~20KB (LiveInputPage + PlayerSelectorSheet + useBreakpoint)
- 既存ルート / ページ挙動: 不変 (新規 `/live/:matchId` 追加のみ)

## 残スコープ (今 PR 後)

| 項目 | 優先 | 備考 |
|---|---|---|
| LiveInputPage キーボード対応 | 中 | useKeyboard hook を分割再利用する設計検討要 |
| LiveInputPage 動画連動 | 中 | VideoPlayer を埋め込み、ストローク確定で pause |
| LiveInputPage オフライン同期 | 中 | `useOfflineSync` を流用 |
| LiveInputPage ダブルス 4-quad picker | 中 | AnnotatorPage 版を切り出し再利用 |
| L-Audio (得点コール音声) | 低 | Phase C 計画書の独立項目 |
| `useIsMobile` → `useBreakpoint` への段階移行 | 低 | 後方互換のため当面共存 |
| analysis_registry `check_or_raise` の各 router wiring | 中 | 別 PR (前 PR で計画済) |
| 本番 ScheduledTask の `/RU SYSTEM` 再登録 + supervisor 移行 | 高 | 別 ライン作業 (PROD_ENV_SPEC.md / INCIDENT_AND_RECOVERY.md 参照) |

## 関連

- `private_docs/2026-05-04_mobile_tile_hybrid_ui_implementation_plan.md`
- `private_docs/ShuttleScope_RESPONSIVE_UI_SPEC.md`
- `private_docs/RESPONSIVE_HEATMAP_IMPL_PLAN.md`
- 直前 PR `docs/validation/2026-05-07_followup_polish_and_security_scan.md`
