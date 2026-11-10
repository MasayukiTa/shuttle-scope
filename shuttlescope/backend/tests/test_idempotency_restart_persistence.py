"""Process-restart durability for idempotency records.

Offline clients can legitimately retry a committed annotation after the backend
process restarts. The in-memory cache must therefore be optional: clearing it
must still recover the dedup record from the persistent DB.
"""
from __future__ import annotations

from backend.db.models import AnalysisCache
from backend.utils import idempotency as idem


def test_idempotency_record_hydrates_from_db_after_process_cache_reset(db_session):
    key = "restart-durable-idem-0001"
    payload = {"success": True, "data": {"id": 4242, "kind": "annotation"}}

    idem.store(
        key,
        user_id=77,
        endpoint="stroke:create:99",
        response_obj=payload,
        status_code=201,
    )

    # Prove the persistent side actually exists before simulating restart.
    db_session.expire_all()
    row = (
        db_session.query(AnalysisCache)
        .filter(AnalysisCache.cache_key == f"idem:{key}")
        .one_or_none()
    )
    assert row is not None
    assert row.analysis_type == "idempotency"

    # Process restart: every Python object/cache entry disappears, DB survives.
    with idem._lock:
        idem._records.clear()

    recovered = idem.get_cached(key, user_id=77, endpoint="stroke:create:99")
    assert recovered is not None
    assert recovered.status_code == 201
    assert idem.replay_response(recovered) == payload


def test_restart_hydration_preserves_user_and_endpoint_binding(db_session):
    key = "restart-durable-idem-0002"
    idem.store(
        key,
        user_id=88,
        endpoint="rally:create",
        response_obj={"success": True, "data": {"id": 7}},
    )

    with idem._lock:
        idem._records.clear()

    assert idem.get_cached(key, user_id=89, endpoint="rally:create") is None
    assert idem.get_cached(key, user_id=88, endpoint="stroke:create") is None

    recovered = idem.get_cached(key, user_id=88, endpoint="rally:create")
    assert recovered is not None
    assert idem.replay_response(recovered)["data"]["id"] == 7
