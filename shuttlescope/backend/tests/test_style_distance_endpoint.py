"""test_style_distance_endpoint.py — STYLE-001 style_distance エンドポイントの結合テスト

テスト設計:
- optimal_transport_loader.load_zone_histograms は
  「自分以外 かつ 試合数 >= min_matches=3」の選手をコホートに含める。
- 参照選手 (ref) と 2 人のコホート選手をシードし、
  各選手のストロークに異なる land_zone 分布を持たせることで
  Wasserstein 距離が非ゼロになることを検証する。
- admin ctx は allowed_player_ids=None (無制限) のため、チームスコープは不要。
"""
import pytest
from datetime import date
from fastapi.testclient import TestClient

from backend.main import app
from backend.db.database import get_db
from backend.db.models import Player, Match, GameSet, Rally, Stroke
from backend.utils.auth import (
    AuthCtx,
    get_auth,
    require_admin_or_analyst,
    require_non_player,
)


# ── テスト用 admin AuthCtx ────────────────────────────────────────────────────

def _admin_ctx() -> AuthCtx:
    return AuthCtx(role="admin", player_id=None, user_id=1, team_name=None, team_id=None)


# ── シードヘルパー ─────────────────────────────────────────────────────────────

def _make_match(db, player_a_id: int, player_b_id: int, match_num: int) -> Match:
    """シングルス試合を1試合生成して返す。"""
    m = Match(
        tournament=f"OT Test {match_num}",
        tournament_level="IC",
        round="R1",
        date=date(2025, 8, match_num % 28 + 1),
        format="singles",
        player_a_id=player_a_id,
        player_b_id=player_b_id,
        result="win",
        annotation_status="complete",
        annotation_progress=1.0,
    )
    db.add(m)
    db.flush()
    return m


def _make_set_and_rally(db, match_id: int, set_num: int = 1) -> tuple:
    """1セット1ラリーを生成して (GameSet, Rally) を返す。"""
    gs = GameSet(
        match_id=match_id,
        set_num=set_num,
        winner="player_a",
        score_a=21,
        score_b=10,
    )
    db.add(gs)
    db.flush()

    rally = Rally(
        set_id=gs.id,
        rally_num=1,
        server="player_a",
        winner="player_a",
        end_type="forced_error",
        rally_length=3,
        score_a_after=21,
        score_b_after=10,
    )
    db.add(rally)
    db.flush()
    return gs, rally


def _add_stroke(db, rally_id: int, player: str, land_zone: str, stroke_num: int = 1):
    """指定 land_zone のストロークを1本追加する。"""
    s = Stroke(
        rally_id=rally_id,
        stroke_num=stroke_num,
        player=player,
        shot_type="clear",
        hit_zone="BC",
        land_zone=land_zone,
        hit_y=0.2,
    )
    db.add(s)


def _seed_style_players(db):
    """
    参照選手 (ref) と 2 人のコホート選手を生成する。

    各選手は 3 試合 (min_matches=3 を満たす) を持ち、
    異なる land_zone 分布でストロークを打つ:
      - ref:    BL / BC / BR 奥寄り
      - cohort1: NL / NC / NR 前寄り
      - cohort2: ML / MC / MR 中間

    異なる分布を持たせることで Wasserstein 距離が非ゼロになる。
    """
    ref = Player(name="StyleRef", dominant_hand="R")
    c1 = Player(name="StyleCohort1", dominant_hand="R")
    c2 = Player(name="StyleCohort2", dominant_hand="L")
    db.add(ref); db.add(c1); db.add(c2)
    db.flush()

    # 各選手ペアで 3 試合生成 (ref vs c1, ref vs c2, c1 vs c2 の各 3 回)
    # これで全員が 3+ 試合を持つ
    zone_map = {
        ref.id:  ["BL", "BC", "BR"],   # 奥ゾーン中心
        c1.id:   ["NL", "NC", "NR"],   # 前ゾーン中心
        c2.id:   ["ML", "MC", "MR"],   # 中間ゾーン中心
    }

    pairs = [
        (ref.id, c1.id),
        (ref.id, c2.id),
        (c1.id, c2.id),
    ]
    match_num = 0
    for a_id, b_id in pairs:
        for repeat in range(3):  # 各ペア 3 試合 → 全員 min_matches=3 以上を確保
            match_num += 1
            m = _make_match(db, a_id, b_id, match_num)
            _, rally = _make_set_and_rally(db, m.id)

            # player_a のストローク
            zones_a = zone_map[a_id]
            _add_stroke(db, rally.id, "player_a", zones_a[repeat % len(zones_a)], stroke_num=1)

            # player_b のストローク
            zones_b = zone_map[b_id]
            _add_stroke(db, rally.id, "player_b", zones_b[repeat % len(zones_b)], stroke_num=2)

    db.flush()
    return ref.id


# ── フィクスチャ ──────────────────────────────────────────────────────────────

@pytest.fixture
def style_distance_client(db_session):
    """シードデータ付きの TestClient を返す。"""
    ref_id = _seed_style_players(db_session)
    db_session.flush()

    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_auth] = _admin_ctx
    app.dependency_overrides[require_admin_or_analyst] = _admin_ctx
    app.dependency_overrides[require_non_player] = _admin_ctx

    client = TestClient(app)
    yield client, ref_id
    app.dependency_overrides.clear()


# ── テストケース ──────────────────────────────────────────────────────────────

class TestStyleDistanceEndpoint:

    def test_returns_200_with_success(self, style_distance_client):
        """エンドポイントが 200 を返し success=True であること。"""
        client, ref_id = style_distance_client
        resp = client.get(f"/api/analysis/style_distance?player_id={ref_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True

    def test_response_has_required_keys(self, style_distance_client):
        """レスポンスに reference_player / distances / style_map / zone_labels が含まれること。"""
        client, ref_id = style_distance_client
        resp = client.get(f"/api/analysis/style_distance?player_id={ref_id}")
        body = resp.json()
        data = body["data"]
        assert data["reference_player"] == ref_id
        assert "distances" in data
        assert "style_map" in data
        assert "zone_labels" in data
        meta = body["meta"]
        assert meta["analysis_type"] == "style_distance"

    def test_zone_labels_has_9_entries(self, style_distance_client):
        """zone_labels は 9 ゾーン (BL/BC/BR/ML/MC/MR/NL/NC/NR) を返すこと。"""
        client, ref_id = style_distance_client
        resp = client.get(f"/api/analysis/style_distance?player_id={ref_id}")
        body = resp.json()
        zone_labels = body["data"]["zone_labels"]
        assert len(zone_labels) == 9, f"zone_labels 数が不正: {zone_labels}"

    def test_distances_list_nonempty_with_cohort(self, style_distance_client):
        """コホートが存在するとき distances リストが空でないこと。"""
        client, ref_id = style_distance_client
        resp = client.get(f"/api/analysis/style_distance?player_id={ref_id}")
        body = resp.json()
        distances = body["data"]["distances"]
        assert isinstance(distances, list)
        assert len(distances) >= 1, (
            "コホートが2名いるので distances は空でないはず。"
            f" distances: {distances}"
        )

    def test_style_map_has_xy_per_player(self, style_distance_client):
        """style_map の各エントリに x / y 座標が含まれること。"""
        client, ref_id = style_distance_client
        resp = client.get(f"/api/analysis/style_distance?player_id={ref_id}")
        body = resp.json()
        style_map = body["data"]["style_map"]
        assert isinstance(style_map, list)
        assert len(style_map) >= 1
        for entry in style_map:
            assert "x" in entry and "y" in entry, f"x/y キーが不足: {entry}"
            assert isinstance(entry["x"], (int, float)), f"x が数値でない: {entry}"
            assert isinstance(entry["y"], (int, float)), f"y が数値でない: {entry}"

    def test_single_player_returns_empty_distances(self, db_session):
        """コホートが存在しない場合 distances == [] が返ること。"""
        solo = Player(name="StyleSolo", dominant_hand="R")
        db_session.add(solo)
        db_session.flush()
        solo_id = solo.id

        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[get_auth] = _admin_ctx
        app.dependency_overrides[require_admin_or_analyst] = _admin_ctx
        app.dependency_overrides[require_non_player] = _admin_ctx
        try:
            client = TestClient(app)
            resp = client.get(f"/api/analysis/style_distance?player_id={solo_id}")
            assert resp.status_code == 200
            body = resp.json()
            assert body["success"] is True
            assert body["data"]["distances"] == []
        finally:
            app.dependency_overrides.clear()
