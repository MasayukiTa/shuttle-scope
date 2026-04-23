# Coverage C2: db_maintenance router (2026-04-23)

## 背景
C1 baseline (52% overall / routers 36%) で `backend/routers/db_maintenance.py` は 50% だった。小さい router (24 stmts) かつテスト未整備のため最初の対象に選定。

## 追加テスト
`backend/tests/test_db_maintenance.py` (8 ケース)

| クラス | テスト | 観点 |
|--------|--------|------|
| TestDbStatus | test_status_returns_200 | GET /api/db/status 200 |
| TestDbStatus | test_status_has_expected_fields | page_count / freelist_count / auto_vacuum キー |
| TestDbMaintenance | test_maintenance_returns_200 | POST /api/db/maintenance 200 |
| TestDbMaintenance | test_maintenance_returns_before_after | dict レスポンス |
| TestSetAutoVacuum | test_invalid_mode_returns_400 | mode="bogus" → 400 (happy error) |
| TestSetAutoVacuum | test_missing_mode_returns_422 | body なし → 422 (validation) |
| TestSetAutoVacuum | test_valid_mode_off_returns_200_or_400 | 有効 mode 受理 |
| TestSetAutoVacuum | test_error_keys_stripped_from_response | error/exception/traceback 非露出（stack-trace 対策の回帰） |

## 検証
- `pytest backend/tests/test_db_maintenance.py -v` → 8 passed (3.55s)
- 既存 635 件も影響なし (import 時に conftest 共用のみ)

## 次
C3: 次の低 coverage router を選定（候補: `prediction.py` 12% / `reports.py` 11% / `yolo_realtime.py` 0% / `cluster.py` 15%）
