"""大分類（9 major）定義のバック↔フロントミラー一致テスト。

簡易入力モード (ShotTypePanel simpleMode / useKeyboard simpleMode) は、
フロントの src/constants/shotMajorCategories.ts と
バックの backend/analysis/shot_taxonomy.py が同じ写像を持つことに依存する。
これがずれると、画面で選んだ大分類がサーバで別の小分類に落ち、
ユーザの意図と保存値が黙って食い違う。その drift をここで止める。

TS は正規の JS/TS パーサを使わず、正規表現でオブジェクトリテラルを
抽出して突き合わせる（ビルド依存を避ける）。
"""
import re
from pathlib import Path

import pytest

from backend.analysis.shot_taxonomy import (
    CANONICAL_SHOTS,
    MAJOR_SHOTS,
    MAJOR_REPRESENTATIVE,
    MAJOR_OF_CANONICAL,
    major_of,
    representative_of,
)

TS_PATH = (
    Path(__file__).resolve().parents[2]
    / "src" / "constants" / "shotMajorCategories.ts"
)


def _extract_block(src: str, marker: str, open_ch: str = "{", close_ch: str = "}") -> str:
    """`marker` の直後の open_ch ... close_ch ブロック本文を返す。

    MAJOR_SHOTS は配列リテラル ([ ... ]) なので open_ch='[' を渡すこと。
    Record リテラル ({ ... }) は既定の { } で良い。
    """
    i = src.index(marker)
    start = src.index(open_ch, i)
    depth = 0
    for j in range(start, len(src)):
        if src[j] == open_ch:
            depth += 1
        elif src[j] == close_ch:
            depth -= 1
            if depth == 0:
                return src[start + 1 : j]
    raise AssertionError(f"unbalanced {open_ch}{close_ch} after {marker!r}")


def _parse_record(block: str) -> dict:
    """'key: value' の単純な Record リテラルを dict 化。値は '...' も bare も可。"""
    out = {}
    for m in re.finditer(r"['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?\s*:\s*'([A-Za-z_]+)'", block):
        out[m.group(1)] = m.group(2)
    return out


def _parse_string_array(block: str) -> list:
    return re.findall(r"'([A-Za-z_]+)'", block)


@pytest.fixture(scope="module")
def ts_src() -> str:
    assert TS_PATH.exists(), f"TS mirror not found: {TS_PATH}"
    return TS_PATH.read_text(encoding="utf-8")


def test_ts_major_shots_match_backend(ts_src):
    block = _extract_block(ts_src, "export const MAJOR_SHOTS", "[", "]")
    ts_majors = _parse_string_array(block)
    assert ts_majors == list(MAJOR_SHOTS), (ts_majors, list(MAJOR_SHOTS))


def test_ts_representative_match_backend(ts_src):
    block = _extract_block(ts_src, "export const MAJOR_REPRESENTATIVE")
    ts_rep = _parse_record(block)
    assert ts_rep == dict(MAJOR_REPRESENTATIVE), (ts_rep, dict(MAJOR_REPRESENTATIVE))


def test_ts_major_of_canonical_match_backend(ts_src):
    block = _extract_block(ts_src, "export const MAJOR_OF_CANONICAL")
    ts_map = _parse_record(block)
    assert ts_map == dict(MAJOR_OF_CANONICAL), (
        set(ts_map.items()) ^ set(dict(MAJOR_OF_CANONICAL).items())
    )


def test_backend_major_of_canonical_covers_all_canonical():
    assert set(MAJOR_OF_CANONICAL.keys()) == set(CANONICAL_SHOTS)
    assert all(v in MAJOR_SHOTS for v in MAJOR_OF_CANONICAL.values())


def test_backend_representative_round_trips():
    for m in MAJOR_SHOTS:
        assert major_of(representative_of(m)) == m
        assert representative_of(m) in CANONICAL_SHOTS


def test_backend_major_of_unknown_is_other():
    assert major_of("nonexistent_shot") == "other"


def test_nine_majors():
    assert len(MAJOR_SHOTS) == 9
    assert len(set(MAJOR_SHOTS)) == 9


# ── 派生細分類 derive_fine_label（保存しない解析時導出）────────────────────────

def test_derive_fine_label_rear_smash_from_back_zone():
    from backend.analysis.shot_taxonomy import derive_fine_label
    for zone in ("BL", "BC", "BR"):
        assert derive_fine_label("smash", zone, "above_net") == "rear_smash"
        assert derive_fine_label("smash", zone, "below") == "rear_smash"


def test_derive_fine_label_frontal_smash_from_front_high():
    from backend.analysis.shot_taxonomy import derive_fine_label
    for zone in ("NL", "NC", "NR", "ML", "MC", "MR"):
        assert derive_fine_label("smash", zone, "above_net") == "frontal_smash"
        assert derive_fine_label("smash", zone, "slightly_above") == "frontal_smash"


def test_derive_fine_label_front_low_is_generic_smash():
    from backend.analysis.shot_taxonomy import derive_fine_label
    # ネット前〜ミッドでも打点が低ければフロントスマッシュとは呼ばない。
    for zone in ("NC", "MC"):
        assert derive_fine_label("smash", zone, "slightly_below") == "smash"
        assert derive_fine_label("smash", zone, "below") == "smash"


def test_derive_fine_label_missing_zone_or_height_is_generic_smash():
    from backend.analysis.shot_taxonomy import derive_fine_label
    assert derive_fine_label("smash", None, None) == "smash"
    assert derive_fine_label("smash", "", "") == "smash"
    assert derive_fine_label("smash", "ZZ", "above_net") == "smash"


def test_derive_fine_label_case_insensitive():
    from backend.analysis.shot_taxonomy import derive_fine_label
    assert derive_fine_label("SMASH", "nc", "ABOVE_NET") == "frontal_smash"
    assert derive_fine_label(" smash ", "bc", "below") == "rear_smash"


def test_derive_fine_label_non_smash_majors_pass_through():
    from backend.analysis.shot_taxonomy import derive_fine_label
    for m in MAJOR_SHOTS:
        if m == "smash":
            continue
        # 攻撃系以外は細分化せず大分類をそのまま返す（ゾーン/高さは無視）。
        assert derive_fine_label(m, "NC", "above_net") == m
        assert derive_fine_label(m, None, None) == m


def test_derive_fine_label_unknown_major_is_other():
    from backend.analysis.shot_taxonomy import derive_fine_label
    assert derive_fine_label("nonexistent_major", "NC", "above_net") == "other"


def test_derive_fine_label_does_not_add_canonical_or_shottype():
    # 派生ラベルは ShotType/canonical を増やさないことの明示（保存しない契約）。
    from backend.analysis.shot_taxonomy import derive_fine_label
    assert "frontal_smash" not in CANONICAL_SHOTS
    assert "rear_smash" not in CANONICAL_SHOTS
    # smash major の代表保存値は従来どおり canonical "smash"。
    assert representative_of("smash") == "smash"
    assert derive_fine_label("smash", "BC", "below") not in CANONICAL_SHOTS
