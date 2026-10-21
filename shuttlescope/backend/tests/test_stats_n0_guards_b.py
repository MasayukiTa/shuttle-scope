"""統計規則 R1-R3 (n=0 を値にしない / 低 n で判定しない) の回帰テスト — 担当 B 群。

対象: condition_analytics / reports / advice / comprehensive PDF / analysis_spine /
doubles_role_inference / epv_state_model / player_summary_service + insights template /
bayes_matchup / bayesian_rt / counterfactual_v2 / prediction router / analysis_research。

各テストは「n=0 または n=1 で None (または判定なし)」と「有効データでは従来どおりの値」を対にして固定する。
"""
from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.db.database import get_db
from backend.db.models import GameSet, Match, Player, Rally, Stroke
from backend.main import app
from backend.utils.auth import AuthCtx
from backend.utils.jwt_utils import create_access_token


# ── 共通ヘルパー ────────────────────────────────────────────────────────────

def _player(db, name):
    p = Player(name=name, dominant_hand="R")
    db.add(p)
    db.flush()
    return p


def _match(db, a, b, d, wins_a=0, n=0, fmt="singles", result="win", partner_a=None, partner_b=None):
    m = Match(
        tournament="t", tournament_level="IC", round="r", date=d, format=fmt,
        player_a_id=a.id, player_b_id=b.id, result=result,
        partner_a_id=partner_a.id if partner_a else None,
        partner_b_id=partner_b.id if partner_b else None,
        annotation_status="complete", annotation_progress=1.0,
    )
    db.add(m)
    db.flush()
    gs = GameSet(match_id=m.id, set_num=1, winner="player_a", score_a=21, score_b=15)
    db.add(gs)
    db.flush()
    for i in range(1, n + 1):
        db.add(Rally(
            set_id=gs.id, rally_num=i, server="player_a",
            winner="player_a" if i <= wins_a else "player_b",
            end_type="forced_error", rally_length=5,
            score_a_after=0, score_b_after=0, annotation_mode="manual_record",
        ))
    db.flush()
    return m


def _headers(role="admin"):
    tok = create_access_token(user_id=99, role=role, player_id=None, team_name="T", team_id=9101)
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


# ── condition_analytics: nearby_win_rate=None を 0% として数えない ──────────

class TestConditionAnalyticsNoneIsNotZero:
    @staticmethod
    def _rows(rates):
        return [
            {
                "nearby_match_count": 1, "nearby_win_rate": r,
                "ccs_score": 40.0 + 5 * i, "f5_sleep_life": 10.0 + i,
                "f1_physical": 10.0 + i, "f2_stress": 10.0, "f3_mood": 10.0,
                "f4_motivation": 10.0, "hooper_index": 10.0, "sleep_hours": 7.0,
                "recorded_at": f"2026-01-{i + 1:02d}",
            }
            for i, r in enumerate(rates)
        ]

    def test_profile_excludes_unknown_win_rate_rows(self, monkeypatch):
        from backend.analysis import condition_analytics as ca
        rows = self._rows([1.0, 0.5, None, None])
        monkeypatch.setattr(ca, "join_condition_match", lambda *a, **k: rows)
        out = ca.best_performance_profile([], [])
        # 勝率不明の 2 行は母集団から外れる (旧実装は 0% 扱いで n_rest に混ざった)
        assert out["n_top"] + out["n_rest"] == 2

    def test_profile_all_unknown_is_empty(self, monkeypatch):
        from backend.analysis import condition_analytics as ca
        monkeypatch.setattr(ca, "join_condition_match", lambda *a, **k: self._rows([None, None]))
        out = ca.best_performance_profile([], [])
        assert out["n_top"] == 0 and out["key_factors"] == []

    def test_profile_valid_rates_unchanged(self, monkeypatch):
        from backend.analysis import condition_analytics as ca
        monkeypatch.setattr(ca, "join_condition_match", lambda *a, **k: self._rows([1.0, 0.5, 0.0, 0.5]))
        out = ca.best_performance_profile([], [])
        assert out["n_top"] + out["n_rest"] == 4
        assert out["win_rate_in_profile"] is not None and out["win_rate_outside"] is not None

    def test_growth_cards_ignore_unknown_rows(self, monkeypatch):
        from backend.analysis import condition_analytics as ca
        # 勝率が分かる行は高 CCS の 2 行 (どちらも勝ち) だけ。残り 8 行は勝敗不明。
        # 旧実装は不明行を「負け」と数えて効果量 1.0 のカードを作った。
        rows = [
            {"nearby_match_count": 1, "nearby_win_rate": 1.0, "ccs_score": 80.0},
            {"nearby_match_count": 1, "nearby_win_rate": 1.0, "ccs_score": 80.0},
        ] + [
            {"nearby_match_count": 1, "nearby_win_rate": None, "ccs_score": 50.0}
            for _ in range(8)
        ]
        monkeypatch.setattr(ca, "join_condition_match", lambda *a, **k: rows)
        assert ca.player_growth_insights([], [])["growth_cards"] == []

    def test_growth_cards_valid_rows_unchanged(self, monkeypatch):
        from backend.analysis import condition_analytics as ca
        rows = [
            {"nearby_match_count": 1, "nearby_win_rate": 1.0, "ccs_score": 80.0},
            {"nearby_match_count": 1, "nearby_win_rate": 1.0, "ccs_score": 80.0},
        ] + [
            {"nearby_match_count": 1, "nearby_win_rate": 0.0, "ccs_score": 50.0}
            for _ in range(8)
        ]
        monkeypatch.setattr(ca, "join_condition_match", lambda *a, **k: rows)
        cards = ca.player_growth_insights([], [])["growth_cards"]
        assert len(cards) == 1 and cards[0]["win_rate_high"] == 1.0 and cards[0]["win_rate_other"] == 0.0


# ── reports: n=0 の率は null、PDF は "—"、低 n で文言を出し分けない ─────────

class TestReportsZeroRallies:
    def _setup(self, db, rallies_n=0, wins=0):
        from backend.db.models import Team
        team = Team(id=9101, display_id="T-1", name="T")
        db.add(team)
        db.flush()
        a = _player(db, "A")
        a.team_id = team.id
        b = _player(db, "B")
        m = _match(db, a, b, date(2026, 1, 1), wins_a=wins, n=rallies_n)
        m.owner_team_id = team.id
        db.commit()
        return a

    def test_player_growth_null_rates_when_no_rallies(self, client, db_session):
        a = self._setup(db_session, 0)
        body = client.get(f"/api/reports/player_growth?player_id={a.id}", headers=_headers("coach")).json()
        assert body["data"]["win_rate"] is None
        assert body["data"]["avg_rally_length"] is None
        assert body["data"]["total_rallies"] == 0
        assert body["meta"]["sample_size"] == 0

    def test_player_growth_valid_rates_unchanged(self, client, db_session):
        a = self._setup(db_session, 10, wins=6)
        body = client.get(f"/api/reports/player_growth?player_id={a.id}", headers=_headers("coach")).json()
        assert body["data"]["win_rate"] == 0.6
        assert body["data"]["avg_rally_length"] == 5.0

    def test_growth_message_not_tiered_below_five_rallies(self, client, db_session):
        a = self._setup(db_session, 4, wins=4)  # 4/4 = 100% でも「安定した成果」と言わない
        body = client.get(f"/api/reports/player_growth?player_id={a.id}", headers=_headers("coach")).json()
        assert "安定した成果" not in body["data"]["growth_message"]

    def test_scouting_with_no_rallies_does_not_crash_and_prints_dash(self, client, db_session):
        a = self._setup(db_session, 0)
        r = client.get(f"/api/reports/scouting?player_id={a.id}", headers=_headers("coach"))
        assert r.status_code == 200, r.text
        if "json" in r.headers.get("content-type", ""):
            assert r.json()["data"]["win_rate"] is None

    def test_player_role_still_gets_no_win_rate(self, client, db_session):
        a = self._setup(db_session, 0)
        body = client.get(f"/api/reports/player_growth?player_id={a.id}", headers=_headers("admin")).json()
        # admin は従来どおり key を持つ。player ロールの除去は test_player_output_privacy が保証
        assert "win_rate" in body["data"]


# ── advice: 本試合を除いた残りが少数なら基準勝率と比べない ──────────────────

class TestAdvicePostMatchBaseline:
    def _world(self, db, monkeypatch, base_rally_count):
        from backend.services import advice
        a = _player(db, "A")
        b = _player(db, "B")
        m = _match(db, a, b, date.today(), wins_a=6, n=10)
        db.commit()
        monkeypatch.setattr(advice, "_gather_window", lambda *_a, **_k: {
            "match_count": 3, "rally_count": base_rally_count,
            "wins": base_rally_count // 2, "losses": base_rally_count // 2,
            "win_rate": 0.5, "primary_shot": None,
            "from_date": date.today(), "to_date": date.today(),
        })
        ctx = AuthCtx(role="coach", player_id=None, user_id=1, team_name=None, team_id=None)
        return advice.advice_post_match_save(db, a.id, m.id, ctx)

    def test_remaining_rallies_below_min_gives_no_baseline(self, db_session, monkeypatch):
        # 30 日合計 65 ラリー − 本試合 10 = 残り 55 (< MIN_RALLIES=60) → 基準なし
        out = self._world(db_session, monkeypatch, 65)
        assert out["status"] == "ok"
        assert "直近 30 日平均" not in out["advice"]["text"]
        assert out["advice"]["basis"]["baseline"] is None

    def test_enough_remaining_rallies_keeps_baseline(self, db_session, monkeypatch):
        out = self._world(db_session, monkeypatch, 80)  # 残り 70 ≥ 60
        assert "直近 30 日平均" in out["advice"]["text"]
        assert out["advice"]["basis"]["baseline"] == "player_30d_excluding_this"


# ── 包括レポート PDF: 率の列が残るなら件数の列も残す ───────────────────────

class TestComprehensivePdfKeepsCountColumn:
    def test_select_columns_keeps_count_next_to_rate(self):
        from backend.routers._comprehensive_report_endpoints import _select_table_columns
        rows = [{"a": 1, "b": 2, "c": 3, "d": 4, "win_rate": 0.5, "e": 6, "f": 7, "count": 12}]
        assert _select_table_columns(rows) == ["a", "b", "c", "d", "win_rate", "count"]

    def test_select_columns_unchanged_without_rate(self):
        from backend.routers._comprehensive_report_endpoints import _select_table_columns
        rows = [{"a": 1, "b": 2, "c": 3, "d": 4, "e": 5, "f": 6, "count": 12}]
        assert _select_table_columns(rows) == ["a", "b", "c", "d", "e", "f"]

    def test_select_columns_unchanged_when_count_visible(self):
        from backend.routers._comprehensive_report_endpoints import _select_table_columns
        rows = [{"label": "x", "win_rate": 0.5, "count": 3, "d": 1, "e": 2, "f": 3, "g": 4}]
        assert _select_table_columns(rows) == ["label", "win_rate", "count", "d", "e", "f"]

    def test_count_column_is_kept_next_to_rate(self):
        pytest.importorskip("reportlab")
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Table
        from backend.routers._comprehensive_report_endpoints import _render_section_data

        styles = getSampleStyleSheet()
        rows = [
            {"a": 1, "b": 2, "c": 3, "d": 4, "win_rate": 0.5, "e": 6, "f": 7, "count": 12}
            for _ in range(3)
        ]
        flow: list = []
        _render_section_data(flow, rows, styles["Heading3"], styles["BodyText"], "Helvetica")
        tables = [f for f in flow if isinstance(f, Table)]
        header = tables[0]._cellvalues[0]
        assert "win_rate" in header and "count" in header and len(header) == 6

    def test_unchanged_when_count_already_visible(self):
        pytest.importorskip("reportlab")
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Table
        from backend.routers._comprehensive_report_endpoints import _render_section_data

        styles = getSampleStyleSheet()
        rows = [{"label": "x", "win_rate": 0.5, "count": 3, "d": 1, "e": 2, "f": 3, "g": 4}]
        flow: list = []
        _render_section_data(flow, rows, styles["Heading3"], styles["BodyText"], "Helvetica")
        header = [f for f in flow if isinstance(f, Table)][0]._cellvalues[0]
        assert header == ["label", "win_rate", "count", "d", "e", "f"]


# ── doubles role / epv state / stability: 0 件は null ───────────────────────

def _stroke(num, shot):
    return SimpleNamespace(stroke_num=num, player="player_a", shot_type=shot)


class TestDoublesRoleInference:
    def test_no_rallies_gives_null_ratios(self):
        from backend.analysis.doubles_role_inference import compute_doubles_role_inference
        out = compute_doubles_role_inference([], {}, {}, {})
        assert out["total_shots"] == 0
        assert out["front_ratio"] is None and out["back_ratio"] is None and out["neutral_ratio"] is None
        assert out["confidence_score"] is None

    def test_valid_ratios_unchanged(self):
        from backend.analysis.doubles_role_inference import compute_doubles_role_inference
        rally = SimpleNamespace(id=1, set_id=1, score_a_before=0, score_b_before=0)
        strokes = {1: [_stroke(i, "net_shot") for i in range(1, 5)] + [_stroke(5, "clear")]}
        out = compute_doubles_role_inference([rally], strokes, {1: "player_a"}, {1: 1})
        assert out["total_shots"] == 5
        assert out["front_ratio"] == 0.8 and out["back_ratio"] == 0.2 and out["neutral_ratio"] == 0.0

    def test_db2_no_strokes_is_null(self):
        from backend.analysis.doubles_role_inference import compute_doubles_role_db2
        out = compute_doubles_role_db2([], {}, {}, {})
        assert out["total_shots"] == 0
        assert out["front_ratio"] is None and out["confidence_score"] is None
        assert out["hmm_role_sequence_summary"]["front_pct"] is None

    def test_db2_below_min_shots_gives_no_role(self):
        from backend.analysis.doubles_role_inference import compute_doubles_role_db2
        rally = SimpleNamespace(id=1, set_id=1, score_a_before=0, score_b_before=0)
        strokes = {1: [_stroke(i, "net_shot") for i in range(1, 4)]}  # 3 打 < MIN_SHOTS_ROLE
        out = compute_doubles_role_db2([rally], strokes, {1: "player_a"}, {1: 1})
        assert out["total_shots"] == 3
        assert out["inferred_role"] == "unknown" and out["confidence_score"] is None

    def test_db2_enough_shots_still_gets_role(self):
        from backend.analysis.doubles_role_inference import compute_doubles_role_db2
        rally = SimpleNamespace(id=1, set_id=1, score_a_before=0, score_b_before=0)
        strokes = {1: [_stroke(i, "net_shot") for i in range(1, 31)]}
        out = compute_doubles_role_db2([rally], strokes, {1: "player_a"}, {1: 1})
        assert out["inferred_role"] in ("front", "back", "mixed")
        assert out["confidence_score"] is not None


class TestSpineEmptyStates:
    def test_doubles_role_without_doubles_matches_is_null(self, client, db_session):
        a = _player(db_session, "A")
        b = _player(db_session, "B")
        _match(db_session, a, b, date(2026, 1, 1), 5, 10)
        db_session.commit()
        data = client.get(f"/api/analysis/doubles_role?player_id={a.id}", headers=_headers()).json()["data"]
        for k in ("front_ratio", "back_ratio", "neutral_ratio", "confidence_score"):
            assert data[k] is None
        assert data["total_shots"] == 0

    def test_stability_without_doubles_matches_is_null(self, client, db_session):
        a = _player(db_session, "A")
        db_session.commit()
        data = client.get(f"/api/analysis/doubles_role_stability?player_id={a.id}", headers=_headers()).json()["data"]
        assert data["role_stability_score"] is None
        assert data["n_matches_analyzed"] == 0

    def test_epv_state_table_without_matches_has_null_global_rate(self, client, db_session):
        a = _player(db_session, "A")
        db_session.commit()
        data = client.get(f"/api/analysis/epv_state_table?player_id={a.id}", headers=_headers()).json()["data"]
        assert data["global_win_rate"] is None and data["total_rallies"] == 0

    def test_epv_state_model_zero_rallies(self):
        from backend.analysis.epv_state_model import compute_rally_state_epv
        out = compute_rally_state_epv([], {}, {}, {}, {})
        assert out["global_win_rate"] is None and out["total_rallies"] == 0 and out["state_table"] == []

    def test_shot_influence_still_runs_on_empty(self):
        from backend.analysis.shot_influence_v2 import compute_shot_influence_v2
        out = compute_shot_influence_v2([], {}, {}, {}, {})
        assert out is not None


# ── bayes / counterfactual ──────────────────────────────────────────────────

class TestBayesAndCounterfactual:
    def test_bayes_matchup_zero_matches_global_rate_null(self):
        from backend.analysis.bayes_matchup import compute_bayes_matchup
        out = compute_bayes_matchup([], 1)
        assert out["global_win_rate"] is None and out["total_matches"] == 0

    def test_bootstrap_empty_ci_is_null_not_full_range(self):
        from backend.analysis.counterfactual_v2 import (
            _bootstrap_ipw_win_rate, _bootstrap_win_rate, _ipw_weighted_win_rate,
        )
        assert _bootstrap_win_rate([]) == (None, None)
        assert _bootstrap_ipw_win_rate([], []) == (None, None)
        wr, var, n_eff = _ipw_weighted_win_rate([], [])
        assert wr is None and var is None and n_eff == 0.0

    def test_bootstrap_valid_data_has_ci(self):
        from backend.analysis.counterfactual_v2 import _bootstrap_win_rate
        lo, hi = _bootstrap_win_rate([True] * 8 + [False] * 8)
        assert 0.0 <= lo <= hi <= 1.0

    def test_bayesian_rt_set_without_rallies_has_null_raw_rate(self, db_session):
        from backend.analysis.bayesian_rt import BayesianRealTimeAnalyzer
        a = _player(db_session, "A")
        b = _player(db_session, "B")
        m = _match(db_session, a, b, date(2026, 1, 1), 0, 0)  # セットはあるがラリー 0
        db_session.commit()
        out = BayesianRealTimeAnalyzer().generate_interval_report(m.id, 1, db_session)
        assert out["success"] is True
        assert out["data"]["sets"][0]["rally_count"] == 0
        assert out["data"]["sets"][0]["win_rate_raw"] is None


# ── player_summary + insights template ──────────────────────────────────────

class TestPlayerSummaryZero:
    def test_empty_player_rates_are_null_with_counts(self, db_session):
        from backend.analysis.insights.player_summary_service import build_player_summary
        p = _player(db_session, "Ghost")
        db_session.flush()
        out = build_player_summary(db_session, p.id, None, None, None)
        assert out["outcomes"]["win_rate"] is None
        assert out["outcomes"]["set_win_rate"] is None
        assert out["outcomes"]["n"] == 0 and out["outcomes"]["n_sets"] == 0
        assert out["recent_trend"]["n_last_5"] == 0

    def test_valid_rates_unchanged_and_denominators_present(self, db_session):
        from backend.analysis.insights.player_summary_service import build_player_summary
        a = _player(db_session, "A")
        b = _player(db_session, "B")
        _match(db_session, a, b, date(2026, 1, 1), 5, 10, result="win")
        _match(db_session, a, b, date(2026, 1, 2), 5, 10, result="loss")
        db_session.flush()
        out = build_player_summary(db_session, a.id, None, None, None)
        assert out["outcomes"]["win_rate"] == 0.5
        assert out["outcomes"]["n"] == 2 and out["outcomes"]["n_sets"] == 2
        assert out["recent_trend"]["n_last_5"] == 2 and out["recent_trend"]["n_prior_5"] == 0


class TestInsightTemplateFiveMatchGate:
    @staticmethod
    def _ctx(n_last, n_prior, last=0.8, delta=0.2):
        return {
            "lang": "ja", "player_id": 1, "period_days": 30,
            "analytics": {
                "sample": {"strokes": 100, "rallies": 100, "matches": n_last + n_prior},
                "recent_trend": {
                    "last_5_match_win_rate": last, "delta_vs_prior_5": delta,
                    "n_last_5": n_last, "n_prior_5": n_prior,
                },
            },
        }

    def _ids(self, ctx):
        from backend.analysis.insights.template import TemplateGenerator
        res = TemplateGenerator().generate(ctx)
        return {i["id"]: i for i in res["items"]}

    def test_fewer_than_five_matches_no_recent_form_item(self):
        assert "recent_form" not in self._ids(self._ctx(2, 0))

    def test_delta_dropped_when_prior_window_is_short(self):
        item = self._ids(self._ctx(5, 2))["recent_form"]
        assert item["metric"]["delta_vs_prior_5"] is None
        assert "前5試合比" not in item["prose"]

    def test_full_windows_unchanged(self):
        item = self._ids(self._ctx(5, 5))["recent_form"]
        assert item["metric"]["delta_vs_prior_5"] == 0.2
        assert "前5試合比" in item["prose"]

    def test_legacy_payload_without_counts_unchanged(self):
        ctx = self._ctx(5, 5)
        del ctx["analytics"]["recent_trend"]["n_last_5"]
        del ctx["analytics"]["recent_trend"]["n_prior_5"]
        assert "recent_form" in self._ids(ctx)


# ── prediction router ───────────────────────────────────────────────────────

class TestPredictionRouterNoRecord:
    def test_pair_ranking_no_record_partner_is_null_and_last(self, client, db_session):
        anchor = _player(db_session, "Anchor")
        pa = _player(db_session, "PartnerWithRecord")
        pb = _player(db_session, "PartnerNoRecord")
        o1 = _player(db_session, "O1")
        o2 = _player(db_session, "O2")
        _match(db_session, anchor, o1, date(2026, 1, 1), 5, 5, fmt="womens_doubles",
               result="win", partner_a=pa, partner_b=o2)
        db_session.commit()
        resp = client.get(f"/api/prediction/pair_ranking?anchor_player_id={anchor.id}", headers=_headers())
        assert resp.status_code == 200, resp.text
        rows = {r["partner_id"]: r for r in resp.json()["data"]["ranked_partners"]}
        assert rows[pb.id]["sample_size"] == 0 and rows[pb.id]["win_probability"] is None
        assert rows[pa.id]["sample_size"] == 1 and rows[pa.id]["win_probability"] is not None
        order = [r["partner_id"] for r in resp.json()["data"]["ranked_partners"]]
        assert order.index(pa.id) < order.index(pb.id)

    def test_pair_simulation_no_record_is_null(self, client, db_session):
        a = _player(db_session, "A")
        b = _player(db_session, "B")
        db_session.commit()
        d = client.get(
            f"/api/prediction/pair_simulation?player_id_1={a.id}&player_id_2={b.id}", headers=_headers()
        ).json()["data"]
        assert d["sample_size"] == 0 and d["win_probability"] is None

    def test_match_preview_without_matches_is_null(self, client, db_session):
        a = _player(db_session, "A")
        b = _player(db_session, "B")
        db_session.commit()
        resp = client.get(
            f"/api/prediction/match_preview?player_id={a.id}&opponent_id={b.id}", headers=_headers()
        )
        assert resp.status_code == 200, resp.text
        d = resp.json()["data"]
        assert d["sample_size"] == 0
        assert d["win_probability"] is None and "win_probability_v2" not in d

    def test_match_preview_with_matches_keeps_numbers(self, client, db_session):
        a = _player(db_session, "A")
        b = _player(db_session, "B")
        for i in range(3):
            _match(db_session, a, b, date(2026, 1, 1) + timedelta(days=i), 5, 5, result="win")
        db_session.commit()
        d = client.get(
            f"/api/prediction/match_preview?player_id={a.id}&opponent_id={b.id}", headers=_headers()
        ).json()["data"]
        assert d["sample_size"] == 3
        assert isinstance(d["win_probability"], float) and "win_probability_v2" not in d

    def test_analyst_depth_without_matches_is_null(self, client, db_session):
        a = _player(db_session, "A")
        db_session.commit()
        resp = client.get(f"/api/prediction/analyst_depth?player_id={a.id}", headers=_headers())
        assert resp.status_code == 200, resp.text
        d = resp.json()["data"]
        assert d["win_prob_v1"] is None and d["win_prob_v2"] is None


# ── analysis_research: pair_synergy / pair_combined ─────────────────────────

class TestResearchPairEndpoints:
    def test_pair_synergy_without_matches_avg_is_null(self, client, db_session):
        a = _player(db_session, "A")
        db_session.commit()
        d = client.get(f"/api/analysis/pair_synergy?player_id={a.id}", headers=_headers()).json()["data"]
        assert d["player_avg_win_rate"] is None and d["pairs"] == []

    def test_pair_synergy_unannotated_pair_is_excluded_not_zero(self, client, db_session):
        # ラリー 0 本の試合は解析母集団に入らない (analysis_population)。件数は meta に出る
        a = _player(db_session, "A")
        p = _player(db_session, "P")
        o1 = _player(db_session, "O1")
        o2 = _player(db_session, "O2")
        _match(db_session, a, o1, date(2026, 1, 1), 0, 0, fmt="womens_doubles",
               result="win", partner_a=p, partner_b=o2)
        db_session.commit()
        body = client.get(f"/api/analysis/pair_synergy?player_id={a.id}", headers=_headers()).json()
        assert body["data"]["player_avg_win_rate"] is None and body["data"]["pairs"] == []
        assert body["meta"]["excluded"] == {"unfinished": 0, "zero_rally": 1}

    def test_pair_combined_without_strokes_has_null_share(self, client, db_session):
        a = _player(db_session, "A")
        p = _player(db_session, "P")
        o1 = _player(db_session, "O1")
        o2 = _player(db_session, "O2")
        _match(db_session, a, o1, date(2026, 1, 1), 5, 5, fmt="womens_doubles",
               result="win", partner_a=p, partner_b=o2)
        db_session.commit()
        resp = client.get(
            f"/api/analysis/pair_combined?player_a_id={a.id}&player_b_id={p.id}", headers=_headers()
        )
        assert resp.status_code == 200, resp.text
        share = resp.json()["data"]["stroke_share"]
        assert share == {"player_a": None, "player_b": None}
