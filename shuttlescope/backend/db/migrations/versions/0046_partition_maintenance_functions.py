"""request_logs / product_events の月次パーティション自動維持関数を追加。

背景 (障害):
  0032 (request_logs) と 0031 (product_events) は「migration 実行時点の当月 +
  翌月」パーティションを 1 回だけ作る DO ブロックを持つが、それ以降パーティ
  ションを追加する仕組みが存在しなかった。0031 は `backend/utils/telemetry.py`
  の `ensure_next_partition()` で追加を試みていたが、この関数はどこからも
  呼ばれておらず (grep で呼び出し元 0 件)、かつ R47 (pg_role_lockdown) 後は
  ss_user セッション経由では CREATE 権限が無く `insufficient_privilege` で
  黙って no-op するだけの死んだコードだった。
  結果、2026-07 分のパーティションが一度も作られず、7/1 以降 request_logs
  への INSERT が (親テーブルにその月をカバーする子パーティションが存在しない
  ため) 全て失敗し、監査ログが 24 日間死んでいた。さらに運用者が肥大化した
  2026_05 / 2026_06 パーティションを DROP した結果、現時点で request_logs は
  パーティション 0 件 = 当月分すら書き込めない状態。

このマイグレーションが行うこと:
  1. `ensure_request_logs_partitions(months_ahead int DEFAULT 1)` を作成。
     当月 + 今後 months_ahead ヶ月分のパーティションを IF NOT EXISTS で作る
     冪等関数。実行後すぐ 1 回 CALL して当月分を復旧する。
  2. 同様に `ensure_product_events_partitions(months_ahead int DEFAULT 1)` を
     作成 (product_events も同じ「作って終わり」パターンで、既存の
     telemetry.ensure_next_partition() は上記の理由で機能していなかった)。
     こちらも作成後すぐ 1 回 CALL する。
  3. security_events (0032) は RANGE PARTITION BY を持たない plain table な
     ので対象外 (パーティション自体が存在しないため維持する対象がない)。

インデックスについて:
  新しいパーティションに ip_addr/ts, path/ts, status/ts, ts, user_id/ts,
  request_id, source/ts の各インデックスを個別に CREATE INDEX する必要は
  ない。PostgreSQL の宣言的パーティショニングでは、親 (パーティション化)
  テーブルに対して作られたインデックスは「パーティション化インデックス」
  となり、それ以降に作成/ATTACH される子パーティションには自動的に同じ
  定義のインデックスが付与される (PG 11+ の仕様。0032 / 0034 は各インデッ
  クスを request_logs という親テーブルに対して CREATE INDEX しているため、
  これらは全てパーティション化インデックスである)。ここで個別に
  CREATE INDEX を追加すると、自動付与されたインデックスとは別名の重複イン
  デックスが生えて容量を無駄にするだけなので、あえて作らない。
  代わりに CALL 直後に実インデックス数を検証し、想定より少なければ
  RAISE WARNING で気づけるようにする。

権限モデル:
  両関数は SECURITY DEFINER + `OWNER TO ss_migration` にする。理由:
    - 主経路 (Scheduled Task = backend/tools/ensure_partitions.py) は
      SS_DB_MIGRATION_URL (ss_migration ロール) で直接呼ぶので DEFINER は
      本来無くても動く。
    - ただし telemetry.ensure_next_partition() のように、将来アプリ内
      (ss_user セッション) から self-heal 目的で呼びたくなるケースに備え、
      SECURITY DEFINER にしておけば ss_user から EXECUTE しても
      ss_migration 権限で実行される。そのため GRANT EXECUTE を ss_user にも
      与えておく (関数の中身は「自分のテーブルのパーティションを作る」だけ
      に限定されているため権限昇格リスクは小さい)。
    - SECURITY DEFINER 関数の定石通り `SET search_path = public` を明示し、
      search_path 経由のなりすまし関数呼び出しを防ぐ。

Revision ID: 0046
Revises: 0045
"""
from alembic import op
import sqlalchemy as sa


revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


def _is_postgres() -> bool:
    bind = op.get_bind()
    return bind.dialect.name == "postgresql"


def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return name in insp.get_table_names()


# --- request_logs -----------------------------------------------------------
_REQUEST_LOGS_FUNC = """
CREATE OR REPLACE FUNCTION ensure_request_logs_partitions(months_ahead int DEFAULT 1)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $func$
DECLARE
  i     int;
  base  DATE := date_trunc('month', now())::date;
  d0    DATE;
  d1    DATE;
  pname TEXT;
BEGIN
  IF months_ahead IS NULL OR months_ahead < 0 THEN
    months_ahead := 1;
  END IF;
  -- i=0 が当月、i=1..months_ahead が先行分。0032 の「当月+翌月」を再現しつつ
  -- 前倒しで複数月分バンクできるようにする (日次タスクが多少遅延しても
  -- ギャップが生まれない安全マージン)。
  FOR i IN 0..months_ahead LOOP
    d0 := (base + (i || ' months')::interval)::date;
    d1 := (base + ((i + 1) || ' months')::interval)::date;
    pname := 'request_logs_' || to_char(d0, 'YYYY_MM');
    EXECUTE format(
      'CREATE TABLE IF NOT EXISTS %I PARTITION OF request_logs FOR VALUES FROM (%L) TO (%L)',
      pname, d0, d1
    );
    -- 親テーブルの権限は親経由アクセスなら自動適用されるが、直接パーティ
    -- ション名を参照するツール/クエリがあっても書き込めるよう明示 GRANT
    -- しておく (telemetry.ensure_next_partition() の既存慣習に合わせる)。
    EXECUTE format('GRANT SELECT, INSERT ON %I TO ss_user', pname);

    -- インデックスは親のパーティション化インデックスから自動付与される
    -- 想定。念のため検証し、想定数 (親の非プライマリキー実インデックス数)
    -- を下回っていたら気づけるように警告する。
    IF (
      SELECT count(*) FROM pg_indexes WHERE schemaname = 'public' AND tablename = pname
    ) < (
      SELECT count(*) FROM pg_indexes WHERE schemaname = 'public' AND tablename = 'request_logs'
    ) THEN
      RAISE WARNING 'ensure_request_logs_partitions: % has fewer indexes than parent (auto-inherit may have failed)', pname;
    END IF;
  END LOOP;
END;
$func$;

ALTER FUNCTION ensure_request_logs_partitions(int) OWNER TO ss_migration;
GRANT EXECUTE ON FUNCTION ensure_request_logs_partitions(int) TO ss_user;
"""

_REQUEST_LOGS_FUNC_DROP = "DROP FUNCTION IF EXISTS ensure_request_logs_partitions(int);"


# --- product_events ----------------------------------------------------------
_PRODUCT_EVENTS_FUNC = """
CREATE OR REPLACE FUNCTION ensure_product_events_partitions(months_ahead int DEFAULT 1)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $func$
DECLARE
  i     int;
  base  DATE := date_trunc('month', now())::date;
  d0    DATE;
  d1    DATE;
  pname TEXT;
BEGIN
  IF months_ahead IS NULL OR months_ahead < 0 THEN
    months_ahead := 1;
  END IF;
  FOR i IN 0..months_ahead LOOP
    d0 := (base + (i || ' months')::interval)::date;
    d1 := (base + ((i + 1) || ' months')::interval)::date;
    pname := 'product_events_' || to_char(d0, 'YYYY_MM');
    EXECUTE format(
      'CREATE TABLE IF NOT EXISTS %I PARTITION OF product_events FOR VALUES FROM (%L) TO (%L)',
      pname, d0, d1
    );
    EXECUTE format('GRANT SELECT, INSERT ON %I TO ss_user', pname);

    IF (
      SELECT count(*) FROM pg_indexes WHERE schemaname = 'public' AND tablename = pname
    ) < (
      SELECT count(*) FROM pg_indexes WHERE schemaname = 'public' AND tablename = 'product_events'
    ) THEN
      RAISE WARNING 'ensure_product_events_partitions: % has fewer indexes than parent (auto-inherit may have failed)', pname;
    END IF;
  END LOOP;
END;
$func$;

ALTER FUNCTION ensure_product_events_partitions(int) OWNER TO ss_migration;
GRANT EXECUTE ON FUNCTION ensure_product_events_partitions(int) TO ss_user;
"""

_PRODUCT_EVENTS_FUNC_DROP = "DROP FUNCTION IF EXISTS ensure_product_events_partitions(int);"


def upgrade() -> None:
    if not _is_postgres():
        # SQLite (dev/test) はパーティショニング自体を使わない plain table
        # なので、この migration は PostgreSQL 専用として丸ごとスキップする
        # (0032 / 0031 と同じガード方針)。
        return

    # request_logs: 関数作成 → 直ちに 1 回 CALL して当月+翌月分を復旧。
    # これが本 migration の主目的 (現在パーティション 0 件で INSERT 全滅中)。
    if _table_exists("request_logs"):
        op.execute(_REQUEST_LOGS_FUNC)
        op.execute("SELECT ensure_request_logs_partitions(1);")

    # product_events: 同型の欠陥 (telemetry.ensure_next_partition() が
    # どこからも呼ばれておらず、かつ ss_user 権限では動かない死んだ関数)。
    # 同じ形の DB 関数に置き換えて直ちに 1 回 CALL しておく。
    if _table_exists("product_events"):
        op.execute(_PRODUCT_EVENTS_FUNC)
        op.execute("SELECT ensure_product_events_partitions(1);")

    # security_events は 0032 で PARTITION BY を持たない plain table として
    # 作られており、パーティション自体が存在しない。維持すべき対象がない
    # ため何もしない (欠陥は request_logs / product_events のみ)。


def downgrade() -> None:
    if not _is_postgres():
        return
    # 関数のみ削除。実データパーティションは downgrade で落とさない
    # (既存パーティションのデータを破壊してはいけない、との運用方針)。
    op.execute(_PRODUCT_EVENTS_FUNC_DROP)
    op.execute(_REQUEST_LOGS_FUNC_DROP)
