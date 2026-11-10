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


# ── 時計ズレ (clock) 監視は撤去済み ───────────────────────────────────────────
#
# オーナー指示 (2026-11-06): 「サーバ時刻がずれています」の表示は不要。サーバ時刻は
# NTP (ntp.nict.jp) で同期済みで利用者に意味のある障害ではなく、ログイン (二段階認証) の
# 案内文言が付いて紛らわしかったため、clock コンポーネント・判定・自動 incident の記録
# 経路を status_monitor から全て削除した。以下は clock が二度と状態一覧・障害履歴へ
# 現れないことを固定するリグレッションテスト。

def test_clock_component_is_not_registered():
    """clock はコンポーネント定義・チェック・自動文言のいずれにも存在しない。"""
    from backend.services import status_monitor as sm
    assert "clock" not in sm.COMPONENT_KEYS
    assert "clock" not in sm._CHECKS
    assert "clock" not in sm._AUTO_TEXT
    assert "clock" not in sm._COMP_BY_KEY
    # clock 判定関数そのものも撤去されている。
    assert not hasattr(sm, "_check_clock")


def test_clock_not_sampled_and_no_incident_created():
    """サンプリングに clock が含まれず、繰り返し評価しても clock の障害履歴が作られない。"""
    from backend.services import status_monitor as sm
    from backend.db.models import StatusIncident
    db = _db()
    now = datetime(2026, 11, 6, 0, 0, 0)
    res = sm.sample_components(db)
    assert "clock" not in {r["component"] for r in res}
    for k in range(sm.CONSECUTIVE_TO_OPEN + 1):
        sm.evaluate_and_record(db, now + timedelta(minutes=10 * k))
    assert db.query(HealthSample).filter(HealthSample.component == "clock").count() == 0
    assert db.query(StatusIncident).filter(StatusIncident.component == "clock").count() == 0


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

# ── database 応答時間の表示 (F-T001-06) ──

def test_format_latency_none_shows_dash():
    assert sm._format_latency_ms(None) == "-"


def test_format_latency_submillisecond_shows_lt_1ms_not_zero():
    assert sm._format_latency_ms(0.0) == "<1ms"
    assert sm._format_latency_ms(0.2) == "<1ms"
    assert sm._format_latency_ms(0.49) == "<1ms"


def test_format_latency_keeps_real_small_values():
    assert sm._format_latency_ms(1.0) == "1ms"
    assert sm._format_latency_ms(1.4) == "1ms"
    assert sm._format_latency_ms(2.0) == "2ms"
    assert sm._format_latency_ms(47.3) == "47ms"
    assert sm._format_latency_ms(400.0) == "400ms"


def test_check_database_detail_uses_lt_1ms_for_submillisecond(monkeypatch):
    import itertools
    import backend.services.status_monitor as _sm
    seq = itertools.count(); vals = {0: 100.0, 1: 100.0003}
    monkeypatch.setattr(_sm.time, "monotonic", lambda: vals[next(seq)])

    class _FakeDB:
        def execute(self, *a, **k):
            return None

    status, metric, detail, sev = _sm._check_database(_FakeDB())
    assert status == _sm.OPERATIONAL
    assert detail.endswith("<1ms") and "0ms" not in detail
    assert 0.0 < metric < 1.0


def test_check_database_detail_keeps_real_millisecond(monkeypatch):
    import itertools
    import backend.services.status_monitor as _sm
    seq = itertools.count(); vals = {0: 100.0, 1: 100.012}
    monkeypatch.setattr(_sm.time, "monotonic", lambda: vals[next(seq)])

    class _FakeDB:
        def execute(self, *a, **k):
            return None

    status, metric, detail, sev = _sm._check_database(_FakeDB())
    assert detail == "応答 12ms" and abs(metric - 12.0) < 0.5


def test_check_database_down_keeps_ohutsunashi_and_none_metric(monkeypatch):
    """DB ダウン時は (DOWN, None, “応答なし”) のまま (表示もここを元にする)。"""
    import backend.services.status_monitor as _sm

    class _FakeDB:
        def execute(self, *a, **k):
            raise RuntimeError("down")

    status, metric, detail, sev = _sm._check_database(_FakeDB())
    assert status == _sm.DOWN
    assert metric is None
    assert detail == "応答なし"


# ── 表示経路 (compute_components): 溜まった 0ms を出さず、かつ情報を削らない ──

def test_compute_components_rebuilds_database_detail_from_metric_no_0ms():
    """DB に “応答 0ms” が保存済みでも、metric(サブミリ) から “応答 <1ms” を作る。"""
    db = _db(); now = datetime(2026, 6, 5, 12, 0, 0)
    _add(db, "database", sm.OPERATIONAL, now, metric=0.3, detail="応答 0ms")
    d = {c["key"]: c for c in sm.compute_components(db, now)}["database"]
    assert d["detail"] == "応答 <1ms" and "0ms" not in d["detail"]
    assert d["metric"] == 0.3


def test_compute_components_database_detail_keeps_real_ms():
    db = _db(); now = datetime(2026, 6, 5, 12, 0, 0)
    _add(db, "database", sm.OPERATIONAL, now, metric=12.0, detail="応答 12ms")
    d = {c["key"]: c for c in sm.compute_components(db, now)}["database"]
    assert d["detail"] == "応答 12ms"


def test_compute_components_preserves_down_ohutsunashi_detail():
    """重要: ダウン時の実際の保存値 (metric=None, detail=“応答なし”) は
    表示経路で書き換えない。“応答 -” にして「応答なし」と「未測定」を潰さない。"""
    db = _db(); now = datetime(2026, 6, 5, 12, 0, 0)
    _add(db, "database", sm.DOWN, now, metric=None, detail="応答なし")
    d = {c["key"]: c for c in sm.compute_components(db, now)}["database"]
    assert d["detail"] == "応答なし"
    assert d["metric"] is None


def test_compute_components_does_not_touch_other_components_detail():
    db = _db(); now = datetime(2026, 6, 5, 12, 0, 0)
    _add(db, "gpu", sm.OPERATIONAL, now, metric=47.0, detail="GPU 47% / VRAM 3.2/8GB")
    d = {c["key"]: c for c in sm.compute_components(db, now)}["gpu"]
    assert d["detail"] == "GPU 47% / VRAM 3.2/8GB"
