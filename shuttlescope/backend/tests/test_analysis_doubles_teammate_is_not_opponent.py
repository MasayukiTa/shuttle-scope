"""ダブルスで、自分の相方の打球を「相手の打球」に数えない。

Stroke.player は個人の枠 (player_a / partner_a / player_b / partner_b)。
`stroke.player != role` で「相手」を判定すると、role が player_a のとき
partner_a (自分の相方) まで相手扱いになっていた。本番では、対象選手 12 の
「相手の打球」22,507 本のうち 3,021 本 (13.4%)、選手 1 では 22.1% が相方の打球だった。
"""
from datetime import date

from backend.analysis.player_context import is_opponent_stroke, stroke_side
from backend.db.models import GameSet, Match, Player, Rally, Stroke
from backend.routers import analysis_advanced, analysis_stable


# ── 判定関数 ───────────────────────────────────────────────

class TestIsOpponentStroke:
    def test_teammate_is_not_opponent(self):
        assert is_opponent_stroke("partner_a", "player_a") is False
        assert is_opponent_stroke("player_a", "player_a") is False
        assert is_opponent_stroke("partner_b", "player_b") is False

    def test_both_opposing_slots_are_opponents(self):
        assert is_opponent_stroke("player_b", "player_a") is True
        assert is_opponent_stroke("partner_b", "player_a") is True
        assert is_opponent_stroke("player_a", "player_b") is True
        assert is_opponent_stroke("partner_a", "player_b") is True

    def test_unknown_values_are_neither(self):
        assert is_opponent_stroke(None, "player_a") is False
        assert is_opponent_stroke("", "player_a") is False
        assert is_opponent_stroke("coach", "player_a") is False
        assert is_opponent_stroke("player_b", None) is False
        assert is_opponent_stroke("player_b", "partner_a") is False  # チーム側でない値は受け付けない

    def test_stroke_side(self):
        assert [stroke_side(x) for x in ("player_a", "partner_a", "player_b", "partner_b", "x", None)] == [
            "player_a", "player_a", "player_b", "player_b", None, None]


# ── 合成データ ─────────────────────────────────────────────

def _player(db, name, target=False):
    p = Player(name=name, dominant_hand="R", is_target=target)
    db.add(p)
    db.flush()
    return p


def _match(db, a, b, fmt, partner_a=None, partner_b=None):
    m = Match(
        tournament="t", tournament_level="IC", round="1", date=date(2025, 1, 1), format=fmt,
        player_a_id=a.id, player_b_id=b.id,
        partner_a_id=partner_a.id if partner_a else None,
        partner_b_id=partner_b.id if partner_b else None,
        result="loss", annotation_status="complete", annotation_progress=1.0,
    )
    db.add(m)
    db.flush()
    g = GameSet(match_id=m.id, set_num=1, winner="player_b", score_a=0, score_b=1)
    db.add(g)
    db.flush()
    return m, g


def _rally(db, g, num, winner, strokes):
    r = Rally(set_id=g.id, rally_num=num, server="player_a", winner=winner, end_type="forced_error",
              rally_length=len(strokes), score_a_after=0, score_b_after=num, annotation_mode="manual_record")
    db.add(r)
    db.flush()
    for i, (who, land) in enumerate(strokes, start=1):
        db.add(Stroke(rally_id=r.id, stroke_num=i, player=who, shot_type="clear", land_zone=land, hit_zone="BC"))
    db.flush()
    return r


def _doubles(db):
    t = _player(db, "T(player_a)", target=True)
    pa = _player(db, "P(partner_a)")
    o1 = _player(db, "O1(player_b)")
    o2 = _player(db, "O2(partner_b)")
    m, g = _match(db, t, o1, "mixed_doubles", partner_a=pa, partner_b=o2)
    return t, pa, o1, o2, m, g


def _zone_detail(db, player_id, zone):
    return analysis_stable.get_received_vulnerability_zone_detail(
        player_id=player_id, zone=zone, result=None, tournament_level=None,
        date_from=None, date_to=None, db=db)["data"]


# ── 相手の打球の集計 ───────────────────────────────────────

class TestReceivedVulnerabilityZoneDetail:
    def test_teammate_stroke_is_not_counted_as_opponent(self, db_session):
        t, pa, o1, o2, m, g = _doubles(db_session)
        # 失点ラリー。NL に落ちた打球: 相手 2 本 (player_b, partner_b) と、相方 1 本 (partner_a)
        _rally(db_session, g, 1, "player_b", [
            ("player_a", "NC"), ("player_b", "NL"), ("partner_a", "NL"), ("partner_b", "NL")])
        d = _zone_detail(db_session, t.id, "NL")
        assert d["total_count"] == 2      # 相方の 1 本を含めない (旧コードは 3)
        assert d["loss_count"] == 2

    def test_singles_result_is_unchanged(self, db_session):
        a = _player(db_session, "A", target=True)
        b = _player(db_session, "B")
        m, g = _match(db_session, a, b, "singles")
        _rally(db_session, g, 1, "player_b", [("player_a", "NC"), ("player_b", "NL"), ("player_a", "BC"), ("player_b", "NL")])
        _rally(db_session, g, 2, "player_a", [("player_a", "NL"), ("player_b", "NL")])
        d = _zone_detail(db_session, a.id, "NL")
        assert d["total_count"] == 3      # player_b の NL は 3 本 (ラリー 1 に 2 本、ラリー 2 に 1 本)。ラリー 2 の player_a の NL は自分の打球
        assert d["loss_count"] == 2       # ラリー 1 の 2 本が失点ラリー


class TestReceivedVulnerability:
    def test_last_opponent_stroke_is_never_the_teammate(self, db_session):
        t, pa, o1, o2, m, g = _doubles(db_session)
        # 失点ラリー: 相方 (partner_a) 自身の打球が最後。相手の最後の打球は player_b の NC
        _rally(db_session, g, 1, "player_b", [("player_b", "NC"), ("player_a", "NL"), ("partner_a", "BR")])
        d = analysis_stable._received_vulnerability_impl(db_session, t.id)["data"]
        assert "BR" not in d["zones"]     # 旧コードは相方の失敗打を「相手の最終打」として BR に数えた
        assert d["zones"]["NC"]["loss_count"] == 1


class TestOpponentVulnerability:
    def test_partner_of_the_analysed_opponent_is_not_the_other_side(self, db_session):
        t, pa, o1, o2, m, g = _doubles(db_session)
        # 分析対象は相手選手 O1 (player_b 側)。A 側が勝ったラリー (=O1 側の失点)。
        # 最後の打球は O1 の相方 (partner_b) のミス。O1 から見た「相手の最後の打球」は player_a の ML
        _rally(db_session, g, 1, "player_a", [("player_b", "NC"), ("player_a", "ML"), ("partner_b", "BL")])
        d = analysis_advanced.get_opponent_vulnerability(opponent_id=o1.id, db=db_session)["data"]
        assert "BL" not in d["zone_loss_rates"]
        assert d["zone_loss_rates"] == {"ML": 1.0}
