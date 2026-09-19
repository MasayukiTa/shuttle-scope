"""ゾーン語彙がフロントとバックで一致していること。

`backend/utils/validators.py` の許可リストと `src/types/index.ts` の
`Zone9` / `ZoneOOB` / `ZoneNet` は同じものを二度書いている。片方だけ足すと:

  - TS に足してバックに足さない → 新しいマスを押した入力が 400 で弾かれる
  - バックに足して TS に足さない → 誰も押せない値が «通る» ことになる

どちらも気づきにくいので、**TS のソースを読んで突き合わせる**。
綴りを人が写し直すたびに間違える類のものなので、目視での一致確認はしない。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from backend.utils.validators import (
    COURT_ZONES,
    NET_ZONES,
    OOB_ZONES,
    VALID_HIT_ZONES,
    VALID_LAND_ZONES,
    validate_stroke,
)

_TYPES_TS = Path(__file__).resolve().parents[2] / "src" / "types" / "index.ts"


def _union_members(source: str, type_name: str) -> set[str]:
    """`export type X = 'a' | 'b' | ...` の右辺から文字列リテラルを集める。

    次の `export` までを本体とみなす。コメント中の引用符は拾わないよう、
    行コメント (`//`) とブロックコメントを先に落とす。
    """
    start = source.index(f"export type {type_name} =")
    rest = source[start + len(f"export type {type_name} ="):]
    end = rest.find("export ")
    body = rest if end == -1 else rest[:end]
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
    body = re.sub(r"//[^\n]*", "", body)
    return set(re.findall(r"'([^']+)'", body))


@pytest.fixture(scope="module")
def ts_source() -> str:
    assert _TYPES_TS.is_file(), f"{_TYPES_TS} が見つからない"
    return _TYPES_TS.read_text(encoding="utf-8")


class TestTheTwoDefinitionsMatch:
    def test_court_zones(self, ts_source):
        assert COURT_ZONES == _union_members(ts_source, "Zone9")

    def test_out_of_bounds_zones(self, ts_source):
        assert OOB_ZONES == _union_members(ts_source, "ZoneOOB")

    def test_net_zones(self, ts_source):
        assert NET_ZONES == _union_members(ts_source, "ZoneNet")

    def test_the_parser_actually_found_something(self, ts_source):
        """空集合どうしの一致で «通った» ことにしない。"""
        assert len(_union_members(ts_source, "Zone9")) == 9
        assert len(_union_members(ts_source, "ZoneOOB")) >= 10
        assert len(_union_members(ts_source, "ZoneNet")) == 3


class TestTheZoneIsChecked:
    def test_a_known_landing_zone_passes(self):
        ok, msg = validate_stroke({"shot_type": "clear", "land_zone": "BL", "stroke_num": 2})
        assert ok, msg

    def test_an_out_of_bounds_landing_zone_passes(self):
        ok, msg = validate_stroke({"shot_type": "clear", "land_zone": "OB_BC", "stroke_num": 2})
        assert ok, msg

    @pytest.mark.parametrize("zone", ["XX", "bl", "NET", "OB_LB", "A_front_left", ""])
    def test_an_unknown_landing_zone_is_refused(self, zone):
        """`NET` / `OB_LB` は実際にバックエンド側のコードに書かれていた綴りで、
        TS 側には存在しない。小文字も別物として扱う (集計キーがぶれる)。"""
        ok, msg = validate_stroke({"shot_type": "clear", "land_zone": zone, "stroke_num": 2})
        assert not ok
        assert zone in (msg or "") or zone == ""

    def test_no_landing_zone_is_still_allowed(self):
        ok, msg = validate_stroke({"shot_type": "clear", "land_zone": None, "stroke_num": 2})
        assert ok, msg

    def test_the_hit_zone_must_be_inside_the_court(self):
        """打点は «打った位置» なのでコート外にはならない。"""
        ok, _ = validate_stroke({"shot_type": "clear", "hit_zone": "MC", "stroke_num": 2})
        assert ok
        ok, msg = validate_stroke({"shot_type": "clear", "hit_zone": "OB_BC", "stroke_num": 2})
        assert not ok
        assert "OB_BC" in (msg or "")

    def test_hit_zones_are_a_subset_of_landing_zones(self):
        assert VALID_HIT_ZONES <= VALID_LAND_ZONES
