# Phase C Speed Slice — 2026-05-04

## Background
モバイル UI ハイブリッド計画 (private_docs v2) Phase C の **速度向上に直接寄与する部分のみ**
を先行実装。LiveInputPage 新設は Phase A+B のドッグフード完了まで保留。

含まれる: 触覚フィードバック / セミ自動 flip / 既存 UI のコントラスト不具合修正。

## Audit findings & fixes

### 色コントラスト issue 1 (致命的)
- ShotTypePanel の selected 状態が `ring-{color}-300` で、同色 bg-{color}-600 と
  同一系統のため視認差が弱い。連打中に「今選んでるショット」が目視困難。
- → 全カテゴリの `ringSelected` を `ring-2 ring-white ring-offset-2 ring-offset-gray-900`
  に統一。白リング + ダークオフセットで selected が一目瞭然。

### 色コントラスト確認 (問題なし)
- HitZoneSelector: 全ての色付き bg は `text-white` または mid yellow に対する
  `text-gray-900` で WCAG AAA 7:1+ を達成済み。問題なし。
- AttributePanel: 紫 bg + white text、グレー bg + light text、問題なし。
- ShotTypePanel mid (黄) は `text-gray-900` 維持で正しい。

## What was implemented

### 1. 触覚フィードバック (`src/hooks/useHapticFeedback.ts`)
- 新規 hook。5 種パターン (tap / strokeConfirm / undo / modeSwitch / error)
- `navigator.vibrate` 非対応 / 例外時は graceful no-op
- AnnotatorPage で以下にワイヤ:
  - ショット種別タップ → `tap()` (20ms)
  - 落点タップ (CourtDiagram) → `strokeConfirm()` ([10,30,10] 二段ブレ)
  - 落点スキップ → `strokeConfirm()`
  - HitZoneSelector タップ → `tap()`
  - Undo → `undo()` (60ms)

### 2. セミ自動 flip (`src/store/annotationStore.ts`)
- 新規 state: `flipMode: 'auto' | 'semi-auto' | 'manual'`、デフォルト `'semi-auto'`
- 新規 state: `lastFlipAt`, `playerBeforeFlip` (bounce revert 用)
- 新規 action: `setFlipMode(mode)` — localStorage `ss_flip_mode` に永続化
- 動作:
  - **auto**: 既存挙動 (selectLandZone/skipLandZone で常に flip)
  - **semi-auto**: flip するが、500ms 以内の次 inputShotType で flip を revert
    (= バウンス対策。連続して同じ打者の打ちこぼしを記録する場面)
  - **manual**: flip しない (打者 tap が常に必要)
- ループする: `selectLandZone` / `skipLandZone` で `lastFlipAt = Date.now()`,
  `playerBeforeFlip = (flip 前の player)` を記録 → 次 `inputShotType` で
  `Date.now() - lastFlipAt < 500` なら revert。

### 3. ShotTypePanel selected ring 修正
- `src/constants/shotTypeColors.ts` の全カテゴリ `ringSelected` を統一
- 旧: `ring-2 ring-{color}-300` → 新: `ring-2 ring-white ring-offset-2 ring-offset-gray-900`

## Validation
- `npm run build` — 2888 modules transformed, build green
- `vitest run` — **24/24 pass**
  - 5 件: useHapticFeedback (vibrate 呼出パターン + degradation)
  - 5 件: annotationStore.flipMode (auto/manual/semi-auto + bounce 500ms 境界 + persistence)
  - 9 件: shotTypeColors (Phase B regression)
  - 5 件: HitZoneSelector (Phase A regression)
- 既存挙動への影響: デフォルト semi-auto で発生する revert は **連続 500ms 以内の
  次ショットがあった場合のみ**。通常ペースの入力では auto と完全同一の挙動。

## Acceptance criteria
- [x] 連打時の触覚 FB (デバイス対応のみ)、非対応で例外なし
- [x] semi-auto bounce revert が 500ms 境界で正しく動作
- [x] manual モードで flip しない
- [x] flipMode 設定が localStorage 経由で永続化
- [x] selected ring が白で全カテゴリ視認可能
- [x] 既存ユニットテスト regression なし

## Out of scope (Phase C 残部)
- LiveInputPage 新設 (試合中専用フルブリード UI) — ドッグフード後判断
- RALLY/RESULT 全画面モード切替 — LiveInputPage 内でのみ実装予定
- セミ自動 flip 設定 UI (現状は localStorage 直接 or DevTools 経由)
  - 設定 UI が必要になったら SettingsPage か LiveInputPage の ⚙ メニューに追加
- サーブミス検知 (同じ打者 2 連続) → タイル脈動表示 — LiveInputPage で実装
- ダブルス対応の 4 分割打者タイル — Phase 5 (別フェーズ)

## Effect (期待効果)
- 連打速度の体感向上 (タップ応答性が触覚で確認可能)
- 同コート連続打 (壁打ち的処理) の入力ミス防止 (semi-auto)
- selected ショットが一目で分かる (白 ring)
- 既存ユーザの操作感を破壊せず、上記が「いつの間にか速くなる」体験
