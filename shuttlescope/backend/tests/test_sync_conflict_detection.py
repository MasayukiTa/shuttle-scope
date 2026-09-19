"""X-5: 競合検出が構造上一度も発火しなかった件。

`merge_resolver.decide_merge` の競合枝は

    if delta <= CONFLICT_WINDOW_SEC and inc_hash and loc_hash and inc_hash != loc_hash:

と、**両側の content_hash を要求する**。ところが中核 5 テーブル
(matches / players / rallies / sets / strokes) のルータは `touch()` は呼ぶが
`touch_sync_metadata()` を 1 箇所も呼んでおらず、`content_hash` は NULL の
ままだった。実測（`git ls-files` 範囲）:

    router                                  touch(   touch_sync_metadata(
    matches / players / rallies / sets / strokes   各2            各0

結果、2 端末が同じラリーを同時に編集しても `SyncConflict` は 1 行も出ず、
無言の last-writer-wins になる。`revision` は誰も読まないので、
「ベクタークロックがある」という誤った安心だけが残っていた。

修正は `touch()` 自身に content_hash を持たせる形にした。10 箇所すべてが
業務列を設定し終えたあとに `touch()` を呼んでいるので、呼び出し側の変更は要らない。
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from backend.db.models import GameSet, Match, Player, Rally, Stroke
from backend.services.merge_resolver import CONFLICT_WINDOW_SEC, decide_merge
from backend.utils.sync_meta import business_payload, compute_content_hash, touch


class TestTouchFillsContentHash:
    """中核 5 テーブルすべてで content_hash が入ること。"""

    @pytest.mark.parametrize("factory", [
        lambda: Player(name="ハッシュ選手", dominant_hand="R"),
        lambda: Match(tournament="ハッシュ大会", format="singles", result="unknown"),
        lambda: GameSet(set_num=1, score_a=0, score_b=0),
        lambda: Rally(rally_num=1, score_a_before=0, score_b_before=0,
                      score_a_after=1, score_b_after=0),
        lambda: Stroke(stroke_num=1, shot_type="clear"),
    ])
    def test_content_hash_is_set(self, factory):
        obj = factory()
        assert getattr(obj, "content_hash", None) is None
        touch(obj)
        assert obj.content_hash, f"{type(obj).__name__} の content_hash が入っていない"
        assert len(obj.content_hash) == 64  # sha256 hex


class TestTheHashDescribesTheRowNotTheRequest:
    def test_changing_a_business_field_changes_the_hash(self):
        a = Stroke(stroke_num=1, shot_type="clear")
        touch(a)
        first = a.content_hash
        a.shot_type = "smash"
        touch(a)
        assert a.content_hash != first

    def test_the_sync_metadata_itself_is_not_hashed(self):
        """updated_at / revision が違うだけの 2 行は同じハッシュになること。

        ここが違うと、内容が同じ行でも必ず不一致になり、
        近接タイムスタンプの更新が**すべて**競合に化ける。
        """
        a = Stroke(stroke_num=1, shot_type="clear")
        b = Stroke(stroke_num=1, shot_type="clear")
        touch(a)
        touch(b)
        b.revision = 99
        b.updated_at = datetime(2020, 1, 1)
        b.source_device_id = "another-device"
        assert compute_content_hash(business_payload(a)) == compute_content_hash(business_payload(b))

    def test_local_ids_are_not_hashed(self):
        """端末ごとに違う採番が混ざらないこと。"""
        a = Stroke(stroke_num=1, shot_type="clear")
        b = Stroke(stroke_num=1, shot_type="clear")
        a.id, a.rally_id = 1, 10
        b.id, b.rally_id = 777, 4242
        assert compute_content_hash(business_payload(a)) == compute_content_hash(business_payload(b))


class TestTheConflictBranchNowFires:
    """decide_merge が実際に conflict を返すこと。

    修正前はこのクラス全体が落ちる（content_hash が None なので
    `inc_hash and loc_hash` が False になり、必ず update か keep になる）。
    """

    def _pair(self, local_shot: str, incoming_shot: str):
        now = datetime(2026, 9, 19, 12, 0, 0)
        local = Stroke(stroke_num=1, shot_type=local_shot)
        touch(local)
        incoming = Stroke(stroke_num=1, shot_type=incoming_shot)
        touch(incoming)
        return (
            {
                "uuid": "same-uuid",
                "updated_at": (now + timedelta(seconds=1)).isoformat(),
                "content_hash": incoming.content_hash,
                "shot_type": incoming_shot,
            },
            {
                "id": 1,
                "uuid": "same-uuid",
                "updated_at": now.isoformat(),
                "content_hash": local.content_hash,
                "shot_type": local_shot,
            },
        )

    def test_two_devices_editing_the_same_stroke_differently_is_a_conflict(self):
        incoming, local = self._pair("clear", "smash")
        decision = decide_merge("strokes", incoming, local)
        assert decision.action == "conflict", decision.reason

    def test_the_same_edit_on_both_devices_is_not_a_conflict(self):
        """内容が同じなら競合にしない（誤検出を出さない）。"""
        incoming, local = self._pair("smash", "smash")
        decision = decide_merge("strokes", incoming, local)
        assert decision.action != "conflict", decision.reason

    def test_edits_far_apart_in_time_are_not_a_conflict(self):
        incoming, local = self._pair("clear", "smash")
        far = datetime(2026, 9, 19, 12, 0, 0) + timedelta(seconds=CONFLICT_WINDOW_SEC + 60)
        incoming["updated_at"] = far.isoformat()
        decision = decide_merge("strokes", incoming, local)
        assert decision.action == "update", decision.reason

    def test_a_missing_hash_still_falls_back_to_last_writer_wins(self):
        """旧データ（hash なし）を壊さないこと。"""
        incoming, local = self._pair("clear", "smash")
        local["content_hash"] = None
        decision = decide_merge("strokes", incoming, local)
        assert decision.action == "update"
