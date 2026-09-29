"""CV バッチ job のエンドポイントに所有者検査が無かった。

`TeamScopeAccessControlMiddleware` は path の数字を match_id として拾うが、
job_id は `str(uuid.uuid4())[:8]` の 16 進 8 文字:

  - tracknet のパターンは末尾 `$` なので `/batch/{job_id}/stop` に一致しない
  - yolo のパターンは一致するが **8 文字がたまたま全部数字のときだけ**
    (16 文字中 10 個が数字なので (10/16)**8 ≒ 2.3%)。そのときは
    無関係な Match をその番号で引いて可否を決めてしまう

どちらも job の所有者検査になっていない。結果、job_id を知っていれば
他チームの CV バッチの進捗を読み、**停止できた**。
`cv_candidates.py` が rally_id 経由の IDOR で踏んだのと同じ形。
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.db.database import get_db
from backend.db.models import Match, Player
from backend.main import app
from backend.routers import tracknet as tracknet_router
from backend.routers import yolo as yolo_router


@pytest.fixture()
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    c = TestClient(app, headers={"X-Role": "admin"})
    yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def match_and_outsider(db_session):
    a = Player(name="job所有A", dominant_hand="R")
    b = Player(name="job所有B", dominant_hand="R")
    outsider = Player(name="無関係な選手", dominant_hand="R")
    db_session.add_all([a, b, outsider])
    db_session.flush()
    m = Match(
        tournament="jobスコープテスト", tournament_level="practice", round="R1",
        date=date(2026, 9, 19), format="singles",
        player_a_id=a.id, player_b_id=b.id, result="unknown",
    )
    db_session.add(m)
    db_session.flush()
    db_session.commit()
    return m, outsider


@pytest.fixture(autouse=True)
def _clean_jobs():
    yolo_router._jobs.clear()
    tracknet_router._jobs.clear()
    yield
    yolo_router._jobs.clear()
    tracknet_router._jobs.clear()


# (router モジュール, status パス, stop パス)
ROUTERS = [
    (yolo_router, "/api/yolo/batch/{jid}/status", "/api/yolo/batch/{jid}/stop"),
    (tracknet_router, "/api/tracknet/batch/{jid}/status", "/api/tracknet/batch/{jid}/stop"),
]


@pytest.mark.parametrize("mod,status_path,stop_path", ROUTERS)
class TestJobEndpointsAreScopedToTheirMatch:
    def _job(self, mod, match_id, jid="3f2a9b1c"):
        mod._jobs[jid] = {"status": "running", "match_id": match_id, "progress": 0.1}
        return jid

    def test_the_owner_can_still_read_and_stop(self, client, match_and_outsider,
                                               mod, status_path, stop_path):
        """解析者の経路を塞いでいないこと。"""
        m, _ = match_and_outsider
        jid = self._job(mod, m.id)
        assert client.get(status_path.format(jid=jid)).status_code == 200
        assert client.post(stop_path.format(jid=jid)).status_code == 200

    def test_someone_outside_the_match_is_refused(self, client, match_and_outsider,
                                                  mod, status_path, stop_path):
        """その試合に出ていない player は読めないし止められない。"""
        m, outsider = match_and_outsider
        jid = self._job(mod, m.id)
        h = {"X-Role": "player", "X-Player-Id": str(outsider.id)}
        assert client.get(status_path.format(jid=jid), headers=h).status_code == 403
        assert client.post(stop_path.format(jid=jid), headers=h).status_code == 403
        # 拒否が «返事だけ» でないこと
        assert "stop_requested" not in mod._jobs[jid]

    def test_a_job_with_no_match_is_refused(self, client, mod, status_path, stop_path):
        """所有者を決められない job は fail-closed。"""
        mod._jobs["deadbeef"] = {"status": "running", "progress": 0.0}
        assert client.get(status_path.format(jid="deadbeef")).status_code == 404
        assert client.post(stop_path.format(jid="deadbeef")).status_code == 404

    def test_an_unknown_job_is_still_404(self, client, mod, status_path, stop_path):
        assert client.get(status_path.format(jid="00000000")).status_code == 404


class TestTheMiddlewarePatternCannotCoverJobIds:
    """機構そのものを固定する。パターン側を直したつもりで直らない形なので。"""

    def test_a_hex_job_id_matches_no_match_pattern(self):
        from backend.main import _MATCH_ID_PATTERNS
        jid = "3f2a9b1c"  # 16 進 8 文字。数字以外を含む典型
        for path in (f"/api/yolo/batch/{jid}/stop", f"/api/tracknet/batch/{jid}/stop"):
            assert not any(p.match(path) for p in _MATCH_ID_PATTERNS), path

    def test_an_all_digit_job_id_is_mistaken_for_a_match_id(self):
        """約 2.3% の確率で起きる。**別物の番号で可否を決めてしまう**。"""
        from backend.main import _MATCH_ID_PATTERNS
        hits = [p.match("/api/yolo/batch/12345678/stop") for p in _MATCH_ID_PATTERNS]
        hit = next((m for m in hits if m), None)
        assert hit is not None and hit.group(1) == "12345678"
