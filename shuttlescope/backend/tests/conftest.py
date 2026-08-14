"""Shared pytest fixtures for backend tests."""

# Disable the admin-MFA gate BEFORE any backend module is imported.
# Production behaviour (Round 281+): an admin role must have totp_enabled=True
# in the User row for AuthCtx.is_admin to return True. Tests bootstrap an
# admin via BOOTSTRAP_ADMIN_USERNAME/PASSWORD with no TOTP enrolment, so
# every admin-gated endpoint returns 403 in CI. The gate has a designed
# escape hatch — `SS_REQUIRE_ADMIN_MFA=0` — that must be in os.environ
# BEFORE Settings() is instantiated for the first time, since pydantic
# BaseSettings reads env vars on construction only.
import os  # noqa: E402
os.environ.setdefault("SS_REQUIRE_ADMIN_MFA", "0")

# NOTE: アプリの常駐バックグラウンドループを止める仕組み
# (`SS_DISABLE_BACKGROUND_LOOPS=1`, backend/main.py の _background_loops_disabled)
# は用意してあるが、テストでは **有効にしない**。
# 有効にすると test_websocket_signaling が軒並み落ちる — WS 系は lifespan で
# 起動される device cleanup タスクの存在を前提にしている。
# 3.12 での ERROR 多発は sys.stdout/stderr の差し替えが原因で、そちらは
# backend/main.py 側で解消済み。

# xdist 並列 (CI Linux: -n auto --dist loadfile) では複数 worker が同一 file SQLite を
# 共有し、各テストの drop_all/create_all が交錯して "table X already exists" で落ちる
# (Windows は serial なので無衝突)。backend.db.database の engine 生成より前に、
# worker ごとに別 DB ファイルへ振り分けて隔離する。
_xw = os.environ.get("PYTEST_XDIST_WORKER")
if _xw:
    _durl = os.environ.get("DATABASE_URL", "")
    if _durl.startswith("sqlite:///") and ":memory:" not in _durl:
        os.environ["DATABASE_URL"] = (
            _durl[:-3] if _durl.endswith(".db") else _durl
        ) + f"_{_xw}.db"
    elif not _durl:
        os.environ["DATABASE_URL"] = f"sqlite:///./backend/db/_pytest_{_xw}.db"

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from backend.db import database as db_module  # noqa: E402
from backend.db import models as _models  # noqa: F401,E402  # ensure metadata registration
from backend.db.database import Base  # noqa: E402
from backend.utils import response_cache  # noqa: E402


@pytest.fixture(autouse=True, scope="session")
def _disable_admin_mfa_gate():
    """Belt-and-braces: also override the runtime attribute in case some test
    overwrites it. Env-var path above is the primary defence — this fixture
    catches the case where a test directly mutates settings.ss_require_admin_mfa.
    """
    from backend.config import settings as _ss
    original = getattr(_ss, "ss_require_admin_mfa", True)
    try:
        _ss.ss_require_admin_mfa = False
    except Exception:
        pass
    yield
    try:
        _ss.ss_require_admin_mfa = original
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _reset_jwt_caches():
    """各テストで JWT 関連のグローバル cache をクリアする。
    test_database_bootstrap 等で同一プロセス内 DB 切替が起きると、
    `_MASS_REVOKE_CACHE` に過去 DB のスナップショットが残って
    後続テストの token を `mass-revoked` 扱いで 401 にする事故が観測されたため。
    """
    try:
        from backend.utils.jwt_utils import _MASS_REVOKE_CACHE
        _MASS_REVOKE_CACHE["ts"] = 0.0
        _MASS_REVOKE_CACHE["value"] = None
    except Exception:
        pass
    yield


@pytest.fixture(scope="session")
def test_engine():
    """Create one shared in-memory SQLite engine for the backend test session."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    # Force the app/database module to use the same in-memory DB everywhere,
    # including websocket helpers and short-lived SessionLocal lookups.
    original_engine = db_module.engine
    original_session_local = db_module.SessionLocal
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db_module.engine = engine
    db_module.SessionLocal = TestingSessionLocal
    yield engine
    db_module.engine = original_engine
    db_module.SessionLocal = original_session_local
    engine.dispose()


def _truncate_all_tables(engine) -> None:
    """全テーブルを空にする。

    子テーブルから消すため sorted_tables (親→子) を逆順に回す。
    SQLite の in-memory DB なので DELETE で十分速い。
    """
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())


@pytest.fixture()
def db_session(test_engine):
    """各テストに DB セッションを渡し、**テスト後に DB を空に戻す**。

    以前は rollback だけで隔離していたが、rollback で消えるのは未コミット分だけ。
    テスト対象コードもテスト自身も `commit()` するため、コミットされた行は
    セッションスコープの共有 in-memory DB に残り、同じ worker の後続テストから
    見えてしまう。これが実際に何度も CI を壊してきた:

      - test_pipeline_smoke: 他テストの ShotInference を数え込んで 3 != 5
        (2026-05-08。match 限定 count に直したが、別の数え方で 33 != 3 が再発)
      - test_benchmark_devices: admin_headers が user_id=1 の JWT を発行するだけで
        ユーザを作らず、他テストが残した user 1 の中身で 403 になる
        (ファイル内の「CI 403 fix」コメントが前回の対症療法)
      - test_mfa_recovery_codes: 作成したユーザを消さず他ファイルを巻き込んだ

    xdist はファイルを動的に配分するため「どのテストが同居するか」が実行ごとに
    変わり、汚染は**間欠的な失敗**として現れる。個々のテストに後始末を足すより、
    ここで一律に断つ方が確実。
    """
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        _truncate_all_tables(test_engine)


@pytest.fixture(autouse=True)
def reset_response_cache(db_session, monkeypatch, request):
    """Clear response cache state for every test to avoid order-dependent failures."""
    response_cache.MEMORY_CACHE.clear()
    response_cache.PLAYER_VERSION.clear()
    response_cache.DATA_VERSION = 0

    # Most integration tests seed data with flush() only. Disable the cache's DB
    # persistence layer there so a short-lived SessionLocal does not interfere with
    # the uncommitted test transaction. Keep the real DB behavior for dedicated
    # response_cache unit tests.
    if request.node.fspath.basename != "test_response_cache.py":
        monkeypatch.setattr(response_cache, "_db_lookup", lambda *a, **k: None)
        monkeypatch.setattr(response_cache, "_db_upsert", lambda *a, **k: None)
        monkeypatch.setattr(response_cache, "_db_delete_all", lambda *a, **k: None)
        monkeypatch.setattr(response_cache, "_db_delete_players", lambda *a, **k: None)
    else:
        try:
            from backend.db.models import AnalysisCache

            db_session.query(AnalysisCache).delete()
            db_session.commit()
        except Exception:
            db_session.rollback()

    yield

    response_cache.MEMORY_CACHE.clear()
    response_cache.PLAYER_VERSION.clear()
    response_cache.DATA_VERSION = 0
