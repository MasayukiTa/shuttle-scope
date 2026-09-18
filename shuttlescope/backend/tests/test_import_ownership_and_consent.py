"""インポートの所有権ガードと、墓石の蘇生防止。

背景:
  `_apply_record` の所有権検査は `hasattr(obj, "owner_team_id")` だけを見ていた。
  **この列を持つのは Match だけ**で、Player / Comment は `team_id`、
  GameSet / Rally / Stroke は**チーム列を持たない**。結果、uuid を知っていれば
  他チームの選手・ラリー・打球を上書き / 論理削除できた。

  同じリポジトリの `routers/sync.py` の conflict 解決は
  `owner_team_id → team_id → それも無ければ拒否` という正しい梯子を実装済みで、
  **こちらだけが追随していなかった**。

  併せて、発信元で論理削除された行が「こちらでは未知」のときに
  `deleted_at` を strip して生きた行として作り直していた (墓石の蘇生)。

ここでは判定関数そのものを直接突く。パッケージを組み立てる経路の
テストは別途必要だが、境界の判定はここで固定できる。
"""
from __future__ import annotations

from datetime import datetime, timedelta

from backend.services.import_package import _may_write
from backend.services.merge_resolver import decide_merge


class _Obj:
    """所有列の有無だけを模した最小のスタブ。"""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


# ── 所有権 ─────────────────────────────────────────────────────────────────

def test_own_team_match_is_writable():
    assert _may_write(_Obj(owner_team_id=1), 1) is True


def test_other_team_match_is_not_writable():
    assert _may_write(_Obj(owner_team_id=2), 1) is False


def test_player_is_guarded_by_team_id_not_owner_team_id():
    """**これが漏れていた。** Player は owner_team_id を持たない。"""
    assert _may_write(_Obj(team_id=2), 1) is False
    assert _may_write(_Obj(team_id=1), 1) is True


def test_a_record_with_no_team_column_is_refused():
    """Rally / Stroke / GameSet はチーム列を持たない。

    これらは親 (Match) の所有で守られるべきもので、uuid を知っているだけの
    相手に個別に書き換えさせる理由が無い。fail-closed。
    """
    assert _may_write(_Obj(rally_id=5, stroke_num=1), 1) is False


def test_orphan_record_with_null_team_is_refused():
    """所有者不明の legacy 行を、uuid を知っているだけで取れないこと。"""
    assert _may_write(_Obj(owner_team_id=None), 1) is False
    assert _may_write(_Obj(team_id=None), 1) is False


def test_teamless_importer_cannot_write_anything():
    assert _may_write(_Obj(owner_team_id=1), None) is False
    assert _may_write(_Obj(team_id=1), None) is False


# ── 未来日時の削除 ──────────────────────────────────────────────────────────

def _rec(**kw) -> dict:
    base = {"uuid": "u-1"}
    base.update(kw)
    return base


def test_a_future_dated_deletion_cannot_beat_a_recent_local_edit():
    """`deleted_at: 9999-12-31` で他チームを一括墓石化できないこと。

    クランプは `_sanitize_import_record` にしか無く、しかも判定より後に走る
    ため、`>=` 比較で削除側が常に勝っていた。
    """
    now = datetime.utcnow()
    decision = decide_merge(
        table="matches",
        incoming=_rec(deleted_at="9999-12-31T00:00:00"),
        local={"id": 7, "updated_at": (now - timedelta(minutes=1)).isoformat()},
    )
    assert decision.action == "keep", (
        f"未来日時の削除が勝っている: {decision.action} / {decision.reason}"
    )


def test_a_genuine_older_deletion_still_wins_over_a_stale_local_row():
    """伏せすぎていないこと。正当な削除は従来どおり伝播する。"""
    now = datetime.utcnow()
    decision = decide_merge(
        table="matches",
        incoming=_rec(deleted_at=(now - timedelta(minutes=1)).isoformat()),
        local={"id": 7, "updated_at": (now - timedelta(hours=2)).isoformat()},
    )
    assert decision.action == "delete"
