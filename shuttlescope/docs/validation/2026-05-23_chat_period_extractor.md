# 2026-05-23 — Advice Chat Period Extractor (rule-based)

## 目的
Growth Advisor チャット入力欄で自然文 (例: `25/03から今まで`, `先月の`, `直近3ヶ月で`)
から非 LLM ルールベースで日付範囲を抽出し、確認チップを出して送信時にメッセージへ
添付。サーバ側で `build_player_summary(db, player_id, date_from, date_to, None)` の
スコープに利用する。

## 変更ファイル

### 新規
- `shuttlescope/src/utils/parsePeriod.ts` — ピュアな日本語/英語期間パーサ
  (依存ゼロ、`now` 引数化、`confidence ∈ {exact, heuristic, none}`)
- `shuttlescope/src/utils/__tests__/parsePeriod.test.ts` — Vitest 32 ケース
- `shuttlescope/backend/db/migrations/versions/0036_chat_message_period.py`
  — `chat_messages.date_from / date_to (VARCHAR(10) NULL)`
- `shuttlescope/backend/tests/test_chat_period.py` — pytest 5 ケース

### 変更
- `shuttlescope/src/components/dashboard/advice_chat/ChatComposer.tsx`
  — debounced (150ms) parse → period chip + edit popover + clear ボタン。
  `onSend(period | null)` シグネチャ拡張
- `shuttlescope/src/components/dashboard/advice_chat/AdviceChatPanel.tsx`
  — `handleSend(period)` に変更し sendMessage へ転送
- `shuttlescope/src/components/dashboard/advice_chat/useAdviceChat.ts`
  — `sendMessage(text, period?)` でリクエスト body に `date_from / date_to`
  を含める。`ChatMessage` 型に `date_from / date_to` 追加
- `shuttlescope/src/components/dashboard/advice_chat/ChatMessageBubble.tsx`
  — ユーザバブルの下に `📅 from → to` ピル
- `shuttlescope/src/i18n/ja.json`, `en.json`
  — `auto.AdviceChat.period.*` キー追加 (chipLabel/estimated/edit/clear/popover\*)
- `shuttlescope/backend/routers/insights_chat.py`
  — `_SendMessageBody` に `date_from / date_to: Optional[str]` + ISO YYYY-MM-DD
  validator。`_build_analytics_context` に転送し `build_player_summary` 第3/4引数へ
  渡す。`_serialize_message` も期間フィールドを含める
- `shuttlescope/backend/db/models.py` — `ChatMessage.date_from / date_to`
- `shuttlescope/src/styles/material-symbols-subset.css` /
  `src/assets/fonts/material-symbols-subset.woff2`
  — `event` / `edit` / `close` 追加分の自動再サブセット結果

## 認識パターン (parsePeriod)
優先順位:
1. 絶対範囲: `YYYY/M/D 〜 YYYY/M/D`, ISO 形式, `to / – / -` コネクタ
2. open-end: `YYYY/M/D から今まで`, `... から現在まで`, `since YYYY-MM`
3. 相対 duration: `直近N(日|週|ヶ月|か月|カ月|月|年)`, `過去N...`, `この/ここN...`,
   英語 `past/last N days|weeks|months|years`
4. 相対 keyword: `今日 / 昨日 / 今週 / 先週 / 今月 / 先月 / 今年 / 去年`
   と英語版 (`today / yesterday / this|last week|month|year`)
5. 単一絶対: `2025年3月`, `25/03`, `M月D日` (年なしは過去 12 ヶ月へ倒す)

2 桁年補正: `YY ≤ curYY+1 → 20YY`, else `19YY`。
ambiguous "3/1" (年なし) は未来側を 1 年戻す。

## 実機で確認したパーサ出力 (now = 2026-05-23 月曜想定)
- `"25/03から今まで"` → 2025-03-01 〜 2026-05-23 (exact)
- `"先月の"` → 2026-04-01 〜 2026-04-30 (exact)
- `"直近3ヶ月で"` → 2026-02-24 〜 2026-05-23 (exact)
- `"past 30 days"` → 2026-04-24 〜 2026-05-23 (exact)
- `"since 2025-03"` (en) → 2025-03-01 〜 2026-05-23 (exact)
- `"2024年2月"` → 2024-02-01 〜 2024-02-29 (閏年)
- `"2025/12/1から今まで"` → 2025-12-01 〜 2026-05-23 (年またぎ)
- `"スマッシュの伸びしろを教えて"` → none

## テスト結果
- vitest: `npm run test -- parsePeriod` → **32 passed**
- pytest: `python -m pytest backend/tests/test_chat_period.py -q`
  → **5 passed** (`accepts_period`, `persisted_on_chat_message_row`,
  `omitted_is_null`, `invalid_iso_date_rejected`, `passed_to_player_summary`)
- lint (`npm run lint -- <touched files>`) → **0 errors** (周辺の既存 warning 多数, 本変更で増加 3 件は parsePeriod の variable-init style warning)

## トリッキー判断 / 妥協ポイント

- `confidence` は仕様上 `exact / heuristic / none` の 3 値だが、当面実装は
  `exact` か `none` のみ返す。`heuristic` 用のヒューリスティック (例: 数字単独
  "3" だけのケース) は false positive リスクが高いので punt した。バッジ色だけは
  `heuristic` も yellow で予約済み。
- 週始まりは月曜 (JIS / 業務週)。日曜始まりに切り替えたい場合は `startOfWeek()`
  の `diff` 計算を 1 行修正。
- 2 桁年 cutoff は `curYY+1`。再来年 (今は 2027) までを 20YY 扱いにする緩い境界。
  実用上 `99/03` のような 90 年代記法とぶつかる確率は低い。
- 直近 N ヶ月の `from` は `addMonths(today, -n) + 1day`。仕様の "ending today" を
  踏み厳密に `today` を含む N ヶ月幅としている (UNIX cutoff 流の半開区間ではない)。
- マイグレーション 0036 は `add_column` ベースで冪等 (既存カラム検査)。SQLite
  デフォルト NULL で破壊なし。`Base.metadata.create_all` パスでもモデル側に
  `date_from / date_to` を生やしたので新規 DB は alembic なしで列が立つ。

## 既知の落とし穴
- conftest が `db_module.engine / SessionLocal` を session-scope で in-memory に
  swap している。テストから DB を覗くときは `from backend.db.database import engine`
  ではなく `from backend.db import database as _db_module` 経由で
  `_db_module.engine / SessionLocal` を使う必要がある (本テストはこのパターンを
  採用済)。
