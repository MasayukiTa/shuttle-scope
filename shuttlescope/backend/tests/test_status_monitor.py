"""status_monitor の自動 incident / コンポーネント集計ロジックのテスト。

実機依存のチェック関数 (GPU/tunnel 等) は呼ばず、HealthSample を直接入れて
評価ロジック (open/resolve, uptime, prune) を検証する。"""
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.db.models import Base, HealthSample
from backend.services import status_monitor as sm


def _db():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def _add(db, comp, status, t, metric=None, detail=None):
    db.add(HealthSample(component=comp, status=status, metric=metric, detail=detail, sampled_at=t))
    db.commit()


def test_sample_components_returns_all_keys():
    db = _db()
    res = sm.sample_components(db)
    assert {r["component"] for r in res} == set(sm.COMPONENT_KEYS)
    for r in res:
        assert r["status"] in (sm.OPERATIONAL, sm.DEGRADED, sm.DOWN)


def test_auto_incident_opens_then_resolves():
    db = _db()
    now = datetime(2026, 6, 5, 0, 0, 0)
    _add(db, "tunnel", sm.DOWN, now)
    sm._manage_auto_incident(db, "tunnel", now); db.commit()
    assert sm._open_auto_incident(db, "tunnel") is None  # 1 回ではまだ開かない
    _add(db, "tunnel", sm.DOWN, now + timedelta(minutes=1))
    sm._manage_auto_incident(db, "tunnel", now + timedelta(minutes=1)); db.commit()
    inc = sm._open_auto_incident(db, "tunnel")
    assert inc is not None and inc.severity == "critical" and inc.source == "auto"
    assert inc.began_at == now + timedelta(minutes=1)

    _add(db, "tunnel", sm.OPERATIONAL, now + timedelta(minutes=2))
    sm._manage_auto_incident(db, "tunnel", now + timedelta(minutes=2)); db.commit()
    assert sm._open_auto_incident(db, "tunnel") is not None  # 1 回ではまだ解決しない
    _add(db, "tunnel", sm.OPERATIONAL, now + timedelta(minutes=3))
    sm._manage_auto_incident(db, "tunnel", now + timedelta(minutes=3)); db.commit()
    assert sm._open_auto_incident(db, "tunnel") is None  # 自動 resolve


def test_degraded_uses_lower_severity():
    db = _db()
    now = datetime(2026, 6, 5, 0, 0, 0)
    for k in range(sm.CONSECUTIVE_TO_OPEN):
        _add(db, "gpu", sm.DEGRADED, now + timedelta(minutes=k))
        sm._manage_auto_incident(db, "gpu", now + timedelta(minutes=k)); db.commit()
    inc = sm._open_auto_incident(db, "gpu")
    assert inc is not None and inc.severity == "minor"  # gpu degraded -> minor


def test_compute_components_uptime_and_latest():
    db = _db()
    now = datetime(2026, 6, 5, 12, 0, 0)
    _add(db, "gpu", sm.OPERATIONAL, now - timedelta(hours=1))
    _add(db, "gpu", sm.DOWN, now - timedelta(minutes=30))
    _add(db, "gpu", sm.OPERATIONAL, now, metric=47.0, detail="GPU 47%")
    comps = {c["key"]: c for c in sm.compute_components(db, now)}
    g = comps["gpu"]
    assert g["status"] == "operational" and g["metric"] == 47.0 and g["detail"] == "GPU 47%"
    assert abs(g["uptime_24h"] - 66.67) < 0.1   # 2 operational / 3 total
    assert comps["worker"]["status"] == "unknown"  # サンプル無し
    assert comps["worker"]["uptime_24h"] is None


def test_component_history_daily_buckets():
    db = _db()
    now = datetime(2026, 6, 5, 12, 0, 0)
    _add(db, "gpu", sm.OPERATIONAL, now)
    _add(db, "gpu", sm.OPERATIONAL, now - timedelta(days=1, hours=2))
    _add(db, "gpu", sm.DOWN, now - timedelta(days=1, hours=1))  # 昨日は down 混在
    hist = sm.compute_component_history(db, days=90, now=now)
    g = hist["gpu"]
    assert len(g["days"]) == 90
    assert g["days"][-1]["st"] == "operational"   # 今日
    assert g["days"][-2]["st"] == "down"          # 昨日 (down 優先)
    assert g["days"][0]["st"] == "nodata"         # 90日前はデータ無し
    # uptime はサンプル比で算出 (日数ベースではない): 2 operational / 3 total = 66.67%。
    # (旧実装は日数ベースで 50.0% = 2日中1日up だったが、1サンプルの down で
    #  その日を丸ごと非稼働扱いするのは過度に厳しいためサンプル比に是正済み。)
    assert abs(g["uptime_pct"] - 66.67) < 0.1


def test_evaluate_and_record_writes_and_prunes():
    db = _db()
    now = datetime(2026, 6, 5, 0, 0, 0)
    old = now - timedelta(days=sm.SAMPLE_RETENTION_DAYS + 1)
    _add(db, "gpu", sm.OPERATIONAL, old)
    sm.evaluate_and_record(db, now)
    assert db.query(HealthSample).filter(HealthSample.sampled_at == now).count() == len(sm.COMPONENT_KEYS)
    assert db.query(HealthSample).filter(HealthSample.sampled_at == old).count() == 0  # prune
