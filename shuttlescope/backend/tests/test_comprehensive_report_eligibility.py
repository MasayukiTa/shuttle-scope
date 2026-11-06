"""audit #154: 完全レポートの matches_eligibility が解析母集団への適格性を
試合ごとに正しく内訳表示することの回帰テスト。

「含めた試合数 (matches_included)」だけでは、未完了・未解析 (0 ラリー) の試合や
検証用 fixture (is_synthetic) が通常試合と同じ母集団に混ざって見える。レポート
生成時点で eligible / unfinished / zero_rally / synthetic の内訳を明示する。
判定は解析本体と同じ analysis_population の語彙 (exclusion_reason /
is_synthetic_match) を使う。
"""
from datetime import date

from backend.services.comprehensive_report import gather_player_report
from backend.tests.test_stats_n0_guards_b import _match, _player
from backend.utils.auth import AuthCtx


def _admin():
    return AuthCtx(role="admin", player_id=None, user_id=1, team_name=None, team_id=None)


def _world(db):
    """選手 a の試合を 5 種類作る: 勝ち (有効ラリー有り) / 負け (有効ラリー有り) /
    未完了 / ラリー 0 本の勝ち / 合成 fixture (勝ち・有効ラリー有りだが is_synthetic)。
    相手は全て b。"""
    a = _player(db, "A")
    b = _player(db, "B")
    m_win = _match(db, a, b, date(2026, 1, 1), 3, 6, result="win")
    m_loss = _match(db, a, b, date(2026, 1, 2), 2, 6, result="loss")
    m_unfinished = _match(db, a, b, date(2026, 1, 3), 1, 4, result="unfinished")
    m_zero = _match(db, a, b, date(2026, 1, 4), 0, 0, result="win")
    m_synth = _match(db, a, b, date(2026, 1, 5), 3, 6, result="win")
    m_synth.is_synthetic = True
    db.add(m_synth)
    db.commit()
    return a, b


def test_matches_eligibility_breakdown(db_session):
    a, _b = _world(db_session)
    rep = gather_player_report(db_session, a.id, _admin(), include_per_match=True)
    header = rep["header"]

    # 5 試合すべてが matches_included に入る (母集団から黙って消さない)。
    assert header["matches_included"] == 5

    elig = header["matches_eligibility"]
    # 内訳は解析本体と同じ定義で数える。
    assert elig == {"eligible": 2, "unfinished": 1, "zero_rally": 1, "synthetic": 1}
    # 合計は matches_included と一致する (どの試合も必ず 1 つの区分に入る)。
    assert sum(elig.values()) == header["matches_included"]


def test_eligibility_present_even_when_all_eligible(db_session):
    a = _player(db_session, "Solo")
    b = _player(db_session, "Opp")
    _match(db_session, a, b, date(2026, 2, 1), 3, 6, result="win")
    db_session.commit()
    rep = gather_player_report(db_session, a.id, _admin(), include_per_match=True)
    elig = rep["header"]["matches_eligibility"]
    assert elig == {"eligible": 1, "unfinished": 0, "zero_rally": 0, "synthetic": 0}
