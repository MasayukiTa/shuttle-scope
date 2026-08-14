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


# ── 時計ズレ監視 (2026-07 の MFA 締め出し障害の再発防止) ────────────────────
#
# w32time が停止してサーバ時計が TOTP の窓 (±30 秒) を外れ、admin がログイン
# できなくなったが、監視は全て緑のままで何の手掛かりも出なかった。

def test_clock_operational_when_offset_small(monkeypatch):
    from backend.services import status_monitor as sm
    monkeypatch.setattr(sm, "_sntp_offset_sec", lambda server, timeout=2.0: 0.4)
    monkeypatch.setattr(sm, "_w32time_running", lambda: True)
    status, metric, detail, sev = sm._check_clock()
    assert status == sm.OPERATIONAL
    assert metric == 0.4
    assert sev is not None and sev < 1.0 / 3.0


def test_clock_degraded_when_drifting(monkeypatch):
    """TOTP がまだ通る範囲でも、ずれ始めたら警告する。"""
    from backend.services import status_monitor as sm
    monkeypatch.setattr(sm, "_sntp_offset_sec", lambda server, timeout=2.0: 9.0)
    monkeypatch.setattr(sm, "_w32time_running", lambda: True)
    status, _metric, detail, _sev = sm._check_clock()
    assert status == sm.DEGRADED
    assert "9" in detail


def test_clock_down_when_offset_breaks_totp(monkeypatch):
    """±30 秒の窓を超える手前で down 扱いにする (実際の締め出し条件)。"""
    from backend.services import status_monitor as sm
    monkeypatch.setattr(sm, "_sntp_offset_sec", lambda server, timeout=2.0: -45.0)
    monkeypatch.setattr(sm, "_w32time_running", lambda: True)
    status, metric, _detail, sev = sm._check_clock()
    assert status == sm.DOWN
    assert metric == -45.0
    assert sev == 1.0


def test_clock_degraded_when_time_service_stopped_even_without_ntp(monkeypatch):
    """NTP に到達できなくても、時刻同期サービスの停止だけで検知できること。

    「測れないので緑」にしてしまうと、前回と同じく無症状のまま放置される。
    """
    from backend.services import status_monitor as sm
    monkeypatch.setattr(sm, "_sntp_offset_sec", lambda server, timeout=2.0: None)
    monkeypatch.setattr(sm, "_w32time_running", lambda: False)
    status, _metric, detail, _sev = sm._check_clock()
    assert status == sm.DEGRADED
    assert "時刻同期" in detail


def test_clock_stays_operational_when_unmeasurable(monkeypatch):
    """NTP 遮断環境で誤検知しないこと (サービスは動いている場合)。"""
    from backend.services import status_monitor as sm
    monkeypatch.setattr(sm, "_sntp_offset_sec", lambda server, timeout=2.0: None)
    monkeypatch.setattr(sm, "_w32time_running", lambda: True)
    status, metric, _detail, sev = sm._check_clock()
    assert status == sm.OPERATIONAL
    assert metric is None and sev is None


def test_clock_component_is_registered():
    from backend.services import status_monitor as sm
    assert "clock" in sm.COMPONENT_KEYS
    assert "clock" in sm._CHECKS
    assert "clock" in sm._AUTO_TEXT
    assert sm._COMP_BY_KEY["clock"]["sev_down"] == "critical"


# ── CLOUDFLARED_METRICS_URL のスキーム制限 (Bandit B310) ────────────────────
#
# urlopen は file:// や独自スキームも開けるため、メトリクス URL を http/https に
# 限定する。運用者設定の env とはいえ、誤設定や設定ファイル汚染でローカル
# ファイル読み出しに転用される経路を残さない。
#
# 注: これらのテストは一度撤回している。当時はテストを足すと xdist の配分が
# 変わり test_benchmark_devices が巻き添えで落ちたため。原因は共有 DB の汚染で、
# conftest の db_session が teardown で全テーブルを空にするようになって解消した。

def test_metrics_url_accepts_http_and_https():
    from backend.services import status_monitor as sm
    assert sm._is_http_url("http://127.0.0.1:2000/metrics")
    assert sm._is_http_url("https://metrics.example.com/m")


def test_metrics_url_rejects_non_http_schemes():
    from backend.services import status_monitor as sm
    for bad in ("file:///C:/Windows/win.ini", "file:///etc/passwd",
                "ftp://example.com/x", "gopher://example.com/",
                "data:text/plain;base64,QQ==", "", "not a url"):
        assert not sm._is_http_url(bad), bad


def test_tunnel_check_skips_urlopen_for_non_http_scheme(monkeypatch):
    """非 http スキームでは urlopen を呼ばずプロセス判定へ落ちること。"""
    import urllib.request

    from backend.services import status_monitor as sm

    monkeypatch.setenv("CLOUDFLARED_METRICS_URL", "file:///etc/passwd")

    called = []

    def _boom(*a, **k):
        called.append(a)
        raise AssertionError("urlopen が呼ばれた")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    status, _metric, _detail, _sev = sm._check_tunnel()
    assert status in (sm.OPERATIONAL, sm.DEGRADED, sm.DOWN)
    assert not called
