# Annotator UX Redesign (U1–U8) — 2026-05-04

ベース: `private_docs/2026-05-04_annotator_ux_redesign_proposal.md` + `…_addendum.md`
方針 (addendum §1): 段階リリースではなく一括実装、ただし順序厳守 + フェーズ別 commit

## 完了サマリ

| Phase | 概要 | 主な成果物 | コミット |
|---|---|---|---|
| U1 | 上バー圧縮 (Score 中央 + ⋮ menu) | `TopBarMenu.tsx` / `TopBarScore.tsx` / 二次ボタン xl 隠し | `09c3c8f` + `f7eaaff` |
| U2 | 4 モードタブ (入力/確認/解析/設定) + Material Symbols 採用 | `ModeTabs.tsx` / `MIcon.tsx` / `annotatorModeStore.ts` / `material-symbols` 導入 | `12339f1` |
| U3 | モード別右パネル + Track A/C 統合口 | `ReviewModePanel.tsx` / `AnalysisModePanel.tsx` / `SettingsModePanel.tsx` | `a835e65` |
| U4 | 下段ストローク履歴ストリップ | `HistoryStrip.tsx` | `b57bcb9` |
| U5 | 動画浮動 overlay toggle | `VideoOverlayToggles.tsx` | `aeaec05` |
| U6 | Ctrl+K コマンドパレット | `CommandPalette.tsx` + 9 コマンド | `a849248` |
| U7 | モバイル変形 (縦積み + BottomSheet 部品) | `BottomSheet.tsx` + flex-col on mobile | `0a3d481` |
| U8 | 設定 Dropdown 階層化 (JMP 風) | `SettingsModePanel.tsx` v2 | (本コミット) |

## アイコン方針

ユーザ要望 (2026-05-04): 絵文字 (🎯⚙ 等) を UI に出さない。Google Material
Symbols (Outlined) を `MIcon` ラッパー経由で使用。`material-symbols` npm
パッケージのローカル woff2 を main.tsx で 1 回 import (CSP / 外部 CDN 不要)。

既存 lucide-react は破壊しない範囲で維持。新規 UI は MIcon を優先採用。

## 不変条件遵守

- `inputStep` 状態機械 (Track A) 不変 — input モードは既存 JSX byte 等価
- HitZoneSelector / CourtDiagram / ShotTypePanel / AttributePanel そのまま再利用
- DB スキーマ変更なし
- Phase A (打点 override / offline stash)、Phase B (セマンティックカラー)、
  Phase C-speed (haptic / semi-auto flip) すべて維持
- routers/yolo.py / candidate_builder.py / cv_aligner.py 等の backend 不変

## Forward-compat hooks

| 統合口 | Track | 表示先 | 現状 |
|---|---|---|---|
| RallyBoundary 候補 | A5 | ReviewModePanel ヘッダ count | 0 件表示 (data なし時 hidden) |
| IdentityGraph mapping | A3 | ReviewModePanel ヘッダ count | 同上 |
| SwingDetector confidence | C3 | ReviewModePanel ヘッダ count | 同上 |
| RTMPose pose overlay | C2 | VideoOverlayToggles `pose` slot | available=false で disabled |

## Validation

- `npm run build` 各フェーズで green (最終 2900 modules, 5.5-9s)
- TypeScript 型チェック OK
- 既存テスト regression なし (Track A/B/C-speed のテストは触らず)
- backend 一切変更なし → backend pytest 影響ゼロ

## 既知の残作業 (フォローアップ任意)

- 入力モードの inputStep 連動表示 (addendum §2): 現状は input モードで
  従来通り全表示。将来 store にトグルを追加して切替可能にできる
- SwingDetector / RTMPose / RallyBoundary の live wiring (Track C-wire 別タスク)
- 上バー xl+ の TrackNet/YOLO バッチ操作 UI も menu に集約 (cosmetic cleanup)
- BottomSheet の右パネル wiring (現状 flex-col のみで mobile は十分)
- i18n 化: 新規 panel の日本語ラベルは hardcoded。`src/i18n/ja.json` 移行は
  CLAUDE.md ルール準拠で別 PR 推奨

## ロールバック

各 Phase 独立にロールバック可能 (commit 単位で revert)。完全ロールバック:

```
git revert 0a3d481 a849248 aeaec05 b57bcb9 a835e65 12339f1 f7eaaff 09c3c8f
```

ロールバック後も DB / 既存 store / inputStep / Track A/B/C 機能は影響なし。
