"""レポート生成のテスト"""
import pytest
from types import SimpleNamespace

from backend.routers.reports import (
    DISCLAIMER_JA,
    FORBIDDEN_WORDS,
    _avg_visible,
    _visible_condition_rows,
    sanitize_player_text,
)


class TestSanitizePlayerText:
    """sanitize_player_text の単体テスト"""

    def test_removes_all_forbidden_words(self):
        """全ての禁止ワードが置換されること"""
        for forbidden_word in FORBIDDEN_WORDS.keys():
            text = f"テスト文 {forbidden_word} テスト"
            result = sanitize_player_text(text)
            assert forbidden_word not in result, \
                f"禁止ワード '{forbidden_word}' がテキストに残っています: {result}"

    def test_replaces_with_correct_words(self):
        """禁止ワードが正しい言葉に置換されること"""
        for forbidden, replacement in FORBIDDEN_WORDS.items():
            text = f"テスト {forbidden} 文"
            result = sanitize_player_text(text)
            assert replacement in result, \
                f"置換後のテキストに '{replacement}' が含まれていません: {result}"

    def test_multiple_forbidden_words(self):
        """複数の禁止ワードが全て置換されること"""
        text = "弱点 苦手 悪い 負け 失敗"
        result = sanitize_player_text(text)
        for forbidden_word in FORBIDDEN_WORDS.keys():
            assert forbidden_word not in result, \
                f"禁止ワード '{forbidden_word}' が残っています: {result}"

    def test_safe_text_unchanged(self):
        """禁止ワードのないテキストは変更されないこと"""
        text = "伸びしろのある選手です。成長エリアを大切にしましょう。"
        result = sanitize_player_text(text)
        assert result == text, "禁止ワードなしのテキストが変更されました"

    def test_empty_text(self):
        """空文字列が処理されること"""
        result = sanitize_player_text("")
        assert result == "", "空文字列が正しく処理されませんでした"


class TestPlayerGrowthReport:
    """player_growth レポートエンドポイントのテスト"""

    def test_response_never_contains_forbidden_words(self):
        """プレイヤー成長レポートのサニタイズが正しく動作すること"""
        # growth_message のサニタイズを直接テスト（DBなし）
        import random
        test_messages = [
            "弱点のある選手です",
            "苦手なショット",
            "悪い傾向がある",
            "負けパターン",
            "失敗から学ぶ",
        ]
        for msg in test_messages:
            result = sanitize_player_text(msg)
            for forbidden_word in FORBIDDEN_WORDS.keys():
                assert forbidden_word not in result, \
                    f"レスポンスに禁止ワード '{forbidden_word}' が含まれています: {result}"

    def test_sanitize_covers_all_forbidden_words(self):
        """FORBIDDEN_WORDSの全ワードがサニタイズされること"""
        # 全禁止ワードを含むテキストを作成
        text = " ".join(FORBIDDEN_WORDS.keys())
        result = sanitize_player_text(text)
        for word in FORBIDDEN_WORDS.keys():
            assert word not in result, f"'{word}' が除去されていません"


class TestScoutingReport:
    """スカウティングレポートのテスト"""

    def test_disclaimer_text_is_correct(self):
        """免責事項テキストが正しいこと"""
        assert DISCLAIMER_JA == "このデータは相関を示すものであり、因果関係を示すものではありません"

    def test_scouting_report_disclaimer_constant_contains_required_text(self):
        """免責事項定数が正しい文言を含むこと"""
        assert "相関" in DISCLAIMER_JA
        assert "因果関係" in DISCLAIMER_JA
        assert len(DISCLAIMER_JA) > 20

class TestReportConditionConsentBoundary:
    """L-5: レポート経路も conditions API と同じ同意境界を使う。"""

    @staticmethod
    def _condition():
        return SimpleNamespace(
            player_id=10,
            measured_at="2026-09-27",
            condition_type="daily",
            ccs_score=82.0,
            hooper_index=11.5,
            session_rpe=7.0,
            sleep_hours=6.5,
            weight_kg=61.2,
            f1_physical=4.0,
            f2_stress=3.0,
            f3_mood=4.0,
            f4_motivation=5.0,
            f5_sleep_life=3.0,
        )

    def test_coach_without_owner_consent_cannot_receive_raw_condition_metrics(self, monkeypatch):
        import backend.routers.conditions as conditions_router

        monkeypatch.setattr(
            conditions_router,
            "_get_owner_body_consents",
            lambda _db, _pid: {},
        )
        rows = _visible_condition_rows(object(), [self._condition()], "coach")

        assert len(rows) == 1
        assert rows[0]["measured_at"] == "2026-09-27"
        for key in ("ccs_score", "hooper_index", "session_rpe", "sleep_hours", "weight_kg"):
            assert key not in rows[0]
        assert _avg_visible(rows, "hooper_index", digits=1) is None

    def test_coach_with_explicit_owner_consent_can_receive_tier3_metrics(self, monkeypatch):
        import backend.routers.conditions as conditions_router

        monkeypatch.setattr(
            conditions_router,
            "_get_owner_body_consents",
            lambda _db, _pid: {"body_disclose_to_coach": True},
        )
        rows = _visible_condition_rows(object(), [self._condition()], "coach")

        assert rows[0]["hooper_index"] == 11.5
        assert rows[0]["session_rpe"] == 7.0
        assert rows[0]["sleep_hours"] == 6.5
        assert rows[0]["weight_kg"] == 61.2
        assert _avg_visible(rows, "hooper_index", digits=1) == 11.5

    def test_analyst_consent_does_not_authorise_coach_and_vice_versa(self, monkeypatch):
        import backend.routers.conditions as conditions_router

        monkeypatch.setattr(
            conditions_router,
            "_get_owner_body_consents",
            lambda _db, _pid: {"body_disclose_to_analyst": True},
        )
        coach_rows = _visible_condition_rows(object(), [self._condition()], "coach")
        analyst_rows = _visible_condition_rows(object(), [self._condition()], "analyst")

        assert "hooper_index" not in coach_rows[0]
        assert analyst_rows[0]["hooper_index"] == 11.5
        assert analyst_rows[0]["weight_kg"] == 61.2

    def test_player_and_admin_keep_their_existing_visibility(self, monkeypatch):
        import backend.routers.conditions as conditions_router

        monkeypatch.setattr(
            conditions_router,
            "_get_owner_body_consents",
            lambda _db, _pid: {},
        )
        player_rows = _visible_condition_rows(object(), [self._condition()], "player")
        admin_rows = _visible_condition_rows(object(), [self._condition()], "admin")

        assert player_rows[0]["hooper_index"] == 11.5
        assert "weight_kg" not in player_rows[0]
        assert admin_rows[0]["hooper_index"] == 11.5
        assert admin_rows[0]["weight_kg"] == 61.2
