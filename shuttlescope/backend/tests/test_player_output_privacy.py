"""player ロールの出力プライバシー回帰テスト (2026-10-15 監査の修正)。

実アプリ (TestClient) + player JWT で、監査が OBSERVED とした漏えいが塞がっていること、
同じ呼び出しを coach / analyst / admin が行うと従来どおりデータが返ること (変更なし) を確かめる。

  (a) /api/export/package   : 相手の体調 / 勝敗 / 相手プロフィール / EPV
  (b) /api/reports/comprehensive : 許可リスト化 (win_rate / 勝敗 / 相手 ID / 直接ルート禁止の節)
  (c) /api/reports/scouting, player_growth, prediction : win_rate / by_level 勝率 / 閾値依存の文言
  (d) /api/analysis/shot_win_loss, pre_loss_patterns : 禁止定義の単一化
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.db.database import get_db
from backend.db.models import (
    Condition, GameSet, Match, Player, Rally, Stroke, Team, User,
)
from backend.main import app
from backend.routers.auth import _hash_password
from backend.utils.jwt_utils import create_access_token

_TEAM_ID = 9101
_PLAYER_USER_ID = 10

NEUTRAL_GROWTH_MESSAGE = "バランスの取れた成長エリアがあります。継続的な練習が大切です。"


def _headers(role: str, user_id: int = 99, player_id: int | None = None) -> dict:
    tok = create_access_token(
        user_id=user_id, role=role, player_id=player_id,
        team_name="T", team_id=_TEAM_ID,
    )
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture
def world(db_session):
    db = db_session
    team = Team(id=_TEAM_ID, display_id="T-1", name="T")
    db.add(team)
    db.flush()
    own = Player(name="Own Player", name_normalized="own", team_id=team.id, height_cm=182)
    opp = Player(name="Opp Player", name_normalized="opp", nationality="JPN", birth_year=1999, height_cm=175)
    db.add_all([own, opp])
    db.flush()
    db.add(User(
        id=_PLAYER_USER_ID, username="pl", role="player", display_name="x",
        hashed_credential=_hash_password("pw"), player_id=own.id,
        team_name="T", team_id=team.id,
    ))
    m = Match(
        tournament="Cup", tournament_level="国内", round="QF", date=date(2026, 1, 1),
        format="singles", result="win", final_score="21-10,21-15",
        player_a_id=own.id, player_b_id=opp.id, owner_team_id=team.id,
    )
    db.add(m)
    db.flush()
    s = GameSet(match_id=m.id, set_num=1, winner="player_a", score_a=21, score_b=10)
    db.add(s)
    db.flush()
    for i in range(1, 6):
        r = Rally(
            set_id=s.id, rally_num=i, server="player_a",
            winner="player_a" if i % 2 else "player_b",
            end_type="smash_winner", rally_length=2, score_a_after=i, score_b_after=0,
        )
        db.add(r)
        db.flush()
        db.add(Stroke(rally_id=r.id, stroke_num=1, player="player_a", shot_type="clear",
                      hit_zone="BL", land_zone="BR", epv=0.12))
        db.add(Stroke(rally_id=r.id, stroke_num=2, player="player_b", shot_type="smash",
                      hit_zone="BL", land_zone="BR", epv=0.2))
    for p, w in ((own, 70.5), (opp, 77.7)):
        db.add(Condition(
            player_id=p.id, measured_at=date(2026, 1, 2), condition_type="weekly",
            weight_kg=w, sleep_hours=7.5, hooper_index=12, ccs_score=55.0,
        ))
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield {"db": db, "match": m, "own": own, "opp": opp}
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


def _player_h(w) -> dict:
    return _headers("player", user_id=_PLAYER_USER_ID, player_id=w["own"].id)


_OTHER_ROLES = ("coach", "analyst", "admin")


def _walk_keys(o, out=None):
    """JSON 木の全キー名 (入れ子含む) を集める。"""
    out = set() if out is None else out
    if isinstance(o, dict):
        for k, v in o.items():
            out.add(k)
            _walk_keys(v, out)
    elif isinstance(o, list):
        for x in o:
            _walk_keys(x, out)
    return out


_WINRATE_LIKE = {
    "win_rate", "win_rate_basis", "wins", "server_win_rate", "win_by_end_type",
    "result", "final_score", "winner", "player_b_id", "partner_a_id", "partner_b_id",
}


def _walk_strings(o):
    """JSON 木の全文字列値 (入れ子含む) を列挙する。"""
    if isinstance(o, dict):
        for v in o.values():
            yield from _walk_strings(v)
    elif isinstance(o, list):
        for x in o:
            yield from _walk_strings(x)
    elif isinstance(o, str):
        yield o


def _json_has_string_value(body, needle):
    """パース済み JSON のいずれかの文字列値が needle を含むなら True。
    生テキストの部分一致 (uuid/タイムスタンプ/16進署名に偶然混ざる) を避ける。"""
    return any(needle in v for v in _walk_strings(body))


def _json_has_birth_year(o, year):
    """JSON 木のどこかに birth_year キーがあり、その値が year と一致すれば True。
    文字列化した値 (例 "1999") も一致とみなす。"""
    if isinstance(o, dict):
        for k, v in o.items():
            if k == "birth_year" and (v == year or str(v) == str(year)):
                return True
            if _json_has_birth_year(v, year):
                return True
    elif isinstance(o, list):
        for x in o:
            if _json_has_birth_year(x, year):
                return True
    return False


# ─── (a) export/package ──────────────────────────────────────────────────────

class TestExportPackage:
    def test_player_conditions_only_own_and_consent_filtered(self, world, client):
        w = world
        r = client.get(
            f"/api/export/package?match_id={w['match'].id}&sections=conditions",
            headers=_player_h(w),
        )
        assert r.status_code == 200, r.text
        rows = r.json()["conditions"]
        assert rows, "本人の体調は返る"
        assert {c["player_id"] for c in rows} == {w["own"].id}
        # 体組成 (Tier 3) は player のフィルタで落ちる。相手の値 77.7 はどこにも出ない。
        assert all("weight_kg" not in c for c in rows)
        assert "77.7" not in r.text

    @pytest.mark.parametrize("role", _OTHER_ROLES)
    def test_other_roles_conditions_unchanged(self, world, client, role):
        w = world
        r = client.get(
            f"/api/export/package?match_id={w['match'].id}&sections=conditions",
            headers=_headers(role),
        )
        assert r.status_code == 200, r.text
        rows = r.json()["conditions"]
        assert {c["player_id"] for c in rows} == {w["own"].id, w["opp"].id}
        assert {c["weight_kg"] for c in rows} == {70.5, 77.7}

    def test_player_default_package_has_no_results_opponent_or_epv(self, world, client, monkeypatch):
        from backend.config import settings
        monkeypatch.setattr(settings, "ss_export_signing_key", "k" * 40, raising=False)
        w = world
        r = client.get(f"/api/export/package?match_id={w['match'].id}", headers=_player_h(w))
        assert r.status_code == 200, r.text
        body = r.json()
        assert "result" not in body["match"] and "final_score" not in body["match"]
        assert [p["id"] for p in body["players"]] == [w["own"].id]
        # 相手名・生年は構造化された JSON 値のどこにも現れない。
        # 生テキストだと uuid/タイムスタンプ/16進署名に "1999" が偶然混ざり得るため
        # パース済みの値だけを調べる。
        assert not _json_has_string_value(body, "Opp Player")
        assert not _json_has_birth_year(body, 1999)
        assert all("winner" not in s and "score_a" not in s for s in body["sets"])
        assert body["rallies"] and all(
            "winner" not in x and "score_a_after" not in x for x in body["rallies"]
        )
        assert body["strokes"] and all("epv" not in s for s in body["strokes"])
        assert "_signature" in body  # 縮約後のパッケージに署名が付く

    def test_player_reports_section_has_no_win_counts(self, world, client):
        w = world
        r = client.get(
            f"/api/export/package?match_id={w['match'].id}&sections=reports,strokes",
            headers=_player_h(w),
        )
        assert r.status_code == 200, r.text
        rep = r.json()["reports"]
        assert rep["total_rallies"] == 5
        assert not ({"rally_wins_a", "rally_wins_b", "result", "final_score"} & set(rep))
        assert all("epv" not in s for s in r.json()["strokes"])

    @pytest.mark.parametrize("role", _OTHER_ROLES)
    def test_other_roles_default_package_unchanged(self, world, client, role, monkeypatch):
        from backend.config import settings
        monkeypatch.setattr(settings, "ss_export_signing_key", "k" * 40, raising=False)
        w = world
        r = client.get(f"/api/export/package?match_id={w['match'].id}", headers=_headers(role))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["match"]["result"] == "win"
        assert body["match"]["final_score"] == "21-10,21-15"
        assert len(body["players"]) == 2
        assert body["sets"][0]["winner"] == "player_a"
        assert all("winner" in x for x in body["rallies"])
        assert all(s["epv"] is not None for s in body["strokes"])
        assert "_signature" in body  # 従来どおり署名付き


# ─── (b) comprehensive ───────────────────────────────────────────────────────

class TestComprehensive:
    def test_player_json_is_allow_list(self, world, client):
        from backend.utils.player_privacy import PLAYER_COMPREHENSIVE_ALLOWED_SECTIONS
        w = world
        r = client.get(f"/api/reports/comprehensive?player_id={w['own'].id}", headers=_player_h(w))
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body["sections"]) <= set(PLAYER_COMPREHENSIVE_ALLOWED_SECTIONS)
        for forbidden in ("rally_length_winrate", "temporal_performance",
                          "shot_transition_matrix", "shot_win_loss", "pre_loss_patterns",
                          "pressure_performance", "opponent_stats"):
            assert forbidden not in body["sections"]
        assert not (_walk_keys(body["sections"]) & _WINRATE_LIKE)
        assert not _json_has_string_value(body, "Opp Player")
        # サンプル数 / 信頼度メタは残る
        d = body["sections"]["descriptive"]["data"]
        assert d["data"]["total_rallies"] == 5
        assert d["meta"]["sample_size"] == 5 and "confidence" in d["meta"]
        # matches[]: 勝敗・スコア・相手 ID・uuid なし
        assert len(body["matches"]) == 1
        mrow = body["matches"][0]
        assert mrow["rally_count"] == 5
        assert not ({"result", "final_score", "player_b_id", "partner_a_id",
                     "partner_b_id", "player_a_id", "uuid"} & set(mrow))

    @pytest.mark.parametrize("role", _OTHER_ROLES)
    def test_other_roles_unchanged(self, world, client, role):
        w = world
        r = client.get(f"/api/reports/comprehensive?player_id={w['own'].id}", headers=_headers(role))
        assert r.status_code == 200, r.text
        body = r.json()
        for sec in ("rally_length_winrate", "temporal_performance", "shot_transition_matrix",
                    "shot_win_loss", "pre_loss_patterns", "set_comparison"):
            assert sec in body["sections"], sec
        assert body["sections"]["descriptive"]["data"]["data"]["win_rate"] == 0.6
        mrow = body["matches"][0]
        assert mrow["result"] == "win" and mrow["final_score"] == "21-10,21-15"
        assert mrow["player_b_id"] == w["opp"].id

    def test_direct_service_call_as_player_is_allow_listed(self, world):
        """PDF 生成も同じ gather_player_report の出力を描画する。サービス層直呼びでも同じ。"""
        from backend.services.comprehensive_report import gather_player_report
        from backend.utils.auth import AuthCtx
        w = world
        ctx = AuthCtx(role="player", player_id=w["own"].id, team_name="T", team_id=_TEAM_ID)
        data = gather_player_report(w["db"], w["own"].id, ctx, include_per_match=False)
        assert "rally_length_winrate" not in data["sections"]
        assert not (_walk_keys(data["sections"]) & _WINRATE_LIKE)


# ─── (c) scouting / player_growth / prediction ───────────────────────────────

def _json_or_none(resp):
    """reportlab のある環境では scouting は PDF を返す。JSON のときだけ中身を見る。"""
    if "json" in resp.headers.get("content-type", ""):
        return resp.json()
    return None


class TestReports:
    def test_scouting_player_has_no_win_rate(self, world, client):
        w = world
        r = client.get(f"/api/reports/scouting?player_id={w['own'].id}", headers=_player_h(w))
        assert r.status_code == 200, r.text
        body = _json_or_none(r)
        if body is not None:
            assert "win_rate" not in body["data"] and "win_rate_basis" not in body["data"]
            assert body["meta"]["sample_size"] == 5

    @pytest.mark.parametrize("role", _OTHER_ROLES)
    def test_scouting_other_roles_unchanged(self, world, client, role):
        w = world
        r = client.get(f"/api/reports/scouting?player_id={w['own'].id}", headers=_headers(role))
        assert r.status_code == 200, r.text
        body = _json_or_none(r)
        if body is not None:
            assert body["data"]["win_rate"] == 0.6

    def test_growth_player_has_no_win_rate_and_message_ignores_win_rate(self, world, client):
        w = world
        url = f"/api/reports/player_growth?player_id={w['own'].id}"
        r = client.get(url, headers=_player_h(w))
        assert r.status_code == 200, r.text
        body = r.json()
        assert "win_rate" not in body["data"] and "win_rate_basis" not in body["data"]
        assert body["meta"]["sample_size"] == 5
        msg_at_60 = body["data"]["growth_message"]
        assert msg_at_60 == NEUTRAL_GROWTH_MESSAGE
        # 勝率を 0.0 に変えても (旧実装なら別の文言になる閾値帯)、player の文言は変わらない
        db = w["db"]
        for rally in db.query(Rally).all():
            rally.winner = "player_b"
        db.commit()
        r2 = client.get(url, headers=_player_h(w))
        assert r2.json()["data"]["growth_message"] == msg_at_60
        # coach は従来どおり勝率に連動し win_rate も返る
        rc = client.get(url, headers=_headers("coach")).json()
        assert rc["data"]["win_rate"] == 0.0
        assert rc["data"]["growth_message"] != NEUTRAL_GROWTH_MESSAGE

    @pytest.mark.parametrize("role", _OTHER_ROLES)
    def test_growth_other_roles_unchanged(self, world, client, role):
        w = world
        r = client.get(f"/api/reports/player_growth?player_id={w['own'].id}", headers=_headers(role))
        assert r.status_code == 200, r.text
        assert r.json()["data"]["win_rate"] == 0.6
        assert "安定した成果" in r.json()["data"]["growth_message"]

    def test_prediction_player_has_no_win_rates(self, world, client):
        w = world
        r = client.get(f"/api/reports/prediction?player_id={w['own'].id}", headers=_player_h(w))
        assert r.status_code == 200, r.text
        body = r.json()
        assert not (_walk_keys(body["data"]) & {"win_rate", "win_rate_basis"})
        assert body["data"]["overall"]["total_rallies"] == 5
        assert body["data"]["by_level"][0]["rallies"] == 5
        assert body["meta"]["sample_size"] == 5

    @pytest.mark.parametrize("role", _OTHER_ROLES)
    def test_prediction_other_roles_unchanged(self, world, client, role):
        w = world
        r = client.get(f"/api/reports/prediction?player_id={w['own'].id}", headers=_headers(role))
        assert r.status_code == 200, r.text
        d = r.json()["data"]
        assert d["overall"]["win_rate"] == 0.6
        assert d["by_level"][0]["win_rate"] == 0.6


# ─── (d) analysis 禁止定義の単一化 ───────────────────────────────────────────

class TestAnalysisForbiddenDefinition:
    @pytest.mark.parametrize("name", ["shot_win_loss", "pre_loss_patterns"])
    def test_player_forbidden_but_others_ok(self, world, client, name):
        w = world
        url = f"/api/analysis/{name}?player_id={w['own'].id}"
        assert client.get(url, headers=_player_h(w)).status_code == 403
        for role in _OTHER_ROLES:
            r = client.get(url, headers=_headers(role))
            assert r.status_code == 200, (role, r.text)

    def test_single_constant_feeds_middleware_and_sanity_check(self):
        import backend.main as main_mod
        from backend.utils.player_privacy import (
            PLAYER_COMPREHENSIVE_ALLOWED_SECTIONS, PLAYER_FORBIDDEN_NAMED_ANALYSIS_PATHS,
        )
        assert "/api/analysis/shot_win_loss" in PLAYER_FORBIDDEN_NAMED_ANALYSIS_PATHS
        assert "/api/analysis/pre_loss_patterns" in PLAYER_FORBIDDEN_NAMED_ANALYSIS_PATHS
        assert PLAYER_FORBIDDEN_NAMED_ANALYSIS_PATHS <= main_mod._PLAYER_FORBIDDEN_ANALYSIS_PATHS
        assert len(main_mod._PLAYER_FORBIDDEN_ANALYSIS_PATHS) >= main_mod._EXPECTED_MIN_FORBIDDEN_PATHS
        # 包括レポートの許可リストに、直接ルートで禁止されている解析が含まれない
        for sec in PLAYER_COMPREHENSIVE_ALLOWED_SECTIONS:
            assert f"/api/analysis/{sec}" not in main_mod._PLAYER_FORBIDDEN_ANALYSIS_PATHS

    @pytest.mark.parametrize("path", ["/analysis/shot_win_loss", "/analysis/pre_loss_patterns"])
    def test_route_level_dependency_present(self, path):
        """ミドルウェアが外れても (または経路が増えても) ルート自身が player を拒否する。"""
        from backend.utils.auth import require_non_player
        from backend.routers.analysis_stable import router as stable_router
        routes = [r for r in stable_router.routes if getattr(r, "path", None) == path]
        assert routes
        for route in routes:
            deps = [d.call for d in route.dependant.dependencies]
            assert require_non_player in deps


# ─── (e) height_cm: export surface に出さない / team スコープ内の /players には出る ──


def _json_has_key(o, key) -> bool:
    """JSON 木のどこかに key という名のキーが存在すれば True。"""
    if isinstance(o, dict):
        for k, v in o.items():
            if k == key:
                return True
            if _json_has_key(v, key):
                return True
    elif isinstance(o, list):
        for x in o:
            if _json_has_key(x, key):
                return True
    return False


class TestHeightExportSurface:
    """height_cm は team スコープ内の選手プロフィール属性。
    public/shared/export (data_package._player_dict の allow-list) には出さない。
    birth_year と違い export の _player_dict にはそもそも含めていないので、
    player だけでなく coach/analyst/admin のパッケージにも現れない。"""

    @pytest.mark.parametrize("role", ("player", "coach", "analyst", "admin"))
    def test_height_cm_absent_from_export_package(self, world, client, role, monkeypatch):
        from backend.config import settings
        monkeypatch.setattr(settings, "ss_export_signing_key", "k" * 40, raising=False)
        w = world
        headers = _player_h(w) if role == "player" else _headers(role)
        r = client.get(f"/api/export/package?match_id={w['match'].id}", headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        # players[] に height_cm キーが無い (allow-list 非含)。
        assert not _json_has_key(body.get("players", []), "height_cm")
        # 値 (182 / 175) も構造化 JSON のどこにも現れない。
        assert not _json_has_key(body, "height_cm")

    def test_height_cm_present_in_players_list_within_team(self, world, client):
        """team スコープ内の /api/players には height_cm が返る (coach)。
        opp は無所属 (team_id なし) のため coach の scope 外。その height 非出力は
        export 側 (TestHeightExportSurface) で担保するので、ここでは own だけ検証する。"""
        w = world
        r = client.get("/api/players", headers=_headers("coach"))
        assert r.status_code == 200, r.text
        rows = r.json()["data"]
        by_id = {p["id"]: p for p in rows}
        assert w["own"].id in by_id, "自チームの選手は返る"
        assert by_id[w["own"].id]["height_cm"] == 182
        # キー自体が応答に存在する (null でなく値が乗る) ことも確かめる。
        assert "height_cm" in by_id[w["own"].id]


def test_json_privacy_helpers_detect_planted_values():
    """ヘルパーが本物の漏えいを検出することの証明 (植え込みテスト)。
    相手名・生年を JSON 値として埋めれば検出し、
    uuid/署名文字列に偶然混ざった "1999" は (birth_year 値でない限り) 検出しない。"""
    leaked = {"players": [{"name": "Opp Player", "birth_year": 1999}]}
    assert _json_has_string_value(leaked, "Opp Player")
    assert _json_has_birth_year(leaked, 1999)
    assert _json_has_birth_year({"p": {"birth_year": "1999"}}, 1999)
    clean = {"_signature": "a1999ff", "uuid": "1999-0000", "ts": "2026-01-01T19:99:00"}
    assert not _json_has_string_value(clean, "Opp Player")
    assert not _json_has_birth_year(clean, 1999)
