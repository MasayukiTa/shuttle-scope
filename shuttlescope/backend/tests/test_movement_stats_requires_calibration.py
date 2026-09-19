"""キャリブレーションが無いなら移動統計を出さない。

旧実装は `GET /yolo/movement_stats/{match_id}` がキャリブレーション未設定でも
数字を返し、`confidence.level = "low"` と
「距離精度が低下しています」を添えていた。精度の問題ではない。

射影が無いとき本体は

    cx_c, cy_c = cx_img, cy_img      # 画面内の 0..1

として**画面内の比率をそのままコート座標に使い**、それに `court_width_m` /
`court_length_m` を掛けてメートルを名乗っていた。総移動距離も平均速度も
18 ゾーンの滞在数も、コートとは無関係な数になる。単位が付いているぶん
もっともらしく見える。

2026-09-19 のユーザ判断:「キャリブレーションがない限りは出さない。
キャリブレーションできていないよとあれば、ユーザがキャリブレーションして
表示される形になればいい」。
"""
from __future__ import annotations

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.db.database import get_db
from backend.db.models import Match, MatchCVArtifact, Player
from backend.main import app


@pytest.fixture()
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    c = TestClient(app, headers={"X-Role": "admin"})
    yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def match_id(db_session) -> int:
    a = Player(name="移動統計A", dominant_hand="R")
    b = Player(name="移動統計B", dominant_hand="R")
    db_session.add_all([a, b])
    db_session.flush()
    m = Match(
        tournament="移動統計テスト",
        tournament_level="practice",
        round="R1",
        date=date(2026, 9, 19),
        format="singles",
        player_a_id=a.id,
        player_b_id=b.id,
        result="unknown",
    )
    db_session.add(m)
    db_session.flush()
    db_session.commit()
    return m.id


def _identity_track(db_session, match_id: int) -> None:
    """選手が画面内を移動する識別トラックを 1 本置く。

    キャリブレーションは**置かない**。旧実装はこれだけで
    「総移動距離 N m」を返していた。
    """
    frames = []
    for i in range(200):
        x = 0.2 + 0.006 * i          # 画面を左から右へ
        frames.append({
            "timestamp_sec": i * 0.1,
            "players": [{
                "player_key": "player_a",
                "bbox": [x, 0.30, x + 0.05, 0.55],
                "lost": False,
            }],
        })
    db_session.add(MatchCVArtifact(
        match_id=match_id,
        artifact_type="player_identity_track",
        data=json.dumps(frames),
    ))
    db_session.commit()


def _get(client, match_id: int):
    return client.get(f"/api/yolo/movement_stats/{match_id}")


class TestWithoutCalibration:
    def test_nothing_is_reported(self, client, db_session, match_id):
        _identity_track(db_session, match_id)
        res = _get(client, match_id)
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["available"] is False, "キャリブレーション無しで統計を出している"

    def test_the_reason_says_calibration_so_the_ui_can_offer_it(
        self, client, db_session, match_id,
    ):
        """「データがありません」で終わらせない。

        ユーザがその場でキャリブレーションへ行けるよう、
        画面は `needs_calibration` を見て導線を出す。
        """
        _identity_track(db_session, match_id)
        data = _get(client, match_id).json()["data"]
        assert data.get("needs_calibration") is True
        assert "キャリブレーション" in data.get("reason", "")

    def test_no_distance_or_speed_leaks_into_the_response(
        self, client, db_session, match_id,
    ):
        """数値そのものが応答に載っていないこと。

        `available: false` を返しつつ players を同梱する実装だと、
        画面が読み替えた瞬間に同じ嘘が戻る。
        """
        _identity_track(db_session, match_id)
        body = _get(client, match_id).text
        for leaked in ("total_distance_m", "avg_speed_m_per_s", "zone_visits"):
            assert leaked not in body, f"{leaked} が応答に残っている"


class TestWithoutAnyTrack:
    def test_the_missing_track_message_is_unchanged(self, client, match_id):
        """トラックが無い場合は従来どおり（キャリブの話にすり替えない）。"""
        data = _get(client, match_id).json()["data"]
        assert data["available"] is False
        assert data.get("needs_calibration") is not True


class TestZoneClassificationUsesTheSharedFunction:
    """18 ゾーンの式を書き写さないこと。

    同じ式が 4 箇所に複製されていて、C-6 で `court_calibration` のものだけ
    直した結果、`yolo.py` には古い挙動（[0,1] にクランプしてから行・列を
    出す）が残っていた。コート外に立っている選手が端ゾーンの滞在として
    数えられる。バドミントンでは選手がラインの外へ出るのは普通なので、
    これは珍しい例外ではなく日常的に混ざる。
    """

    def test_the_formula_is_not_copied_into_yolo_router(self):
        import pathlib
        src = (pathlib.Path(__file__).resolve().parents[1]
               / "routers" / "yolo.py").read_text(encoding="utf-8")
        assert "pixel_to_court_zone" in src, "共有関数を呼んでいない"
        for copied in ("* 3), 2)", "* 6), 5)"):
            assert copied not in src, f"18ゾーンの式が書き写されている: {copied}"
