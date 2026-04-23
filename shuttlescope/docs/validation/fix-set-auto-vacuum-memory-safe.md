# Fix: `set_auto_vacuum_mode` in-memory DB safeguard

Date: 2026-04-23

## 問題

`test(C2): add db_maintenance router unit tests` 以降 CI が大量失敗 (30 failed, 103 errors)。
症状は `sqlite3.OperationalError: no such table: players` / `no such table: shared_sessions` 等、
特定テスト以降の全テストでテーブル消失。

## 原因

`backend/db/database.py::set_auto_vacuum_mode()` がインメモリ DB (`:memory:`) でも実行され、
内部で `bind.dispose()` を呼び出してしまうため、共有 StaticPool の単一コネクションが破棄され、
`Base.metadata.create_all(engine)` で作成した全テーブルが消失する。

具体的には `test_db_maintenance.py::test_error_keys_stripped_from_response` が
`POST /api/db/set_auto_vacuum {mode:"incremental"}` を送り、共有 in-memory test_engine を破壊していた。

## 修正

`set_auto_vacuum_mode()` に `:memory:` ガードを追加し、インメモリ URL の場合は no-op で
`{"supported": False, "message": "in-memory DB は対象外"}` を返すようにした。

## 検証

- `DATABASE_URL=sqlite:///:memory: pytest` の結果が
  - Before: 30 failed, 537 passed, 103 errors
  - After:  16 failed, 654 passed, 0 errors
- 残り 16 件は既存の test pollution 問題 (auth/settings router の TestClient lifespan 順序依存) で
  本修正とは別課題。C2 commit 導入前から存在していた可能性が高い (CI はそれ以前から auth 系テスト
  commit で failure だった)。
- `test_db_maintenance.py` 単体は全 8 ケース PASS。

## 影響範囲

- インメモリ DB (テスト環境) のみで挙動変化。ファイル DB の本番/開発環境では従来通り動作。
