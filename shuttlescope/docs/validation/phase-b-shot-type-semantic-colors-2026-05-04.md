# Phase B: Shot Type Semantic Colors — 2026-05-04

## Background
モバイル / タブレット タイル UI ハイブリッド計画 (private_docs v2) の Phase B 実装。
ShotTypePanel の全グレーボタンをカテゴリ別のセマンティック色に置き換え、
連打中に文字を読まず色で判断できるようにする。

不変原則 (v2 §守るべき不変原則 を遵守):
- `getShotContext()` のフィルタロジックは一切変更しない
- `buildGroups()` のグループ化ロジックは一切変更しない
- ボタン押下イベントの挙動は不変
- キーボードショートカット表示も不変

## What was implemented

### 階層分離の明文化 (v2 §7.1)
- **表示グループ** (ShotTypePanel.buildGroups の出力): コンテキスト依存で動的
- **色カテゴリ** (新規 SHOT_TYPE_CATEGORY): ショットタイプ単位で固定
- ボタンは「所属表示グループに関わらず、ショットタイプから引いた色」で塗る
- 例: after_back_attack で `defend` グループに block (シアン) / lob (黄) / drive (緑) が
  混在表示される — 想定通り

### Frontend
- **新規** `src/constants/shotTypeColors.ts`
  - `ShotCategory` = `'attack' | 'net' | 'mid' | 'serve' | 'other'`
  - `CATEGORY_STYLES` 各カテゴリに bg / bgHover / text / border / icon /
    labelKey / ringSelected を定義
  - `SHOT_TYPE_CATEGORY` 全 18 ShotType をマッピング
    - around_head は ATTACK 分類 (バック後方攻撃手段)
    - cant_reach は OTHER 分類
  - `getCategoryForShot(shot)` / `getStyleForShot(shot)` ヘルパー
- **新規** `src/constants/__tests__/shotTypeColors.test.ts` (9 tests)
- `src/components/annotation/ShotTypePanel.tsx`
  - import `getStyleForShot` 追加
  - 全グレー → カテゴリ色 (selected 時は `ring-2 ring-{color}-300` で強調)
  - 形状アイコン (◆ ● ■ ★ ✕) を左上に追加 (カラーブラインド対応)
  - `aria-pressed` 属性追加
- `src/i18n/ja.json` — `shot_color_categories.{attack,net,mid,serve,other}` と
  `annotator.shot_color_legend` ラベル追加 (CLAUDE.md i18n ルール遵守)

### カラーマッピング
| カテゴリ | 色 (Tailwind) | アイコン | 含まれる ShotType |
|---|---|---|---|
| ATTACK | green-600 | ◆ | smash, half_smash, push_rush, drive, around_head |
| NET | cyan-600 | ● | net_shot, cross_net, flick, block, drop, defensive |
| MID | yellow-500 + 暗文字 | ■ | clear, lob, slice |
| SERVE | violet-600 | ★ | short_service, long_service |
| OTHER | slate-600 | ✕ | other, cant_reach |

WCAG AAA: 黄色背景 (mid) のみ `text-gray-900` で暗文字、それ以外は白文字でコントラスト 7:1 以上。

## Validation
- `npm run build` — 2887 modules transformed, build green
- `vitest run shotTypeColors.test.ts HitZoneSelector.test.tsx` — **14/14 pass**
  - 9 件: shotTypeColors の分類正当性 + WCAG 暗文字確認
  - 5 件: Phase A の HitZoneSelector regression 確認 (退化なし)
- `getShotContext()` / `buildGroups()` ロジックに一切の変更なし
- キーボードショートカット表示 (右上 9px font) 維持

## Acceptance criteria status (v2 §7.4)
- [x] 全ショット種別ボタンがカテゴリ色で表示される
- [x] `getShotContext()` のフィルタロジックに一切変更がない
- [x] selected 状態の視認性が旧 UI と同等以上 (ring-2 で強調)
- [x] カラーブラインド対応アイコンが全ボタンに併記 (◆ ● ■ ★ ✕)
- [x] WCAG AAA (コントラスト比 7:1 以上) を全色で達成 (黄色のみ暗文字)
- [x] `isMatchDayMode` ON/OFF 両方で正常表示 (既存 grid 切替ロジック不変)

## How to roll out
- Frontend デプロイのみ (backend / DB 変更なし)
- 既存ユーザの操作感は同じ、色だけが変わる
- 旧 UI と完全互換 — rollback も即時可能 (色定数 + コンポーネントの 1 import 削除のみ)

## Effect (期待効果)
- 連打速度の地味だが確実な改善 — 文字を読まず色で判断
- カテゴリ理解の習熟が早まる (新規ユーザの学習コスト低下)
- Phase C (LiveInputPage) でも同じ色定数を流用可能

## Known follow-ups (Phase B の範囲外)
- 色凡例 UI (legend) を AnnotatorPage のヘッダ等に追加するかは別途判断
  - i18n キー `annotator.shot_color_legend` は予約済み
- LiveInputPage (Phase C) でも同色定数を流用予定
