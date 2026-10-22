"""統計ルール (2026-10-15 オーナー決定「偽の統計になる数字は直す」) の退行防止テスト。

R1: 分母 0 の率は 0.0 / 0.5 ではなく null
R2: 率には側 / 区間ごとの件数を併記する
R3: 標本が小さいときは判定 (タイプ・助言文) を出さない
成長判定: 1 指標 = 1 票 (trend と weighted_trend を 2 票に数えない)

対象: analysis_advanced / analysis_stable / growth_engine / hazard_fatigue / prediction_engine。
有効データ (十分な標本) の出力は従来どおりであることも併せて固定する。
"""
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from backend.analysis.growth_engine import (
    compute_opponent_strength,
    decide_overall_growth,
    strength_weighted_moving_avg,
)
from backend.analysis.hazard_fatigue import compute_hazard_model
from backend.analysis.prediction_engine import (
    compute_feature_win_prob,
    compute_recent_form,
    compute_score_volatility,
)
from backend.analysis.router_helpers import _shot_ja
from backend.db.models import GameSet, Match, Rally, Stroke
from backend.tests.test_ui_numeric_contracts import _match, _player, client  # noqa: F401


# ── 共通ヘルパー ─────────────────────────────────────────────────────────────

def _custom_match(db, a, b, rows, fmt="singles", server="player_a", d=date(2025, 1, 1), result="win"):
    """rows = [(rally_length, winner, score_a_after, score_b_after), ...] のラリーを持つ 1 セット 1 試合。"""
    m = Match(
        tournament="t", tournament_level="IC", round="r", date=d, format=fmt,
        player_a_id=a.id, player_b_id=b.id, result=result,
        annotation_status="complete", annotation_progress=1.0,
    )
    db.add(m)
    db.flush()
    gs = GameSet(match_id=m.id, set_num=1, winner="player_a", score_a=21, score_b=15)
    db.add(gs)
    db.flush()
    rallies = []
    for i, (length, winner, sa, sb) in enumerate(rows, start=1):
        r = Rally(
            set_id=gs.id, rally_num=i, server=server, winner=winner,
            end_type="forced_error", rally_length=length,
            score_a_after=sa, score_b_after=sb, annotation_mode="manual_record",
        )
        db.add(r)
        rallies.append(r)
    db.flush()
    return m, gs, rallies


def _get(client, path):
    resp = client.get(path)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── growth_engine ────────────────────────────────────────────────────────────

def _player_mock(rank=None):
    p = MagicMock()
    p.world_ranking = rank
    return p


def _result_mock(a, b, result):
    m = MagicMock()
    m.player_a_id, m.player_b_id, m.result = a, b, result
    return m


class TestOpponentStrength:
    def test_fewer_than_three_matches_is_none_not_half(self):
        db = MagicMock()
        db.get.return_value = _player_mock(None)
        db.query.return_value.filter.return_value.all.return_value = [
            _result_mock(99, 1, "win"), _result_mock(99, 1, "loss"),
        ]
        assert compute_opponent_strength(db, 99) is None

    def test_three_matches_is_a_real_rate(self):
        db = MagicMock()
        db.get.return_value = _player_mock(None)
        db.query.return_value.filter.return_value.all.return_value = [
            _result_mock(99, 1, "win"), _result_mock(99, 1, "win"), _result_mock(99, 1, "loss"),
        ]
        assert compute_opponent_strength(db, 99) == round(2 / 3, 4)

    def test_unknown_strength_still_weights_as_neutral_in_moving_avg(self):
        # 強度不明 (None) の点も移動平均の「重み」には中立値 0.5 を使う (計算は従来と同一)
        pts = [
            {"value": 0.2, "strength_weight": None},
            {"value": 0.4, "strength_weight": 0.5},
            {"value": 0.6, "strength_weight": 0.5},
        ]
        out = strength_weighted_moving_avg(pts, window_size=3)
        assert out[2]["weighted_moving_avg"] == round((0.2 + 0.4 + 0.6) / 3, 4)


class TestGrowthTimelinePoints:
    def test_point_has_rally_count_and_marks_insufficient_strength(self, client, db_session):
        a = _player(db_session, "山田")
        b = _player(db_session, "標本 桃子")
        for i in range(2):  # 相手 b は 2 試合しか無い → 強度は推定不能
            _match(db_session, a, b, date(2025, 1, 1 + i), 6)
        db_session.commit()
        pts = _get(client, f"/api/analysis/growth_timeline?player_id={a.id}&metric=win_rate")["data"]["points"]
        assert len(pts) == 2
        for p in pts:
            assert p["rally_count"] == 10
            assert p["strength_weight"] is None
            assert p["strength_insufficient"] is True

    def test_valid_strength_point_shape_is_unchanged(self, client, db_session):
        a = _player(db_session, "山田")
        b = _player(db_session, "標本 桃子")
        for i in range(3):  # 3 試合 → 強度は実測値 (b は 0 勝)
            _match(db_session, a, b, date(2025, 1, 1 + i), 6)
        db_session.commit()
        pts = _get(client, f"/api/analysis/growth_timeline?player_id={a.id}&metric=win_rate")["data"]["points"]
        for p in pts:
            assert p["strength_weight"] == 0.0
            assert "strength_insufficient" not in p
            assert p["value"] == 0.6 and p["rally_count"] == 10


class TestOverallGrowthVerdict:
    @staticmethod
    def _m(trend, weighted="pending"):
        return {"trend": trend, "weighted_trend": weighted, "delta": 0.0, "weighted_delta": 0.0}

    def test_one_improving_metric_is_not_two_votes(self):
        # 旧実装: win_rate の trend と weighted_trend の 2 票で「改善傾向」になった
        metrics = {
            "win_rate": self._m("improving", "improving"),
            "serve_win_rate": self._m("stable", "stable"),
        }
        assert decide_overall_growth(metrics) == ("stable", "横ばい")

    def test_two_metrics_improving_is_improving(self):
        metrics = {
            "win_rate": self._m("improving", "stable"),
            "serve_win_rate": self._m("improving", "improving"),
        }
        assert decide_overall_growth(metrics) == ("improving", "改善傾向")

    def test_two_metrics_declining_is_declining(self):
        metrics = {
            "win_rate": self._m("declining", "declining"),
            "serve_win_rate": self._m("declining", "stable"),
        }
        assert decide_overall_growth(metrics) == ("declining", "悪化傾向")

    def test_weighted_trend_contradicting_trend_withdraws_the_vote(self):
        metrics = {
            "win_rate": self._m("improving", "declining"),
            "serve_win_rate": self._m("improving", "improving"),
        }
        assert decide_overall_growth(metrics) == ("stable", "横ばい")

    def test_any_pending_metric_keeps_the_verdict_pending(self):
        metrics = {
            "win_rate": self._m("improving", "improving"),
            "serve_win_rate": self._m("pending", "pending"),
        }
        assert decide_overall_growth(metrics) == ("pending", "判定保留")

    def test_all_pending_is_pending(self):
        metrics = {"win_rate": self._m("pending"), "serve_win_rate": self._m("pending")}
        assert decide_overall_growth(metrics) == ("pending", "判定保留")


# ── rally_length_vs_winrate: player_type ─────────────────────────────────────

class TestPlayerType:
    def test_one_short_rally_does_not_make_a_short_game_specialist(self, client, db_session):
        a = _player(db_session, "山田")
        b = _player(db_session, "標本 桃子")
        _custom_match(db_session, a, b, [(2, "player_a", 1, 0)])
        db_session.commit()
        d = _get(client, f"/api/analysis/rally_length_vs_winrate?player_id={a.id}")["data"]
        assert d["player_type"] == "unknown" and d["player_type_ja"] == "不明"
        assert d["insufficient_data"] is True
        assert d["short_count"] == 1 and d["long_count"] == 0

    def test_enough_rallies_but_no_long_side_is_withheld(self, client, db_session):
        # 全体 30 ラリーでも長ラリーが 0 本なら「短期決戦型」と比較できない
        a = _player(db_session, "山田")
        b = _player(db_session, "標本 桃子")
        _custom_match(db_session, a, b, [(2, "player_a", 1, 0)] * 30)
        db_session.commit()
        d = _get(client, f"/api/analysis/rally_length_vs_winrate?player_id={a.id}")["data"]
        assert d["player_type"] == "unknown" and d["insufficient_data"] is True

    def test_sufficient_data_keeps_the_original_verdict(self, client, db_session):
        a = _player(db_session, "山田")
        b = _player(db_session, "標本 桃子")
        rows = (
            [(2, "player_a", 1, 0)] * 9 + [(2, "player_b", 0, 1)] * 1      # 短い: 9/10 勝ち
            + [(12, "player_a", 1, 0)] * 3 + [(12, "player_b", 0, 1)] * 7  # 長い: 3/10 勝ち
        )
        _custom_match(db_session, a, b, rows)
        db_session.commit()
        d = _get(client, f"/api/analysis/rally_length_vs_winrate?player_id={a.id}")["data"]
        assert d["player_type"] == "short_game_specialist"
        assert d["player_type_ja"] == "短期決戦型"
        assert d["insufficient_data"] is False
        assert d["short_count"] == 10 and d["long_count"] == 10
        by_range = {b_["range"]: b_ for b_ in d["buckets"]}
        assert by_range["1-3"]["win_rate"] == 0.9 and by_range["11-15"]["win_rate"] == 0.3


# ── pressure_performance ─────────────────────────────────────────────────────

class TestPressurePerformance:
    def test_empty_segments_are_null_not_zero(self, client, db_session):
        a = _player(db_session, "山田")
        b = _player(db_session, "標本 桃子")
        _custom_match(db_session, a, b, [(5, "player_a", i, 0) for i in range(1, 4)])  # 全部 normal
        db_session.commit()
        d = _get(client, f"/api/analysis/pressure_performance?player_id={a.id}")["data"]
        for seg in ("deuce", "endgame"):
            assert d[seg]["win_rate"] is None and d[seg]["avg_rally_length"] is None
            assert d[seg]["rally_count"] == 0 and d[seg]["sample_size"] == 0
        assert d["normal"]["win_rate"] == 1.0 and d["normal"]["rally_count"] == 3
        assert d["normal"]["avg_rally_length"] == 5.0

    def test_no_matches_all_segments_null(self, client, db_session):
        a = _player(db_session, "山田")
        db_session.commit()
        d = _get(client, f"/api/analysis/pressure_performance?player_id={a.id}")["data"]
        for seg in ("deuce", "endgame", "normal"):
            assert d[seg]["win_rate"] is None and d[seg]["rally_count"] == 0


# ── temporal / post_long ─────────────────────────────────────────────────────

class TestTemporalAndPostLong:
    def test_phase_without_rallies_is_null(self, client, db_session):
        a = _player(db_session, "山田")
        b = _player(db_session, "標本 桃子")
        _custom_match(db_session, a, b, [(5, "player_a", 1, 0), (5, "player_b", 1, 1)])  # 序盤のみ
        db_session.commit()
        phases = _get(client, f"/api/analysis/temporal_performance?player_id={a.id}")["data"]["phases"]
        by_name = {p["phase"]: p for p in phases}
        assert by_name["序盤(0-7点)"]["win_rate"] == 0.5 and by_name["序盤(0-7点)"]["rally_count"] == 2
        assert by_name["中盤(8-14点)"]["win_rate"] is None and by_name["中盤(8-14点)"]["rally_count"] == 0
        assert by_name["終盤(15点以降)"]["win_rate"] is None

    def test_no_long_rally_means_no_post_long_win_rate_and_no_diff(self, client, db_session):
        a = _player(db_session, "山田")
        b = _player(db_session, "標本 桃子")
        _custom_match(db_session, a, b, [(5, "player_a", 1, 0), (5, "player_b", 1, 1), (5, "player_a", 2, 1)])
        db_session.commit()
        d = _get(client, f"/api/analysis/post_long_rally_stats?player_id={a.id}")["data"]
        assert d["post_long"]["count"] == 0
        assert d["post_long"]["win_rate"] is None and d["post_long"]["avg_rally_length"] is None
        assert d["diff_win_rate"] is None
        assert d["normal"]["win_rate"] == round(2 / 3, 3)

    def test_valid_post_long_diff_is_unchanged(self, client, db_session):
        a = _player(db_session, "山田")
        b = _player(db_session, "標本 桃子")
        # 長ラリー(12)の次のラリーが 1 本勝ち
        rows = [(12, "player_b", 0, 1), (4, "player_a", 1, 1), (4, "player_a", 2, 1)]
        _custom_match(db_session, a, b, rows)
        db_session.commit()
        d = _get(client, f"/api/analysis/post_long_rally_stats?player_id={a.id}")["data"]
        # normal: 1 本目(負け) と 3 本目(長ラリー後ではない=2本目が post_long、3本目は normal)
        assert d["post_long"]["count"] == 1 and d["post_long"]["win_rate"] == 1.0
        assert d["normal"]["count"] == 2 and d["normal"]["win_rate"] == 0.5
        assert d["diff_win_rate"] == 0.5


# ── descriptive / serve-receive splits ───────────────────────────────────────

class TestSideSplits:
    def test_descriptive_with_no_rallies_has_null_rates_and_zero_counts(self, client, db_session):
        a = _player(db_session, "山田")
        db_session.commit()
        d = _get(client, f"/api/analysis/descriptive?player_id={a.id}")["data"]
        assert d["win_rate"] is None and d["avg_rally_length"] is None
        assert d["server_win_rate"] == {
            "as_server": None, "as_receiver": None, "server_count": 0, "receiver_count": 0,
        }

    def test_descriptive_one_sided_server_split(self, client, db_session):
        a = _player(db_session, "山田")
        b = _player(db_session, "標本 桃子")
        _match(db_session, a, b, date(2025, 1, 1), 6)  # 山田が常にサーブ・10 本中 6 勝
        db_session.commit()
        d = _get(client, f"/api/analysis/descriptive?player_id={a.id}")["data"]
        assert d["win_rate"] == 0.6 and d["avg_rally_length"] == 5.0
        assert d["server_win_rate"]["as_server"] == 0.6
        assert d["server_win_rate"]["server_count"] == 10
        assert d["server_win_rate"]["as_receiver"] is None
        assert d["server_win_rate"]["receiver_count"] == 0

    def test_doubles_serve_receive_one_sided(self, client, db_session):
        a = _player(db_session, "山田")
        b = _player(db_session, "標本 桃子")
        _match(db_session, a, b, date(2025, 1, 1), 6, fmt="doubles")
        db_session.commit()
        d = _get(client, f"/api/analysis/doubles_serve_receive?player_id={a.id}")["data"]
        assert d["serve_win_rate"] == 0.6 and d["serve_count"] == 10
        assert d["receive_win_rate"] is None and d["receive_count"] == 0

    def test_stroke_sharing_without_strokes_has_null_rates(self, client, db_session):
        a = _player(db_session, "山田")
        b = _player(db_session, "標本 桃子")
        _match(db_session, a, b, date(2025, 1, 1), 6, fmt="doubles")
        db_session.commit()
        d = _get(client, f"/api/analysis/stroke_sharing?player_id={a.id}")["data"]
        assert d["balanced_count"] == 0 and d["imbalanced_count"] == 0
        assert d["balanced_win_rate"] is None and d["imbalanced_win_rate"] is None
        assert d["avg_balance_ratio"] is None

    def test_consecutive_streaks_no_deuce_sets_is_null(self, client, db_session):
        a = _player(db_session, "山田")
        b = _player(db_session, "標本 桃子")
        m, _gs, _r = _custom_match(db_session, a, b, [(5, "player_a", 1, 0)])
        db_session.commit()
        d = _get(client, f"/api/analysis/consecutive_streaks?match_id={m.id}")["data"]
        assert d["deuce_win_rate"] is None and d["deuce_set_count"] == 0


# ── per-opponent / per-level rows carry the insufficient marker ──────────────

class TestSmallSampleMarkers:
    def test_opponent_stats_marks_rows_below_three_matches(self, client, db_session):
        a = _player(db_session, "山田")
        few = _player(db_session, "少数 太郎")
        many = _player(db_session, "多数 花子")
        _match(db_session, a, few, date(2025, 1, 1), 6)
        for i in range(3):
            _match(db_session, a, many, date(2025, 2, 1 + i), 6)
        db_session.commit()
        rows = {r["opponent_id"]: r for r in
                _get(client, f"/api/analysis/opponent_stats?player_id={a.id}")["data"]["opponents"]}
        assert rows[few.id]["match_count"] == 1 and rows[few.id]["insufficient"] is True
        assert rows[few.id]["win_rate"] == 1.0   # 値は従来どおり (印を付けるだけ)
        assert rows[many.id]["match_count"] == 3 and rows[many.id]["insufficient"] is False

    def test_tournament_levels_mark_rows_below_three_matches(self, client, db_session):
        a = _player(db_session, "山田")
        b = _player(db_session, "標本 桃子")
        for i in range(2):
            _match(db_session, a, b, date(2025, 1, 1 + i), 6)
        db_session.commit()
        levels = _get(client, f"/api/analysis/tournament_level_comparison?player_id={a.id}")["data"]["levels"]
        assert len(levels) == 1 and levels[0]["match_count"] == 2
        assert levels[0]["insufficient"] is True and levels[0]["win_rate"] == 1.0


# ── zone_detail: 打球 0 件の勝率は null ──────────────────────────────────────

class TestZoneDetail:
    def test_zone_without_shots_has_null_win_rate(self, client, db_session):
        a = _player(db_session, "山田")
        b = _player(db_session, "標本 桃子")
        _match(db_session, a, b, date(2025, 1, 1), 6)
        db_session.commit()
        d = _get(client, f"/api/analysis/zone_detail?player_id={a.id}&zone=BL&type=hit")["data"]
        assert d["total_shots"] == 0 and d["win_rate"] is None


# ── flash_advice: 小標本から助言文を出さない ─────────────────────────────────

def _flash(client, m, gs, a):
    return _get(
        client,
        f"/api/analysis/flash_advice?match_id={m.id}&as_of_set={gs.set_num}&player_id={a.id}",
    )["data"]["items"]


def _body(items, category):
    return next(i["body"] for i in items if i["category"] == category)


class TestFlashAdvice:
    def _scenario(self, db_session, smash_rallies, long_rallies_followed_by_loss):
        """12 本のセット。smash_rallies 本の山田勝ちラリーにスマッシュ 1 打を置く。"""
        a = _player(db_session, "山田")
        b = _player(db_session, "標本 桃子")
        rows = []
        # 長ラリー(12 打)を先頭に long_rallies_followed_by_loss 回、直後を負けで置く
        for _ in range(long_rallies_followed_by_loss):
            rows.append((12, "player_a", 1, 0))
            rows.append((3, "player_b", 0, 1))
        while len(rows) < 12:
            rows.append((3, "player_a", 1, 0))
        m, gs, rallies = _custom_match(db_session, a, b, rows)
        placed = 0
        for r in rallies:
            if r.winner == "player_a" and placed < smash_rallies:
                db_session.add(Stroke(rally_id=r.id, stroke_num=1, player="player_a", shot_type="smash"))
                placed += 1
        db_session.commit()
        return a, m, gs

    def test_one_rally_does_not_say_scoring_is_high(self, client, db_session):
        a, m, gs = self._scenario(db_session, smash_rallies=1, long_rallies_followed_by_loss=0)
        body = _body(_flash(client, m, gs, a), "opportunity")
        assert "得点が多い" not in body
        assert "1本" in body

    def test_enough_rallies_keeps_the_original_sentence(self, client, db_session):
        a, m, gs = self._scenario(db_session, smash_rallies=6, long_rallies_followed_by_loss=0)
        label = _shot_ja("smash")
        body = _body(_flash(client, m, gs, a), "opportunity")
        assert body == (
            f"「{label}」での得点が多い"
            f"（このセットで「{label}」を打った6ラリー中"
            f"6ラリーで得点、100%）"
        )

    def test_one_long_rally_does_not_say_watch_for_fatigue(self, client, db_session):
        a, m, gs = self._scenario(db_session, smash_rallies=0, long_rallies_followed_by_loss=1)
        items = _flash(client, m, gs, a)
        body = _body(items, "fatigue_signal")
        assert "消耗に注意" not in body
        assert "1本" in body

    def test_enough_long_rallies_keeps_the_original_sentence(self, client, db_session):
        a, m, gs = self._scenario(db_session, smash_rallies=0, long_rallies_followed_by_loss=5)
        # 長ラリー後の次ラリーは 5 本とも負け → 勝率 0%
        body = _body(_flash(client, m, gs, a), "fatigue_signal")
        assert body == "長ラリー（10球以上）後の次ラリー勝率が0%と低い — 消耗に注意"


# ── hazard_fatigue ───────────────────────────────────────────────────────────

def _hz_rally(set_id, num, winner, length, score_a_before=0):
    return SimpleNamespace(
        set_id=set_id, rally_num=num, winner=winner, rally_length=length,
        score_a_before=score_a_before, score_b_before=0,
    )


class TestHazardFatigue:
    def test_no_rallies_everything_is_null(self):
        out = compute_hazard_model([], {}, {}, {})
        assert out["total_rallies"] == 0
        assert out["hazard_next_loss"] is None and out["hazard_after_long"] is None
        assert out["hazard_endgame"] is None and out["combined_hazard"] is None
        assert out["collapse_risk_band"] is None
        assert out["after_long_rally"]["loss_rate"] is None
        assert out["after_long_rally"]["vs_baseline"] is None
        assert out["endgame_analysis"]["loss_rate"] is None
        assert out["endgame_analysis"]["vs_baseline"] is None
        assert out["after_long_rally"]["n_long_rallies"] == 0

    def test_no_long_rally_and_no_endgame_report_null_but_combined_uses_baseline(self):
        rallies = [_hz_rally(1, i, "player_b" if i % 2 else "player_a", 3) for i in range(1, 7)]
        out = compute_hazard_model(rallies, {1: "player_a"}, {1: 1}, {1: 1})
        assert out["after_long_rally"]["n_long_rallies"] == 0
        assert out["after_long_rally"]["loss_rate"] is None
        assert out["after_long_rally"]["vs_baseline"] is None
        assert out["hazard_after_long"] is None
        assert out["endgame_analysis"]["loss_rate"] is None and out["hazard_endgame"] is None
        # 総合ハザードは従来どおり (観測が無い項はベースラインで置く)
        baseline = out["baseline_loss_rate"]
        assert baseline == 0.5
        expected = round(0.5 * out["hazard_next_loss"] + 0.25 * baseline + 0.25 * baseline, 4)
        assert out["combined_hazard"] == expected

    def test_observed_values_are_unchanged(self):
        # 長ラリー(10 打)の直後に失点が 1 回: after_long の失点率 = 1/1
        rallies = [
            _hz_rally(1, 1, "player_a", 10),
            _hz_rally(1, 2, "player_b", 3),
            _hz_rally(1, 3, "player_a", 3),
        ]
        out = compute_hazard_model(rallies, {1: "player_a"}, {1: 1}, {1: 1})
        assert out["after_long_rally"] == {
            "n_long_rallies": 1, "n_loss_after_long": 1, "loss_rate": 1.0,
            "vs_baseline": round(1.0 - round(1 / 3, 4), 4),
        }
        assert out["hazard_after_long"] == 1.0

    def test_long_rally_threshold_is_the_shared_config_value(self):
        # 基準未満のラリーは長ラリーに数えない (基準は全カード共通の AnalysisConfig)
        from backend.analysis.analysis_config import AnalysisConfig
        from backend.analysis import hazard_fatigue
        assert hazard_fatigue.LONG_RALLY_THRESHOLD == AnalysisConfig.LONG_RALLY_THRESHOLD
        rallies = [
            _hz_rally(1, 1, "player_a", AnalysisConfig.LONG_RALLY_THRESHOLD - 1),
            _hz_rally(1, 2, "player_b", 3),
        ]
        out = compute_hazard_model(rallies, {1: "player_a"}, {1: 1}, {1: 1})
        assert out["after_long_rally"]["n_long_rallies"] == 0


# ── prediction_engine ────────────────────────────────────────────────────────

def _pm(result, d):
    m = MagicMock(spec=Match)
    m.player_a_id, m.player_b_id, m.result, m.date = 1, 101, result, d
    m.tournament_level, m.format, m.sets = "IC", "singles", []
    return m


class TestPredictionEngineNoFakeNeutral:
    def test_no_matches_form_is_null(self):
        r = compute_recent_form([], 1)
        assert r == {'win_rate': None, 'sample': 0, 'trend': None, 'results': [], 'overall_wr': None}

    def test_zero_window_form_is_null_but_keeps_overall(self):
        ms = [_pm("win", date(2024, 1, 1))]
        r = compute_recent_form(ms, 1, n=0)
        assert r["win_rate"] is None and r["sample"] == 0 and r["trend"] is None
        assert r["overall_wr"] is not None

    def test_valid_form_is_unchanged(self):
        ms = [_pm("win", date(2024, 1, 9 - i)) for i in range(5)]
        r = compute_recent_form(ms, 1, n=5)
        assert r["sample"] == 5 and r["win_rate"] == 1.0
        assert r["trend"] == "improving" and r["results"] == ["W"] * 5

    def test_feature_win_prob_with_null_recent_uses_base(self):
        ms = [_pm("win", date(2024, 1, i + 1)) for i in range(4)]
        form = compute_recent_form(ms, 1, n=0)
        prob, bd = compute_feature_win_prob(ms, 1, [], form, {})
        assert bd["recent_wr"] is None
        assert prob == bd["base_wr"]   # 直近項なし → base のみ (weights = {'base': 1.0})

    def test_match_narrative_accepts_the_null_volatility_of_a_player_without_matches(self):
        # score_volatility の各率が null でも比較で TypeError にならない (match_preview が 500 になった)
        from backend.analysis.prediction_engine import compute_match_narrative
        out = compute_match_narrative(
            player_name="A", opponent_name="B", win_prob=0.5, sample_size=0,
            set_distribution={'2-0': 0.25, '2-1': 0.25, '1-2': 0.25, '0-2': 0.25},
            most_likely_scorelines=[], score_volatility=compute_score_volatility([], 1),
            recent_form=compute_recent_form([], 1), obs_context={}, h2h_count=0,
            tournament_level=None,
        )
        assert not any("縺れ" in z for z in out["risk_zones"])  # 試合 0 件で「縺れやすい」と言わない

    def test_volatility_with_no_matches_is_null(self):
        v = compute_score_volatility([], 1)
        assert v["volatility_score"] is None
        assert v["close_match_rate"] is None and v["dominant_match_rate"] is None
        assert v["sample"] == 0
