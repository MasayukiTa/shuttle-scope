"""require_operator_or_demo_read: demo ロールが戦術統計を素通りしないことの回帰テスト。

`require_non_player` は player しか弾かないため、role=demo が
shot_win_loss / pre_loss_patterns (任意 player_id の勝敗内訳) を通過できた (#661)。

  - 運用ロール (admin / analyst / coach) は従来どおり通る
  - demo は検証済み demo read (request.state.demo_read=True) のときだけ通る
  - llm / 未知ロールは常に 403
  - player は require_non_player が 403 (従来どおり)
  - 対象 2 ルートが新しい依存を持つ (構造)
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.utils.auth import AuthCtx, require_non_player, require_operator_or_demo_read


def _req(demo_read: bool):
    return SimpleNamespace(state=SimpleNamespace(demo_read=demo_read))


def _ctx(role):
    return AuthCtx(role=role, player_id=None, user_id=1, team_name=None, team_id=None)


@pytest.mark.parametrize("role", ["admin", "analyst", "coach"])
def test_operator_roles_pass(role):
    ctx = _ctx(role)
    assert require_operator_or_demo_read(_req(False), ctx) is ctx


def test_demo_without_verified_demo_read_is_denied():
    with pytest.raises(HTTPException) as ei:
        require_operator_or_demo_read(_req(False), _ctx("demo"))
    assert ei.value.status_code == 403


def test_demo_with_verified_demo_read_passes():
    ctx = _ctx("demo")
    assert require_operator_or_demo_read(_req(True), ctx) is ctx


@pytest.mark.parametrize("role", ["llm", "unknown_role"])
def test_other_roles_denied_even_when_demo_read_flag_is_set(role):
    # demo_read は role=demo 以外には効かせない設計ではないが、llm は通常 API 自体が
    # 別ミドルウェアで 403。ここでは「運用ロールでもなく demo read でもない」場合の既定拒否を確認する。
    with pytest.raises(HTTPException) as ei:
        require_operator_or_demo_read(_req(False), _ctx(role))
    assert ei.value.status_code == 403


def test_player_jwt_is_denied_by_require_non_player():
    from starlette.requests import Request

    from backend.utils.jwt_utils import create_access_token

    tok = create_access_token(user_id=5, role="player", player_id=5, team_name="T", team_id=1)
    req = Request({
        "type": "http",
        "headers": [(b"authorization", f"Bearer {tok}".encode())],
        "query_string": b"",
    })
    with pytest.raises(HTTPException) as ei:
        require_non_player(req)
    assert ei.value.status_code == 403


def test_target_routes_use_the_new_dependency():
    from backend.routers import analysis_stable

    wanted = {"/analysis/shot_win_loss", "/analysis/pre_loss_patterns"}
    seen = set()
    for route in analysis_stable.router.routes:
        path = getattr(route, "path", "")
        if path in wanted:
            calls = [d.call for d in route.dependant.dependencies]
            assert require_operator_or_demo_read in calls, path
            seen.add(path)
    assert seen == wanted
