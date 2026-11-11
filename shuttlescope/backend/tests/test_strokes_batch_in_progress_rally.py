"""fix/in-progress-rally-not-final: /api/strokes/batch の途中保存 (final=false) で作られた
未確定ラリーが、確定ラリーのように扱われないことを検証する。

背景: 途中保存 (final=false, end_type=in_progress, winner=仮の player_a) で作られた
ラリーが、確定ラリーと同じように共有セッションへブロードキャストされ、得点・解析の
集計にも数えられていた。これにより観戦ビューに未確定ラリーが流れ、勝率などの指標が
仮値で汚れていた。

検証ケース:
  - final=false の新規作成では rally_saved を共有セッションへブロードキャストしない
  - final=false で作られたラリーは end_type=in_progress で保存され、
    active_rally_predicates / rally_counts_by_match の集計から除外される
  - final=true の確定送信が同じ (set_id, rally_num) に来たら winner / end_type / score を
    確定内容で必ず上書きする (打球本数が同じでも上書きされる)
  - final=true の確定後はブロードキャストされ、集計にも数えられる
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.analysis.analysis_population import (
    IN_PROGRESS_END_TYPE,
    active_rally_predicates,
    rally_counts_by_match,
)
from backend.db.database import get_db
from backend.db.models import GameSet, Match, Player, Rally, SharedSession, User
from backend.main import app
from backend.utils.jwt_utils import create_access_token


@pytest.fixture()
def game_set(db_session) -> GameSet:
    a = Player(name="inprog A", dominant_hand="R")
    b = Player(name="inprog B", dominant_hand="R")
    db_session.add_all([a, b])
    db_session.flush()
    m = Match(
        tournament="inprog test", tournament_level="practice", round="R1",
        date=date(2026, 11, 1), format="singles",
        player_a_id=a.id, player_b_id=b.id, result="unknown",
    )
    db_session.add(m)
    db_session.flush()
    gs = GameSet(match_id=m.id, set_num=1)
    db_session.add(gs)
    db_session.flush()
    db_session.commit()
    return gs


@pytest.fixture()
def client(db_session, game_set):
    app.dependency_overrides[get_db] = lambda: db_session
    match = db_session.get(Match, game_set.match_id)
    assert match is not None
    user = User(
        username=f"inprog-player-{match.player_a_id}",
        role="player",
        player_id=match.player_a_id,
        awaiting_admin_approval=False,
        consent_required=False,
        is_test=True,
    )
    db_session.add(user)
    db_session.commit()
    token = create_access_token(
        user_id=user.id,
        role="player",
        player_id=match.player_a_id,
        minutes=10,
    )
    c = TestClient(
        app,
        base_url="http://localhost",
        headers={"Authorization": f"Bearer {token}"},
    )
    yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def broadcast_spy(monkeypatch):
    """_broadcast_rally_saved の呼び出しを記録する。実際の WS 送信/ループ依存を避ける。

    実装の _broadcast_rally_saved は asyncio.get_event_loop().is_running() が True の
    ときだけ manager.broadcast を ensure_future する。TestClient の同期経路では
    ループが running でないため、下流の broadcast をスパイしても呼ばれない。
    検証したいのは「確定 (final=true) 時だけブロードキャスト経路に入り、途中保存
    (final=false) では入らない」という分岐なので、経路の入口である
    _broadcast_rally_saved 自体をスパイする。呼ばれた (match_id, rally の確定項目) を
    記録する。
    """
    calls: list[dict] = []

    from backend.routers import strokes as strokes_mod

    orig = strokes_mod._broadcast_rally_saved

    def _spy(db, match_id, rally):  # noqa: ANN001
        calls.append(
            {
                "match_id": match_id,
                "winner": rally.winner,
                "end_type": rally.end_type,
                "score_a": rally.score_a_after,
                "score_b": rally.score_b_after,
            }
        )
        return orig(db, match_id, rally)

    monkeypatch.setattr(strokes_mod, "_broadcast_rally_saved", _spy)
    return calls


def _stroke(n: int) -> dict:
    return {
        "stroke_num": n,
        "player": "player_a" if n % 2 == 1 else "player_b",
        "shot_type": "clear",
        "source_method": "manual",
    }


def _body(
    set_id: int,
    count: int,
    *,
    final: bool,
    winner: str = "player_a",
    end_type: str = IN_PROGRESS_END_TYPE,
    score_a_after: int = 0,
    score_b_after: int = 0,
    rally_num: int = 1,
    replace: bool = False,
) -> dict:
    rally = {
        "set_id": set_id,
        "rally_num": rally_num,
        "server": "player_a",
        "winner": winner,
        "end_type": end_type,
        "rally_length": count,
        "score_a_after": score_a_after,
        "score_b_after": score_b_after,
        "is_deuce": False,
        "annotation_mode": "manual_record",
    }
    return {
        "rally": rally,
        "strokes": [_stroke(i) for i in range(1, count + 1)],
        "replace_strokes": replace,
        "final": final,
    }


def _with_active_session(db_session, match_id: int) -> str:
    """ブロードキャスト先となるアクティブな共有セッションを 1 本作る。

    session_code は String(10) 制約があるので 10 文字以内の固定コードにする。
    """
    code = "INPRG1"
    sess = SharedSession(
        session_code=code,
        match_id=match_id,
        is_active=True,
    )
    db_session.add(sess)
    db_session.commit()
    return code


def _rally(db_session, game_set) -> Rally:
    r = (
        db_session.query(Rally)
        .filter(Rally.set_id == game_set.id, Rally.rally_num == 1)
        .first()
    )
    assert r is not None
    db_session.expire(r)
    return db_session.get(Rally, r.id)


def test_in_progress_new_rally_is_not_broadcast(
    client, db_session, game_set, broadcast_spy
):
    _with_active_session(db_session, game_set.match_id)

    r = client.post(
        "/api/strokes/batch",
        json=_body(game_set.id, 3, final=False),
    )
    assert r.status_code in (200, 201), r.text

    # 途中保存ラリーは end_type=in_progress で保存される
    rally = _rally(db_session, game_set)
    assert rally.end_type == IN_PROGRESS_END_TYPE

    # 未確定ラリーは共有セッションへブロードキャストしない
    assert broadcast_spy == []


def test_in_progress_rally_excluded_from_counts(client, db_session, game_set):
    r = client.post(
        "/api/strokes/batch",
        json=_body(game_set.id, 3, final=False),
    )
    assert r.status_code in (200, 201), r.text

    rally = _rally(db_session, game_set)
    assert rally.end_type == IN_PROGRESS_END_TYPE

    # active_rally_predicates は in_progress を引かない
    active = (
        db_session.query(Rally)
        .filter(Rally.set_id == game_set.id, *active_rally_predicates())
        .all()
    )
    assert rally.id not in {x.id for x in active}

    # rally_counts_by_match も in_progress を数えない
    counts = rally_counts_by_match(db_session, [game_set.match_id])
    assert counts.get(game_set.match_id, 0) == 0


def test_final_overwrites_winner_end_type_score_same_stroke_count(
    client, db_session, game_set, broadcast_spy
):
    _with_active_session(db_session, game_set.match_id)

    # 途中保存 3 本 (winner=仮 player_a, end_type=in_progress, score 0-0)
    r1 = client.post(
        "/api/strokes/batch",
        json=_body(game_set.id, 3, final=False),
    )
    assert r1.status_code in (200, 201), r1.text
    rally_id = _rally(db_session, game_set).id
    assert broadcast_spy == []

    # 同じ本数 (3) のまま final=true の確定送信。winner / end_type / score を確定内容へ。
    r2 = client.post(
        "/api/strokes/batch",
        json=_body(
            game_set.id, 3, final=True,
            winner="player_b", end_type="winner",
            score_a_after=0, score_b_after=1,
        ),
    )
    assert r2.status_code in (200, 201), r2.text
    assert r2.json()["data"]["rally_id"] == rally_id

    db_session.expire_all()
    rally = db_session.get(Rally, rally_id)
    # 本数が同じでも確定内容で必ず上書きされる
    assert rally.winner == "player_b"
    assert rally.end_type == "winner"
    assert rally.score_a_after == 0
    assert rally.score_b_after == 1
    assert rally.end_type != IN_PROGRESS_END_TYPE

    # 確定後は集計に数えられる
    counts = rally_counts_by_match(db_session, [game_set.match_id])
    assert counts.get(game_set.match_id, 0) == 1

    # 確定時にはブロードキャスト経路に入る (途中保存では入っていない)
    assert len(broadcast_spy) >= 1
    last = broadcast_spy[-1]
    assert last["match_id"] == game_set.match_id
    assert last["winner"] == "player_b"
    assert last["end_type"] == "winner"
    assert last["score_b"] == 1
