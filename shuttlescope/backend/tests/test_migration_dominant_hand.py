"""dominant_hand nullable 化の検証テスト

migration 0001 が適用された結果:
- dominant_hand = None (NULL) でプレイヤー作成が成功する
- dominant_hand = None で保存・取得できる
- dominant_hand に 10 文字まで入れられる
"""
import pytest
from datetime import date

from backend.db.models import Player, Match


class TestDominantHandNullable:
    """dominant_hand が nullable になっていることを確認する"""

    def test_create_player_with_null_dominant_hand(self, db_session):
        """dominant_hand = None でプレイヤーを作成できる"""
        player = Player(name="テスト選手", dominant_hand=None)
        db_session.add(player)
        db_session.flush()

        fetched = db_session.get(Player, player.id)
        assert fetched is not None
        assert fetched.dominant_hand is None

    def test_create_player_without_dominant_hand_field(self, db_session):
        """dominant_hand を渡さなくてもプレイヤーを作成できる"""
        player = Player(name="利き手未設定選手")
        db_session.add(player)
        db_session.flush()

        fetched = db_session.get(Player, player.id)
        assert fetched is not None
        # デフォルトが None になっていること
        assert fetched.dominant_hand is None

    def test_update_player_dominant_hand_to_null(self, db_session):
        """既存の dominant_hand を NULL に更新できる"""
        player = Player(name="変更テスト選手", dominant_hand="R")
        db_session.add(player)
        db_session.flush()

        player.dominant_hand = None
        db_session.flush()

        fetched = db_session.get(Player, player.id)
        assert fetched.dominant_hand is None

    def test_dominant_hand_accepts_unknown_string(self, db_session):
        """'unknown' (7文字) が格納できる"""
        player = Player(name="未確認選手", dominant_hand="unknown")
        db_session.add(player)
        db_session.flush()

        fetched = db_session.get(Player, player.id)
        assert fetched.dominant_hand == "unknown"

    def test_dominant_hand_accepts_r_and_l(self, db_session):
        """'R' / 'L' が格納できる"""
        pa = Player(name="右利き選手", dominant_hand="R")
        pb = Player(name="左利き選手", dominant_hand="L")
        db_session.add_all([pa, pb])
        db_session.flush()

        fa = db_session.get(Player, pa.id)
        fb = db_session.get(Player, pb.id)
        assert fa.dominant_hand == "R"
        assert fb.dominant_hand == "L"

    def test_player_usable_in_match_with_null_dominant_hand(self, db_session):
        """dominant_hand = None のプレイヤーを試合に登録できる"""
        pa = Player(name="選手A", dominant_hand=None)
        pb = Player(name="選手B", dominant_hand=None)
        db_session.add_all([pa, pb])
        db_session.flush()

        match = Match(
            tournament="テスト大会",
            tournament_level="国内",
            round="1回戦",
            date=date(2026, 4, 8),
            format="singles",
            player_a_id=pa.id,
            player_b_id=pb.id,
            result="win",
        )
        db_session.add(match)
        db_session.flush()

        fetched = db_session.get(Match, match.id)
        assert fetched is not None
        assert fetched.player_a_id == pa.id
