# Fix: test pollution from `backend.config.settings` singleton replacement

Date: 2026-04-23

## 問題

in-memory DB 対応 (`fix-set-auto-vacuum-memory-safe.md`) 後も full pytest で 16 件失敗。
症状は主に `POST /api/auth/login → 401 "login failed"` と
`PUT /api/settings → 500 no such table: app_settings`。
個別実行 (`pytest backend/tests/test_refresh_token.py`) では pass するが
full suite 順序依存で失敗する典型的な pollution。

## 根本原因

2 種類の pollution 源があった。

### 1. `backend/routers/settings.py` の import 時 engine キャプチャ

`from backend.db.database import engine` と module import 時の
`create_settings_table()` 呼び出しにより、`conftest.py::test_engine` fixture が
`db_module.engine` を patch する前の engine に `app_settings` テーブルを作成していた。
結果、test 用 in-memory engine には `app_settings` が存在せず `/api/settings` が 500。

### 2. `backend.config.settings` の instance 差し替え

`backend/benchmark/runner.py` と `backend/tests/test_benchmark_runner.py` が
`cfg_mod.settings = cfg_mod.Settings()` で **instance ごと差し替え** ており、
すでに `from backend.config import settings` で参照をキャプチャしていた
他モジュール (`backend/routers/auth.py`, `backend/routers/network_diag.py` 等) は
古い instance を保持し続けた。
結果、`test_refresh_token` fixture が `settings.BOOTSTRAP_ADMIN_PASSWORD = "..."`
を設定しても `auth._seed_admin_if_needed` は古い settings (空文字列) を参照して
admin を seed せず、login が失敗。

## 修正

- `backend/routers/settings.py`: import 時の `engine` キャプチャを削除し、
  各リクエストで `_ensure_settings_table(db)` を呼んで冪等に CREATE。
- `backend/routers/network_diag.py`: `from backend.config import settings` を
  `from backend import config as _config_module` に変え、関数内で
  `_get_settings()` で動的に最新 attribute を取得するよう変更。
- `backend/benchmark/runner.py`: `cfg_mod.settings = cfg_mod.Settings()` を
  **in-place attribute 更新** に変更（instance 参照を壊さない）。
- `backend/tests/test_benchmark_runner.py` の `mock_env` fixture も同様に in-place 化。
- `backend/tests/test_cv_factory.py::_reload_settings`: `importlib.reload(backend.config)`
  をやめ、既存 singleton の属性を `monkeypatch.setattr` で更新するよう修正。
- `backend/main.py` lifespan: `bootstrap_database(engine, ...)` を `bootstrap_database(None, ...)`
  に変更し、db_module 側で engine を動的解決。

## 検証

- `DATABASE_URL=sqlite:///:memory: pytest backend/tests/` の結果が
  - Before (this fix series 開始時): 30 failed, 537 passed, 103 errors
  - After auto_vacuum fix: 16 failed, 654 passed, 0 errors
  - **After: 0 failed, 670 passed, 4 skipped**

## 影響範囲

- テスト環境のみの修正が中心。PostgreSQL / ファイル SQLite 本番環境は従来通り。
- `backend/benchmark/runner.py` の in-place 更新化は本番動作でも副作用なし
  (pydantic settings の属性更新のみで、Settings() 再生成の動作と等価)。
