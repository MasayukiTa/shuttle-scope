# 設計ノート: players.height_cm（ペアデータ蓄積の準備）

作成日: 2026-11-14
対象タスク: PAIR-DATA-ACCUMULATION
ステータス: データ捕捉のみ実装（解析は未実装・意図的に先送り）

## 目的

ダブルスのペアは安定した「個性」を持ち、対戦相手ごとの変化は基準との差分として読み取れる、という仮説に向けて、将来の「ペア × 対オポーネント」解析で使う可能性のある選手の基本属性を、解析を作る前から蓄積しておく。本ノートはそのうち身長 `players.height_cm`（任意・nullable）を追加した意図と、将来解析が参照するフィールドの見取り図、および運用上オーナーへ確認すべき点を記録する。

本ノートは設計意図のみを記す。組織名・個人名・実データ・解析結果は一切含めない。

## 追加したもの

- `players.height_cm`: nullable Integer。既存行は NULL（未入力扱い）。API 入力時に 100〜250 の範囲で検証。
- 体組成（`Condition.weight_kg` 等、別ティア）とは別系統の「選手プロフィール基本属性」として team スコープ内でのみ扱う。
- public / shared / export の各サーフェスには出さない（allow-list 方式）。

## 将来の「ペア × 対オポーネント」解析が参照するフィールド

解析は本 PR では作らない。将来解析が読む想定のフィールドを、現行スキーマ上の所在（file:line）とともに列挙する。

### ペアの同定

- `Match.partner_a_id` / `Match.partner_b_id` — ダブルスのペア構成選手。`backend/db/models.py:406-407`
- `Match.format`（singles / womens_doubles / mixed_doubles）— ダブルス判定。`backend/db/models.py:403`
- `Match.player_a_start_side` 等の開始サイド情報。`backend/db/models.py:436`

### 選手ごとの属性（本タスクで追加）

- `players.height_cm` — 身長（任意）。`backend/db/models.py:348`
- 既存の選手属性（`nationality` / `birth_year` 等）と同じ team スコープの基本属性として扱う。

### ストローク単位（per-stroke）の帰属とクエリ

- `Stroke.player`（player_a / player_b / partner_a / partner_b）— ストロークの打者サイド。`backend/db/models.py:603`
- per-stroke クエリ用インデックス（player / shot_type / hit_zone / land_zone）。`backend/db/models.py:572-576`
- `Stroke` → `Rally` → `GameSet` の連鎖（ラリー単位・セット単位の集計の土台）。`backend/db/models.py:566`, `:601-602`
- ラリー属性（`rally_num` / `rally_length` 等）。`backend/db/models.py:544`, `:548`

### 差分（対オポーネント変化）を読むための軸

- ペア（partner_a_id, partner_b_id）を単位に、対戦相手（相手側のペアまたは選手）ごとに per-stroke 分布（shot_type / hit_zone / land_zone）を集計し、そのペアの全体傾向（基準）との差分を取る、という構成を将来実装で想定する。身長はこの差分の説明変数候補として `players.height_cm` を join して参照する。

## オーナーへの確認事項（質問）

解析を実装・報告する前に、以下をオーナーに確認したい。

1. **報告前に必要な最小試合数**: ペア × 対オポーネントの差分を「読める」と見なして報告に載せてよい最小試合数は何試合か。ペア単位の下限、かつ特定オポーネント対戦の下限（例: 同一オポーネントと最低何試合か）をそれぞれ指定してほしい。これを満たさないペア/対戦は「サンプル不足」として差分報告の対象外にする方針でよいか。
2. **身長の入力方針**: `height_cm` は任意入力のまま運用し、未入力（NULL）の選手は身長を説明変数に使う解析から除外する扱いでよいか。
3. **解析単位**: ペアの同定は `(partner_a_id, partner_b_id)` の順不同の組で扱ってよいか（左右・サイドは別途 start_side で保持）。

上記 1 の最小試合数が未確定の間は、差分解析の実装・報告は行わず、本タスクはデータ捕捉（身長列の追加）に留める。
