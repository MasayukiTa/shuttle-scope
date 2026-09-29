"""公開ステータスページの自動更新が、ログインしていない閲覧者にも効くこと。

`backend/templates/public/status.html.j2` の `poll()` は **60 秒ごとに**
`/api/public/status` を叩き、状態が初期描画時と変わっていればページを
再読み込みする。障害中に開きっぱなしにしている人のための経路。

その `/api/public/status` が `_GLOBAL_AUTH_EXEMPT` に入っておらず
（入っていたのは `/api/public/status/day` だけ）、**未ログインの閲覧者には
401 が返り続けていた**。fetch 側は

    return r.ok ? r.json() : null      ... .catch(function(){})

と書いてあるので、**失敗しても何も起きない**。エラーも出ないまま、
自動更新だけが一度も動いていなかった。

免除を足すのは `/status` と同じ粒度の情報だから: 返すのは
operational / degraded / down の粗い状態と件数だけで、
ページ本体はもともと同じ内容を server-rendered で出している。

`backend.main` を import する (3.11+)。
"""
from __future__ import annotations

import pathlib
import re
import sys

import pytest

_NEEDS_MAIN = pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="backend.main は Python 3.11+ が要る (typing.NotRequired)",
)


@_NEEDS_MAIN
def test_the_status_endpoint_the_page_polls_is_exempt():
    from backend.main import _GLOBAL_AUTH_EXEMPT

    assert _GLOBAL_AUTH_EXEMPT.match("/api/public/status"), (
        "公開ステータスページの poll() が 401 になる"
    )


@_NEEDS_MAIN
def test_the_day_drilldown_stays_exempt():
    from backend.main import _GLOBAL_AUTH_EXEMPT

    assert _GLOBAL_AUTH_EXEMPT.match("/api/public/status/day")
    assert _GLOBAL_AUTH_EXEMPT.match("/api/public/status/day?day=2026-09-22")


@_NEEDS_MAIN
def test_the_exemption_does_not_widen_to_the_admin_side():
    """`public/status` の免除が前方一致に化けていないこと。

    旧 `public(?:/[^?]*)?$` は唯一の前方一致エントリで、admin 専用の
    inquiries 系まで免除していた。同じ轍を踏まない。
    """
    from backend.main import _GLOBAL_AUTH_EXEMPT

    for path in (
        "/api/public/status/secret",
        "/api/public/statuses",
        "/api/public/inquiries",
        "/api/public/inquiries/unread-count",
        "/api/public/status/day/extra",
    ):
        assert not _GLOBAL_AUTH_EXEMPT.match(path), path


def test_every_public_page_banner_uses_that_path_too():
    """`_status_banner.html.j2` は `base.html.j2` から include されている。

    つまり **すべての公開ページ**（トップ / contact / privacy / terms /
    legal / status）が同じ `/api/public/status` を叩いていた。
    401 が返るので `r.ok` が false になり、`d` は null。
    障害中・メンテ中のバナーは **公開の閲覧者に一度も出ていなかった**。
    コメントは「フェイルクローズ」と書いてあるが、たまに失敗するのではなく
    恒久的に失敗していた。
    """
    tpl_dir = pathlib.Path(__file__).resolve().parents[1] / "templates" / "public"
    banner = (tpl_dir / "_status_banner.html.j2").read_text(encoding="utf-8")
    assert re.search(r"fetch\(\s*'/api/public/status'", banner)

    base = (tpl_dir / "base.html.j2").read_text(encoding="utf-8")
    assert "_status_banner.html.j2" in base, (
        "バナーが base から外れている。全公開ページに出る前提が崩れる"
    )


def test_the_page_really_does_poll_that_path():
    """テンプレート側が本当にこのパスを叩いていること。

    免除だけ足して呼び出し側が別パスなら、直したことにならない。
    """
    tpl = (
        pathlib.Path(__file__).resolve().parents[1]
        / "templates" / "public" / "status.html.j2"
    ).read_text(encoding="utf-8")
    assert re.search(r"fetch\(\s*'/api/public/status'", tpl), (
        "status.html.j2 が /api/public/status を poll していない"
    )
    assert "setInterval(poll,60000)" in tpl.replace(" ", ""), (
        "poll の定期実行が消えている"
    )
