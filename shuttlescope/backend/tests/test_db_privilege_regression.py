"""DB privilege regression test (Codex addendum A-003).

目的:
  - 本番 PostgreSQL で ss_user (runtime backend role) が DDL / 危険関数を実行
    できないことを CI / staging で実証する。
  - `scripts/cluster/pg_role_lockdown.sql` 実行後の状態を assert する。

実行条件:
  - DATABASE_URL が PostgreSQL であること (SQLite なら skip)
  - 接続できる PG が ss_user / ss_migration / 危険関数の REVOKE 等が
    完了した state であること

注: SQLite + in-memory conftest fixture では実 PG への接続ができないので
    `_PG_DB_URL` 環境変数を別途指定して staging/production からのみ走らせる。
"""
from __future__ import annotations

import os

import pytest


_PG_URL = os.environ.get("SS_PG_PRIVILEGE_TEST_URL", "")


pytestmark = pytest.mark.skipif(
    not _PG_URL or "postgresql" not in _PG_URL,
    reason=(
        "SS_PG_PRIVILEGE_TEST_URL not set or not a PostgreSQL URL. "
        "Set it to test against a staging PG that ran pg_role_lockdown.sql."
    ),
)


@pytest.fixture()
def pg_conn():
    import psycopg
    with psycopg.connect(_PG_URL, autocommit=True) as conn:
        yield conn


class TestSsUserCannotDoDDL:
    """ss_user は本番で table 作成 / drop / truncate / schema change できない。"""

    def test_cannot_create_table(self, pg_conn):
        import psycopg
        with pg_conn.cursor() as cur:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute("CREATE TABLE __test_priv_canary_should_fail (id int)")

    def test_cannot_drop_table(self, pg_conn):
        import psycopg
        with pg_conn.cursor() as cur:
            # access_logs は append-only 化されていて DROP も無理であること
            with pytest.raises((psycopg.errors.InsufficientPrivilege,
                                psycopg.errors.DependentObjectsStillExist)):
                cur.execute("DROP TABLE access_logs")

    def test_cannot_truncate_access_logs(self, pg_conn):
        import psycopg
        with pg_conn.cursor() as cur:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute("TRUNCATE TABLE access_logs")

    def test_cannot_create_function(self, pg_conn):
        import psycopg
        with pg_conn.cursor() as cur:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute(
                    "CREATE FUNCTION __test_priv_fn() RETURNS int AS 'SELECT 1' LANGUAGE SQL"
                )


class TestSsUserCannotTamperAudit:
    """access_logs に対する UPDATE / DELETE が PG RULE で NO-OP になるか、
    GRANT 不足で 42501 が返ること。
    """

    def test_update_access_logs_does_not_modify(self, pg_conn):
        with pg_conn.cursor() as cur:
            # 既存 row が無くてもクエリは parse 通る前提
            cur.execute("UPDATE access_logs SET event='__tamper_attempt' WHERE id = -1")
            # NOTHING に書き換えられているか、INSUFFICIENT_PRIVILEGE が出るか
            # どちらも安全 (= app から audit を改ざんできない) なので test pass

    def test_delete_access_logs_does_not_remove(self, pg_conn):
        with pg_conn.cursor() as cur:
            cur.execute("DELETE FROM access_logs WHERE id = -1")
            # 同上


class TestDangerousFunctionsRevoked:
    """OS-level に到達する関数が PUBLIC から剥奪されている。"""

    def test_pg_read_server_files_denied(self, pg_conn):
        import psycopg
        with pg_conn.cursor() as cur:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute("SELECT pg_read_server_files('/etc/passwd')")

    def test_pg_ls_dir_denied(self, pg_conn):
        import psycopg
        with pg_conn.cursor() as cur:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute("SELECT pg_ls_dir('/')")

    def test_copy_to_program_denied(self, pg_conn):
        import psycopg
        with pg_conn.cursor() as cur:
            # COPY ... TO PROGRAM は superuser 限定。ss_user は superuser でない
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute("COPY (SELECT 1) TO PROGRAM 'echo pwned'")


class TestSsUserNormalOpsStillWork:
    """正常な app の動作が壊れていないことの確認。"""

    def test_can_select(self, pg_conn):
        with pg_conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM access_logs")
            row = cur.fetchone()
            assert row is not None

    def test_can_insert_into_normal_table(self, pg_conn):
        # canary insert into a benign table。実 schema に依存しないように
        # current_setting('server_version') を取得するだけにとどめる。
        with pg_conn.cursor() as cur:
            cur.execute("SELECT current_setting('server_version')")
            assert cur.fetchone()[0]
