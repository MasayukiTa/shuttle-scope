"""レポート生成のテスト"""
import pytest

from backend.routers.reports import sanitize_player_text, FORBIDDEN_WORDS, DISCLAIMER_JA


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
