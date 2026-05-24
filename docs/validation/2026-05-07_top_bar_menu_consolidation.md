# 2026-05-07 AnnotatorPage トップバー統合 + Settings フラット化 + ⌘K 発見性

ユーザ指摘: 「同じ操作が直配置 / TopBarMenu / SettingsModePanel と 3 経路にあって
維持コストが膨らんでいる」「Cmd+K の明示ボタンがあったほうが良いかも」。

これに対し以下 4 フェーズで整理。BPごと (mobile / tablet / PC) の挙動は維持。

## Phase 1: 直接ボタン統合

`AnnotatorPage.tsx` 上バー右側の `hidden xl:flex` 直接ボタンを削除。
TopBarMenu (旧: `hidden md:flex xl:hidden`) を `hidden md:flex` に格上げして
md+ で常時表示。**xl+ でも直接ボタンを廃止し ⋮ メニューに集約**。

### 削除した重複ボタン (xl+ から)
- Annotation mode toggle
- Match day mode toggle
- Dual monitor (open/close + display selector)
- Exception 終了

### 直接配置のまま残したもの (状態表示 / ジョブ系)
- 保存中バッジ / 保存エラー数
- In-match panel toggle (V4-U-001)
- Review queue バッジ
- TrackNet バッチ進捗 (state machine)
- YOLO/CV オーバーレイトグル (state machine)
- CV補助 候補生成・適用ボタン

## Phase 1b: ⌘K 専用ボタン

`CommandPalette.tsx` に `openCommandPalette()` 関数 + `shuttlescope:command-palette-open`
カスタムイベントを追加し、外部から開けるように。

`AnnotatorPage.tsx` の TopBarMenu 隣に明示ボタンを追加:
- md (タブレット): 🔍 + ⌘K kbd ピル (アイコン + ショートカット表示)
- lg+ (PC): 上記 + 「コマンド検索」ラベル
- mobile (<md): 非表示 (mobile はキーボード接続前提でないため)

i18n:
- `annotator.ux.command_button_label` / `command_button_aria` / `command_button_title`

## Phase 2: TopBarMenu 整備

`TopBarMenu.tsx` に `TopBarMenuSection` を追加。見出し + 区切り線 + 子ボタンのグループ化。
AnnotatorPage の TopBarMenu 中身を 4 セクションに整理:

| セクション | 含まれる項目 |
|---|---|
| 記録モード | annotation mode toggle / match day toggle |
| 表示 | dual monitor open/close (displays.length≥2 のとき) |
| CV バッチ | YOLO バッチ / TrackNet バッチ (有効化時) |
| 危険操作 | Exception 終了 |

i18n:
- `annotator.ux.menu_section_record / display / cv / danger`

## Phase 3: SettingsModePanel フラット化

旧版は `category → item → control` の 3 段カスケード Dropdown で 2-click アクセス必須。
試合中の素早い設定変更に向かなかった。

新版 (sectioned list):
- md+ (タブレット/PC): **全 4 セクション常時展開** (1-click アクセス)
- md 未満 (mobile / BottomSheet 内): 最初の「記録モード」セクションのみ展開、
  他はアコーディオン (折り畳み式)
- 各セクションは見出し (icon + title) + 子コントロール

新コンポーネント:
- `Section`: 折り畳み + alwaysOpen 切替対応
- `ToggleControl`: ON/OFF 切替 (旧と互換)
- `SegmentedControl`: 2-3 値の固定選択肢 (旧の "ボタン縦リスト" 代替、横並びで省スペース)

セクション構成:
- 記録モード (試合中モード / 補助記録 / 入力ステップ連動表示)
- 自動切替 (flip mode 3 値)
- コートキャリブレーション
- キーボード legend

依存削除:
- `useMemo` ベースの categories / items 配列 → セクション直書き
- `useState` カテゴリ/アイテム選択 → Section コンポーネントの open 状態のみ
- 旧 DropdownRow 定義削除

## Phase 4: CommandPalette 発見性

検索バーヘッダーのヒントを `Esc` 1 個から `↑↓ / Enter / Esc` の 3 個に拡充。
キーボード操作の発見性を向上。

## ブレークポイント別の最終 UI

| BP | サイドバー | TopBarMenu ⋮ | ⌘K ボタン | 直接ボタン (xl+) | SettingsModePanel |
|---|---|---|---|---|---|
| < md (mobile) | hidden (BottomSheet) | hidden | hidden (⌘K shortcutless) | n/a | アコーディオン |
| md (tablet) | w-16 アイコン | ✅ 表示 | 🔍 + ⌘K (ラベル無) | n/a | 全展開 |
| lg (iPad横) | w-56 ラベル付 | ✅ 表示 | 🔍 + 「コマンド検索」 + ⌘K | n/a | 全展開 |
| xl+ (PC) | w-56 ラベル付 | ✅ 表示 | 🔍 + 「コマンド検索」 + ⌘K | **削除済** | 全展開 |

## 検証

### 追加した frontend テスト
- `src/components/annotator/__tests__/TopBarMenu.test.tsx` (6 ケース)
  - 初期状態 / 開閉 / Esc / Section title / firstSection の上区切り線挙動
- `src/components/annotator/__tests__/CommandPalette.test.tsx` (9 ケース)
  - Ctrl+K / Cmd+K で開く
  - **`openCommandPalette()` 関数で外部から開ける** ⌘K ボタンとの連携
  - Esc で閉じる
  - 検索フィルタ
  - ↑↓ Enter で実行
  - disabled コマンドは実行されない
  - ヘッダーに ↑↓ / Enter / Esc 表記

### 全テスト結果
- vitest: **17 ファイル / 159 tests PASS** (+15 新規)
- electron-vite build: ✅
- npm audit: 0 vulnerabilities

## 影響

- DB スキーマ変更: なし
- バックエンド変更: なし
- 既存ルート / ページ挙動: 変更なし (上バー UI のみ整理)
- 既存ユーザの操作経路: 全て CommandPalette + TopBarMenu + SettingsModePanel に維持
- xl+ で「いつもの直接ボタン」が消える点が唯一の体感的変化 → ⌘K ボタン + ⋮ で補えている

## 残スコープ

- TopBarMenu ボタンへのキーボードショートカット表示 (e.g. `M` でモード切替) は将来検討
- SettingsModePanel でセクション順をユーザがドラッグ並べ替えする機能は不要 (固定で十分)
- CommandPalette の最近使ったコマンド優先表示は次サイクル
