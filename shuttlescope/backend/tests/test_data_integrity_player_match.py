"""データ整合性の回帰テスト (監査 #522 / #525 / #526 / #527 / #528)。

- #527 選手の試合一覧・スタッツは 4 スロット (player_a/b + partner_a/b) を見て、
       B 側の勝利を反転して数える。
- #528 選手削除は Match 以外の参照 (アカウント等) があれば 500 でなく 409。
- #526 試合削除は DB の commit が通るまで物理動画を消さない。
- #522 スコア補正の擬似ラリー (is_skipped) は勝率・ラリー長に入れない。
- #525 Annotator の「途中終了」が送る result="retired" を受け付ける。
"""
from __future__ import annotations

import uuid
from datetime import date

from backend.db.models import GameSet, Match, Rally, User
from backend.tests.test_stats_n0_guards_b import (  # noqa: F401
    _headers,
    _match,
    _player,
    client,
)


def _doubles(db, result="win"):
    a, pa, b, pb = (_player(db, n) for n in ("A", "Aの相方", "B", "Bの相方"))
    m = _match(db, a, b, date(2026, 9, 1), 3, 5, fmt="doubles", result=result,
               partner_a=pa, partner_b=pb)
    db.commit()
    return a, pa, b, pb, m


def _stats(client, pid):
    r = client.get(f"/api/players/{pid}/stats", headers=_headers())
    assert r.status_code == 200, r.text
    return r.json()["data"]


# ── #527 ───────────────────────────────────────────────────────────────────

def test_stats_count_partner_slots_and_b_side_wins(client, db_session):
    a, pa, b, pb, _m = _doubles(db_session, result="win")
    for p in (a, pa):
        assert _stats(client, p.id) == {"total_matches": 1, "wins": 1, "decided_matches": 1}
    for p in (b, pb):
        assert _stats(client, p.id) == {"total_matches": 1, "wins": 0, "decided_matches": 1}


def test_stats_b_side_wins_when_a_side_lost(client, db_session):
    a, pa, b, pb, _m = _doubles(db_session, result="loss")
    assert _stats(client, a.id)["wins"] == 0
    assert _stats(client, b.id)["wins"] == 1
    assert _stats(client, pb.id)["wins"] == 1


def test_stats_unfinished_is_not_decided(client, db_session):
    a, _pa, b, _pb, _m = _doubles(db_session, result="unfinished")
    for p in (a, b):
        d = _stats(client, p.id)
        assert d["total_matches"] == 1 and d["wins"] == 0 and d["decided_matches"] == 0


def test_matches_list_includes_partner_and_b_side(client, db_session):
    a, pa, b, pb, m = _doubles(db_session)
    for p in (a, pa, b, pb):
        r = client.get(f"/api/players/{p.id}/matches", headers=_headers())
        assert r.status_code == 200, r.text
        assert [row["id"] for row in r.json()["data"]] == [m.id]


# ── #528 ───────────────────────────────────────────────────────────────────

def test_delete_player_with_account_reference_is_409(client, db_session):
    p = _player(db_session, "アカウント付き")
    db_session.add(User(username="player_with_account", role="player", player_id=p.id))
    db_session.commit()
    r = client.delete(f"/api/players/{p.id}", headers=_headers())
    assert r.status_code == 409
    assert "アカウント" in r.json()["detail"]


def test_delete_unreferenced_player_still_works(client, db_session):
    p = _player(db_session, "未参照")
    db_session.commit()
    r = client.delete(f"/api/players/{p.id}", headers=_headers())
    assert r.status_code == 200, r.text


# ── #526 ───────────────────────────────────────────────────────────────────

def _match_with_server_video(db, upload_dir):
    uid = str(uuid.uuid4())
    video = upload_dir / f"{uid}.mp4"
    video.write_bytes(b"x")
    a, b = _player(db, "動画A"), _player(db, "動画B")
    m = _match(db, a, b, date(2026, 9, 2), 1, 2)
    m.video_local_path = f"server://{uid}.mp4"
    db.commit()
    return m, video


def test_delete_match_keeps_video_when_commit_fails(client, db_session, monkeypatch, tmp_path):
    from backend.routers import uploads
    monkeypatch.setattr(uploads, "UPLOAD_DIR", tmp_path)
    m, video = _match_with_server_video(db_session, tmp_path)

    real_commit = db_session.commit

    def boom():
        raise RuntimeError("simulated FK violation")

    monkeypatch.setattr(db_session, "commit", boom)
    r = client.delete(f"/api/matches/{m.id}", headers=_headers())
    monkeypatch.setattr(db_session, "commit", real_commit)
    assert r.status_code == 500
    assert video.exists(), "DB の commit 前に物理動画を消している"
    assert db_session.get(Match, m.id) is not None


def test_delete_match_removes_video_after_commit(client, db_session, monkeypatch, tmp_path):
    from backend.routers import uploads
    monkeypatch.setattr(uploads, "UPLOAD_DIR", tmp_path)
    m, video = _match_with_server_video(db_session, tmp_path)
    r = client.delete(f"/api/matches/{m.id}", headers=_headers())
    assert r.status_code == 200, r.text
    assert not video.exists()


# ── #522 ───────────────────────────────────────────────────────────────────

def _add_skipped(db, match, n):
    gs = db.query(GameSet).filter(GameSet.match_id == match.id).first()
    for i in range(n):
        db.add(Rally(
            set_id=gs.id, rally_num=100 + i, server="player_a", winner="player_a",
            end_type="unknown", rally_length=0, score_a_after=0, score_b_after=0,
            annotation_mode="manual_record", is_skipped=True,
        ))
    db.commit()


def test_descriptive_ignores_score_correction_rallies(client, db_session):
    a = _player(db_session, "補正A")
    b = _player(db_session, "補正B")
    m = _match(db_session, a, b, date(2026, 9, 3), 2, 4)  # 実ラリー 4 本・2 勝
    db_session.commit()
    _add_skipped(db_session, m, 6)  # 補正で自分が勝ったことにされた 6 点
    r = client.get(f"/api/analysis/descriptive?player_id={a.id}", headers=_headers())
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["total_rallies"] == 4
    assert d["win_rate"] == 0.5
    assert d["server_win_rate"]["server_count"] == 4


def test_set_comparison_ignores_score_correction_rallies(client, db_session):
    a = _player(db_session, "補正C")
    b = _player(db_session, "補正D")
    m = _match(db_session, a, b, date(2026, 9, 4), 2, 4)
    db_session.commit()
    _add_skipped(db_session, m, 6)
    r = client.get(f"/api/analysis/set_comparison?player_id={a.id}", headers=_headers())
    assert r.status_code == 200, r.text
    rows = r.json()["data"]
    assert [row["total_rallies"] for row in rows] == [4]
    assert rows[0]["win_rate"] == 0.5


# ── #525 ───────────────────────────────────────────────────────────────────

def test_match_accepts_retired_result(client, db_session):
    a, b = _player(db_session, "途中A"), _player(db_session, "途中B")
    m = _match(db_session, a, b, date(2026, 9, 5), 1, 2)
    db_session.commit()
    r = client.put(
        f"/api/matches/{m.id}",
        json={"result": "retired", "exception_reason": "retired_a", "metadata_status": "partial"},
        headers=_headers(),
    )
    assert r.status_code == 200, r.text
    db_session.refresh(m)
    assert m.result == "retired"


def test_match_still_rejects_unknown_result(client, db_session):
    a, b = _player(db_session, "拒否A"), _player(db_session, "拒否B")
    m = _match(db_session, a, b, date(2026, 9, 6), 1, 2)
    db_session.commit()
    r = client.put(f"/api/matches/{m.id}", json={"result": "bogus"}, headers=_headers())
    assert r.status_code == 422
