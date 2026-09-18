"""役割述語の「素通り」が既定拒否になっていること。

`is_player` / `is_coach` / `is_analyst` / `is_admin` は**すべて role の完全一致**。
したがって `llm` と `demo` はどの述語にも入らない。

いくつもの認可関数が `if is_admin / elif is_coach or is_analyst / # admin は全件`
という形で書かれており、**最後のコメント行に落ちる = 許可**になっていた。
`GET /players` を直したときに同じ形の他を見落としたので、ここで固定する。

ロールを足すたびに黙って広がる形なので、**既定は拒否**でなければならない。
"""
from __future__ import annotations

import pytest

from backend.utils.auth import AuthCtx, filter_by_role, user_can_access_match


class _Match:
    def __init__(self, owner_team_id=None, is_public_pool=False):
        self.owner_team_id = owner_team_id
        self.is_public_pool = is_public_pool
        self.player_a_id = 1
        self.player_b_id = 2
        self.partner_a_id = None
        self.partner_b_id = None


def _ctx(role: str, team_id=None) -> AuthCtx:
    return AuthCtx(role=role, player_id=None, team_name=None, team_id=team_id)


# ── 公開プールの試合 ────────────────────────────────────────────────────────

@pytest.mark.parametrize("role", ["llm", "demo"])
def test_unscoped_roles_cannot_read_public_pool_matches(role):
    """`is_public_pool` は無条件 True を返す枝だった。

    llm / demo がどの述語にも入らずこの枝に落ち、**公開プールの全試合**を
    読めていた。
    """
    assert user_can_access_match(_ctx(role), _Match(is_public_pool=True)) is False


@pytest.mark.parametrize("role", ["coach", "analyst"])
def test_scoped_roles_still_read_public_pool_matches(role):
    """伏せすぎていないこと。本来の利用者は従来どおり読める。"""
    assert user_can_access_match(_ctx(role), _Match(is_public_pool=True)) is True


def test_own_team_match_is_still_readable():
    assert user_can_access_match(_ctx("coach", team_id=3), _Match(owner_team_id=3)) is True


def test_other_team_private_match_is_not_readable():
    assert user_can_access_match(_ctx("coach", team_id=3), _Match(owner_team_id=4)) is False


# ── 出力の伏せ方 ────────────────────────────────────────────────────────────

_SENSITIVE_SAMPLE = {
    "player_name": "X",
    "epv": 0.42,
    "weakness_zones": ["BL"],
    "win_rate_vs_opponent": 0.61,
}


def test_demo_gets_the_same_redaction_as_player():
    """demo は「最小権限・実データ不可」と定義されているのに、

    旧実装は player だけを伏せており、**demo には analyst 相当のキーが
    そのまま出ていた**。
    """
    out = filter_by_role(dict(_SENSITIVE_SAMPLE), "demo")
    assert "epv" not in out
    assert "weakness_zones" not in out
    assert "win_rate_vs_opponent" not in out


def test_player_redaction_unchanged():
    out = filter_by_role(dict(_SENSITIVE_SAMPLE), "player")
    assert "epv" not in out


def test_analyst_still_sees_everything():
    out = filter_by_role(dict(_SENSITIVE_SAMPLE), "analyst")
    assert out["epv"] == 0.42
