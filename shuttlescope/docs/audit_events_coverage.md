# データ変更監査 (audit_events) — 現状調査と設計根拠

対象: ShuttleScope backend。固定条件(1)(2)に対応する成果物。
実測基準日: 2026-11-06（本番 request_logs の実測例: user 183 が PUT /api/matches/400）。

## 背景

認証済みユーザーの書き込みは `request_logs` に `user_id` / `method` / `path` / `status` が残る。
しかし「どのフィールドが、どの値から、どの値に変わったか」は残らない。
さらに、変更内容の追跡用に各ルーターへ個別に `access_log.log_access` を足す方式は、
書き漏れが構造的に避けられない（下表の「request_logs 以外」列が空＝未記録の行が多数）。

## (1) 変更系ルーター一覧と「request_logs 以外に何を残すか」

mount prefix: matches/sets/rallies/strokes/players/settings は `main.py` が `/api` を付与。
conditions は router 側 `prefix="/api/conditions"`。auth は `/api` + router 側 `/auth`。

「access_log」= `backend/utils/access_log.py` の `log_access`（AccessLog テーブル。action 文字列と
任意の details を残すが、変更前後の値・フィールド差分は残さない）。

| エンティティ | メソッド・実パス | request_logs 以外の既存記録 | 新 audit_events 対象 |
|---|---|---|---|
| match | POST /api/matches | なし | ○ |
| match | PUT /api/matches/{id} | access_log `match_updated` | ○ |
| match | DELETE /api/matches/{id} | access_log `match_deleted` / `match_video_cascade_deleted` | ○ |
| match | POST /api/matches/quick-start | なし | ○ |
| match | POST /api/matches/{id}/regenerate_variants | なし | ○ |
| match | POST /api/matches/{id}/download | access_log `video_dl_started` | ○ |
| set | POST /api/sets | なし | ○ |
| set | PUT /api/sets/{id}/end | なし | ○ |
| rally | POST /api/rallies | なし | ○ |
| rally | PUT /api/rallies/{id} | なし | ○ |
| rally | DELETE /api/rallies/{id} | なし | ○ |
| rally | POST /api/annotation/{match_id}/undo | なし | ○ |
| stroke | POST /api/strokes/batch | なし | ○ |
| stroke | POST /api/strokes | なし | ○ |
| stroke | PUT /api/strokes/{id} | なし | ○ |
| stroke | DELETE /api/strokes/{id} | なし | ○ |
| player | POST /api/players | なし | ○ |
| player | PUT /api/players/{id} | なし（cross-team scope 違反時のみ access_log） | ○ |
| player | DELETE /api/players/{id} | なし | ○ |
| settings | PUT /api/settings | なし | ○ |
| user | POST /api/auth/users | access_log `user_created` | ○ |
| user | PUT /api/auth/users/{id} | access_log（複数 action） | ○ |
| user | POST /api/auth/users/{id}/unlock | access_log `account_unlocked` | ○ |
| user | DELETE /api/auth/users/{id} | access_log `user_deleted` | ○ |
| user | POST /api/auth/users/{id}/reset-password | access_log `password_reset_by_admin` | ○ |
| condition | POST /api/conditions | access_log（一部） | ○ |
| condition | POST /api/conditions/questionnaire | なし | ○ |
| condition | PATCH /api/conditions/{id} | なし | ○ |
| condition | DELETE /api/conditions/{id} | access_log `condition_deleted` | ○ |
| condition_tag | POST /api/condition_tags | なし | ○ |
| condition_tag | PUT /api/condition_tags/{id} | なし | ○ |
| condition_tag | DELETE /api/condition_tags/{id} | なし | ○ |
| team | POST /api/auth/teams | access_log（一部） | ○ |
| team | PATCH /api/auth/teams/{id} | access_log（一部） | ○ |
| team | DELETE /api/auth/teams/{id} | access_log（一部） | ○ |

観察: match と user 系の一部を除き、変更内容に関する既存記録は無いか action 名のみ。
sets / rallies / strokes / settings / conditions / condition_tags は変更系なのに request_logs
以外ゼロの経路が多い。横断フックで担保する。

選手コンディション（conditions / condition_tags）は「選手」に紐づく測定・タグであり、
固定条件(1)の「選手」系の変更台帳に含める。チーム（auth /teams）は「ユーザー・設定」系の
組織マスタ変更として監査対象に含める。これらが `_PATTERNS` から漏れると classify_path=None に
なるため、網羅テスト `TestEveryWriteRouteIsClassified` が実ルート走査で検知して落ちる。

### スコープ外（意図的に未対象）

- **auth のログイン/MFA/トークン系**（login, mfa/*, logout, refresh, password, consents/*）:
  エンティティの作成・更新・削除ではなく認証イベント。既存 access_log が担当。
  （teams の CRUD は上表のとおり監査対象に含める。page-access 設定も team に紐付いて拾われる。）

## (2) 値を保存しない理由と測定

保存するのは **フィールド名・件数・ハッシュ** まで（`summarize_body`）。生値は保存しない。

- **個人情報**: players の表示名、conditions の問診回答など個人データを含むため、
  監査テーブルへの平文複製は最小化する（二次流出面を増やさない）。
- **大容量**: strokes batch は実測最大 ~180KB の JSON、video 系は multipart 動画。
  変更前後の値を全保存するとテーブルが肥大化する。body 読み取りは 512KB で打ち切り
  （`_AUDIT_BODY_MAX_BYTES`）、超過時はハッシュも取らず行だけ残す。
- **残すもの**: `changed_fields`（body のキー名＝列名候補）/ `field_count` / `body_hash`(SHA-256)。
  値は復元できないが、同一 body の照合・改竄検知の指紋として機能する。

## (3) 実装

横断フック（`AuditEventMiddleware`、最外ミドルウェア）で、POST/PUT/PATCH/DELETE が
成功（2xx）したときに `audit_events` に 1 行書く。主体は `request.state.user_id`、無い場合は
検証済み Bearer トークンの `sub` からのみ解決。監査書き込みは別 DB セッションで行い、
失敗しても元レスポンスを壊さない（失敗は logger.warning のみ）。

単一定義: `backend/utils/audit_targets.py`（middleware とテストが共有）。
