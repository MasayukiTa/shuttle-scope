"""Attack #42+ ハードニングテスト群 (round 4, ライブ攻撃由来)。

Y1: player ロールが research-tier / EPV / weakness / 対戦相手解析にアクセス可能 (CLAUDE.md product safety violation)
    - "Never show player-facing screens direct EPV or direct weakness summaries"
    - middleware に deny-list を追加して自己 player_id でも 403

Y2: /api/conditions/insights / best_profile などの IDOR (player の cross-player)
    - middleware の player_id query 検証が /api/analysis/* + /api/reports/* のみ
      対象だったため、`/api/conditions/insights?player_id=other` で他選手のデータ取得可
    - middleware を /api/conditions/, /api/human_forecast/, /api/warmup/ にも展開

Y3: coach の cross-team scope leak
    - coach が `?player_id=他チーム選手` で他チームの heatmap / EPV / conditions を
      読めていた (require_match_scope は match path にしか効かない)
    - middleware に role=coach 用の team scope 検証を追加
"""
from __future__ import annotations

import pytest


# ─── Y1: research / EPV / weakness deny-list の整合性 ─────────────────────────


class TestPlayerForbiddenAnalysisPaths:
    def test_research_endpoints_in_deny_list(self):
        from backend.main import _PLAYER_FORBIDDEN_ANALYSIS_PATHS as DENY

        # research-tier 主要パス
        for p in [
            "/api/analysis/epv",
            "/api/analysis/spatial_density",
            "/api/analysis/state_best_actions",
            "/api/analysis/state_action_values",
            "/api/analysis/recommendation_ranking",
            "/api/analysis/counterfactual_v2",
            "/api/analysis/counterfactual_shots",
            "/api/analysis/shot_influence",
            "/api/analysis/bayes_matchup",
            "/api/analysis/hazard_fatigue",
            "/api/analysis/bundle/research",
        ]:
            assert p in DENY, f"missing in deny list: {p}"

    def test_weakness_endpoints_in_deny_list(self):
        from backend.main import _PLAYER_FORBIDDEN_ANALYSIS_PATHS as DENY

        for p in [
            "/api/analysis/received_vulnerability",
            "/api/analysis/received_vulnerability/zone_detail",
            "/api/analysis/opponent_vulnerability",
            "/api/analysis/opponent_card",
            "/api/analysis/opponent_stats",
            "/api/analysis/opponent_type_affinity",
            "/api/analysis/opponent_adaptive_shots",
            "/api/analysis/opponent_policy",
            "/api/analysis/win_loss_comparison",
            "/api/analysis/partner_comparison",
        ]:
            assert p in DENY, f"missing in deny list: {p}"

    def test_neutral_endpoints_not_in_deny_list(self):
        """player に開放してよい endpoints が誤って deny-list に入っていないこと。"""
        from backend.main import _PLAYER_FORBIDDEN_ANALYSIS_PATHS as DENY

        for p in [
            "/api/analysis/heatmap",
            "/api/analysis/shot_types",
            "/api/analysis/descriptive",
            "/api/analysis/growth_judgment",
            "/api/analysis/growth_timeline",
            "/api/analysis/pressure_performance",
            "/api/analysis/temporal_performance",
            "/api/analysis/score_progression",
            "/api/analysis/set_summary",
        ]:
            assert p not in DENY, f"unintentionally in deny list: {p}"


# ─── Y2: middleware の player_id query 検証範囲拡張 ──────────────────────────


class TestPlayerIdQueryCoverage:
    def test_middleware_covers_conditions_paths(self):
        """PlayerAccessControlMiddleware が /api/conditions/* も対象にしている。"""
        from backend.main import PlayerAccessControlMiddleware
        import inspect

        src = inspect.getsource(PlayerAccessControlMiddleware.dispatch)
        assert "/api/conditions/" in src
        assert "/api/human_forecast/" in src
        assert "/api/warmup/" in src

    def test_middleware_covers_analysis_and_reports(self):
        from backend.main import PlayerAccessControlMiddleware
        import inspect

        src = inspect.getsource(PlayerAccessControlMiddleware.dispatch)
        assert "/api/analysis/" in src
        assert "/api/reports/" in src


# ─── Y3: coach team scope 強制 ──────────────────────────────────────────────


class TestCoachTeamScope:
    def test_middleware_enforces_coach_team_scope(self):
        """role=coach の player_id クエリパラメータに対して team scope 検証が入っている。"""
        from backend.main import PlayerAccessControlMiddleware
        import inspect

        src = inspect.getsource(PlayerAccessControlMiddleware.dispatch)
        # coach 専用ブロックがあること
        assert 'role == "coach"' in src or "role==\"coach\"" in src
        # access_denied_coach_scope などのログタグ
        assert "coach_scope" in src or "coach" in src
        # Player モデル lookup で team を比較している
        assert ".team" in src

    def test_middleware_block_message_for_coach(self):
        from backend.main import PlayerAccessControlMiddleware
        import inspect

        src = inspect.getsource(PlayerAccessControlMiddleware.dispatch)
        # team scope エラーメッセージが定義されている
        assert "あなたのチームに所属していません" in src
