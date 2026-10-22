"""名前の不可視・双方向制御文字 (監査 #10)。値はすべて架空。

- 共通の検証関数は、列挙漏れのあった不可視文字 (Cf カテゴリ・ハングルフィラー等) も拒否する。
- 検証を入れる前に保存された名前は、応答で取り除いて返す (保存値は書き換えない)。
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend.tests.test_stats_n0_guards_b import _headers, _player, client  # noqa: F401
from backend.utils.text_sanitize import (
    reject_bidi_only,
    reject_ctrl_and_bidi,
    strip_invisible_format_chars,
)

# 従来の列挙には無かった文字 (Cf: 不可視の数式演算子・廃止済み書式・言語タグ、フィラー)
EXTRA_HIDDEN = ["⁡", "⁤", "⁪", "ㅤ", "ᅟ", "͏", "\U000e0041"]


@pytest.mark.parametrize("ch", EXTRA_HIDDEN)
def test_validators_reject_characters_missing_from_the_old_list(ch):
    with pytest.raises(HTTPException) as e1:
        reject_ctrl_and_bidi(f"Taro{ch}Yamada", "name", max_len=100)
    assert e1.value.status_code == 422
    with pytest.raises(HTTPException) as e2:
        reject_bidi_only(f"Taro{ch}Yamada", "notes", max_len=100)
    assert e2.value.status_code == 422


@pytest.mark.parametrize("name", ["山田太郎", "Taro Yamada", "O'Brien-Smith", "テスト 1"])
def test_normal_names_still_pass(name):
    assert reject_ctrl_and_bidi(name, "name", max_len=100) == name


def test_strip_removes_hidden_chars_and_normalizes():
    assert strip_invisible_format_chars("Taro​Yama‮da") == "TaroYamada"
    assert strip_invisible_format_chars("TaroㅤYamada") == "TaroYamada"
    assert strip_invisible_format_chars(None) is None
    # NFD (濁点が分離) は NFC にそろえる
    assert strip_invisible_format_chars("ガ") == "ガ"
    assert strip_invisible_format_chars("山田 太郎") == "山田 太郎"


def test_player_list_hides_legacy_hidden_chars_without_rewriting_storage(client, db_session):
    p = _player(db_session, "Legacy​Name‮")
    db_session.commit()
    r = client.get("/api/players", headers=_headers())
    assert r.status_code == 200, r.text
    names = [row["name"] for row in r.json()["data"]]
    assert "LegacyName" in names
    assert all("​" not in n and "‮" not in n for n in names)
    db_session.refresh(p)
    assert p.name == "Legacy​Name‮"  # 保存値はそのまま
