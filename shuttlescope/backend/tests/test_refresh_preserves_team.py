"""S-11: refresh で発行し直す access token が team_id を落とさないことのテスト。

`routers/auth.py` の refresh だけが `team_id=` を渡し忘れており、他の 7 箇所は
渡していた。access token は 15 分なので、**ログインから 15 分後に coach /
analyst の team_id が消える**。team_id を見る認可
(`user_can_access_match` の owner_team_id 判定、スカウティング選手の可視判定)
が、その時点から静かに別の答えを返し始める。

トークンの中身だけを見る。`backend.main` を import しないので 3.10 でも走る。
"""
from __future__ import annotations

import pytest

from backend.utils.jwt_utils import create_access_token, verify_token


CLAIMS = [
    ("sub", 42),
    ("role", "coach"),
    ("team_id", 7),
]


@pytest.fixture()
def full_token() -> str:
    """ログイン経路が発行するのと同じ形。"""
    return create_access_token(42, "coach", 5, team_name="チームA", team_id=7)


def test_login_shaped_token_carries_team_id(full_token):
    payload = verify_token(full_token)
    assert payload is not None
    assert payload.get("team_id") == 7


def test_every_real_user_token_call_site_passes_team_id():
    """`create_access_token` を **user.role で呼んでいる全箇所**が team_id を渡すこと。

    この欠陥は「8 箇所のうち 1 箇所だけ kwarg が抜けている」という形をしている。
    トークンを 2 本作って比べても、同じ引数で作る以上いつも一致してしまい
    何も検出しない (それは実装を実装で確かめているだけ)。
    検出すべきは呼び出し側の食い違いなので、呼び出し箇所そのものを走査する。

    mfa_pending / 匿名ロールなど、user を伴わない発行は対象外。
    """
    import ast
    import pathlib

    src_path = pathlib.Path(__file__).resolve().parents[1] / "routers" / "auth.py"
    tree = ast.parse(src_path.read_text(encoding="utf-8"))

    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Name) and fn.id == "create_access_token"):
            continue
        # user.role を渡している = 実ユーザ向けの発行
        passes_user_role = any(
            isinstance(a, ast.Attribute) and a.attr == "role"
            and isinstance(a.value, ast.Name) and a.value.id == "user"
            for a in node.args
        )
        if not passes_user_role:
            continue
        kwargs = {k.arg for k in node.keywords}
        if "team_id" not in kwargs:
            offenders.append(node.lineno)

    assert not offenders, (
        "create_access_token を user.role で呼んでいるのに team_id を渡していない箇所がある: "
        f"auth.py 行 {offenders}。access token は 15 分なので、"
        "ここが抜けると 15 分後に coach / analyst の team_id が静かに消える。"
    )


def test_omitting_team_id_is_visible_in_the_token():
    """渡し忘れると本当に落ちることを示す (この欠陥の再現)。"""
    without = verify_token(create_access_token(42, "coach", 5, team_name="チームA"))
    assert without is not None
    assert without.get("team_id") is None
