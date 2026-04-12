"""
予測エンジン — 統計ベースの試合プレビュー予測
Phase A + B + C + D 実装
Phase 1 Rebuild: 多特徴量キャリブレーション、モメンタムセットモデル、アナリスト深掘り
"""
from __future__ import annotations
import math
from collections import Counter
from typing import Optional
import numpy as np
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_

from backend.db.models import Match, GameSet, Rally, Player, PreMatchObservation
from backend.analysis.player_context import player_wins_match as _player_wins_match_ctx

# 大会重要度（TournamentComparison と共通）
LEVEL_IMPORTANCE: dict[str, float] = {
    'IC': 1.0, 'IS': 0.75, 'SJL': 0.5,
    '全日本': 0.25, '国内': 0.0, 'その他': 0.1,
}


def _player_wins_match(match: Match, player_id: int) -> bool:
    """試合結果をプレイヤー視点の bool に変換（player_context への委譲）"""
    return _player_wins_match_ctx(match, player_id)


def get_matches_for_player(
    db: Session,
    player_id: int,
    opponent_id: Optional[int] = None,
    tournament_level: Optional[str] = None,
) -> list[Match]:
    """フィルタ済み試合リスト取得（棄権・未完了除外）"""
    q = (
        db.query(Match)
        .filter(
            or_(Match.player_a_id == player_id, Match.player_b_id == player_id)
        )
        .filter(Match.result.in_(['win', 'loss']))
    )
    if opponent_id is not None:
        q = q.filter(
            or_(
                and_(Match.player_a_id == player_id, Match.player_b_id == opponent_id),
                and_(Match.player_b_id == player_id, Match.player_a_id == opponent_id),
            )
        )
    if tournament_level:
        q = q.filter(Match.tournament_level == tournament_level)
    return q.order_by(Match.date.desc()).all()


def get_pair_matches(
    db: Session,
    player_id_1: int,
    player_id_2: int,
    tournament_level: Optional[str] = None,
) -> list[Match]:
    """ペアとして出場した試合を取得"""
    q = (
        db.query(Match)
        .filter(Match.result.in_(['win', 'loss']))
        .filter(
            or_(
                and_(Match.player_a_id == player_id_1, Match.partner_a_id == player_id_2),
                and_(Match.player_a_id == player_id_2, Match.partner_a_id == player_id_1),
                and_(Match.player_b_id == player_id_1, Match.partner_b_id == player_id_2),
                and_(Match.player_b_id == player_id_2, Match.partner_b_id == player_id_1),
            )
        )
    )
    if tournament_level:
        q = q.filter(Match.tournament_level == tournament_level)
    return q.order_by(Match.date.desc()).all()


def compute_win_probability(
    matches: list[Match],
    player_id: int,
    prior_alpha: float = 2.0,
) -> tuple[float, int]:
    """
    Laplace 平滑化した勝率を返す。
    Returns: (win_probability, sample_size)
    """
    if not matches:
        return 0.5, 0
    wins = sum(1 for m in matches if _player_wins_match(m, player_id))
    n = len(matches)
    p = (wins + prior_alpha / 2) / (n + prior_alpha)
    return round(p, 4), n


def compute_set_distribution(
    matches: list[Match],
    player_id: int,
    win_prob: float,
) -> dict[str, float]:
    """
    2-0 / 2-1 / 1-2 / 0-2 の確率分布を計算。
    実データ ≥ 5 試合: 観測値（Laplace 平滑化）
    実データ < 5 試合: 二項分布近似
    """
    counter: dict[str, int] = {'2-0': 0, '2-1': 0, '1-2': 0, '0-2': 0}

    for m in matches:
        sets = sorted(m.sets or [], key=lambda s: s.set_num)
        wins_sets = sum(
            1 for s in sets
            if (s.winner == 'player_a' and m.player_a_id == player_id)
            or (s.winner == 'player_b' and m.player_b_id == player_id)
        )
        total_sets = len(sets)
        if total_sets == 2:
            if wins_sets == 2:
                counter['2-0'] += 1
            elif wins_sets == 0:
                counter['0-2'] += 1
        elif total_sets == 3:
            if wins_sets == 2:
                counter['2-1'] += 1
            elif wins_sets == 1:
                counter['1-2'] += 1

    total = sum(counter.values())
    if total >= 5:
        return {k: round((v + 0.5) / (total + 2.0), 4) for k, v in counter.items()}

    # 二項分布近似
    p = win_prob
    q = 1 - p
    raw = {
        '2-0': p * p,
        '2-1': 2 * p * p * q,
        '1-2': 2 * p * q * q,
        '0-2': q * q,
    }
    total_prob = sum(raw.values())
    if total_prob <= 0:
        return {'2-0': 0.25, '2-1': 0.25, '1-2': 0.25, '0-2': 0.25}
    return {k: round(v / total_prob, 4) for k, v in raw.items()}


def compute_score_bands(
    matches: list[Match],
    player_id: int,
) -> dict[str, dict[str, int]]:
    """
    各セット(1/2/3)のスコアバンドを計算。
    Returns: { "set1": {"my_low", "my_high", "opp_low", "opp_high"}, ... }
    """
    set_scores: dict[int, list[tuple[int, int]]] = {1: [], 2: [], 3: []}

    for m in matches:
        for s in (m.sets or []):
            if s.set_num not in set_scores:
                continue
            if m.player_a_id == player_id:
                set_scores[s.set_num].append((s.score_a, s.score_b))
            else:
                set_scores[s.set_num].append((s.score_b, s.score_a))

    bands: dict[str, dict[str, int]] = {}
    for sn, scores in set_scores.items():
        if len(scores) < 2:
            continue
        my = sorted(sc[0] for sc in scores)
        opp = sorted(sc[1] for sc in scores)
        n = len(my)
        lo = max(0, int(n * 0.25))
        hi = min(n - 1, int(n * 0.75))
        bands[f'set{sn}'] = {
            'my_low': my[lo],
            'my_high': my[hi],
            'opp_low': opp[lo],
            'opp_high': opp[hi],
            'sample': n,
        }
    return bands


def compute_most_likely_scorelines(
    set_distribution: dict[str, float],
    score_bands: dict[str, dict[str, int]],
) -> list[dict]:
    """最頻スコアラインのリスト（確率上位3件）"""
    results = []
    s1 = score_bands.get('set1', {})
    s2 = score_bands.get('set2', {})
    s3 = score_bands.get('set3', {})

    for outcome, prob in sorted(set_distribution.items(), key=lambda x: -x[1]):
        is_win = outcome.startswith('2')
        item: dict = {'outcome': outcome, 'probability': prob}

        if s1:
            my = s1['my_high'] if is_win else s1['my_low']
            opp = s1['opp_low'] if is_win else s1['opp_high']
            item['set1_score'] = f'{my}-{opp}'
        else:
            item['set1_score'] = '21-??' if is_win else '??-21'

        if outcome in ('2-1', '1-2'):
            if s2:
                # 第2セットは逆パターン傾向
                my2 = s2['my_low'] if is_win else s2['my_high']
                opp2 = s2['opp_high'] if is_win else s2['opp_low']
                item['set2_score'] = f'{my2}-{opp2}'
            if s3:
                my3 = s3['my_high'] if is_win else s3['my_low']
                opp3 = s3['opp_low'] if is_win else s3['opp_high']
                item['set3_score'] = f'{my3}-{opp3}'

        results.append(item)
    return results[:3]


def get_observation_context(
    db: Session,
    player_id: int,
    opponent_id: Optional[int] = None,
    match_id: Optional[int] = None,
) -> dict:
    """ウォームアップ・自コンディション観察コンテキストを取得"""
    if match_id:
        m = db.get(Match, match_id)
        if m:
            opponent_actual = m.player_b_id if m.player_a_id == player_id else m.player_a_id
            obs_list = (
                db.query(PreMatchObservation)
                .filter(PreMatchObservation.match_id == match_id)
                .all()
            )
        else:
            return {}
    elif opponent_id:
        opponent_actual = opponent_id
        # 最近の対戦試合の観察を取得
        recent = (
            db.query(Match)
            .filter(
                Match.result.in_(['win', 'loss']),
                or_(
                    and_(Match.player_a_id == player_id, Match.player_b_id == opponent_id),
                    and_(Match.player_b_id == player_id, Match.player_a_id == opponent_id),
                )
            )
            .order_by(Match.date.desc())
            .first()
        )
        if not recent:
            return {}
        obs_list = (
            db.query(PreMatchObservation)
            .filter(PreMatchObservation.match_id == recent.id)
            .all()
        )
    else:
        return {}

    self_obs: dict = {}
    opp_obs: dict = {}
    for o in obs_list:
        entry = {'value': o.observation_value, 'confidence': o.confidence_level}
        if o.player_id == player_id:
            self_obs[o.observation_type] = entry
        elif o.player_id == opponent_actual:
            opp_obs[o.observation_type] = entry

    ctx: dict = {}
    if self_obs:
        ctx['self'] = self_obs
    if opp_obs:
        ctx['opponent'] = opp_obs
    return ctx


def build_tactical_notes(
    win_prob: float,
    sample_size: int,
    obs_context: dict,
    opponent_player: Optional[Player] = None,
) -> list[dict]:
    """
    ヒューリスティックな戦術ノート（最大3件）
    Returns: [{note: str, estimated_impact: str, basis: str}]
    """
    notes: list[dict] = []
    opp = obs_context.get('opponent', {})
    self_obs = obs_context.get('self', {})

    hand = opp.get('handedness', {})
    if hand.get('value') == 'L':
        notes.append({
            'note': '相手は左利き — バック側への配球が有効な可能性',
            'estimated_impact': '高',
            'basis': '利き手観察（確認済み）',
        })

    phys = opp.get('physical_caution', {})
    if phys.get('value') in ('moderate', 'heavy'):
        notes.append({
            'note': f'相手に身体的ハンデあり — フットワーク多用の展開を検討',
            'estimated_impact': '中',
            'basis': '試合前観察',
        })

    style = opp.get('tactical_style', {})
    if style.get('value') == 'attacker':
        notes.append({
            'note': '相手は攻撃型 — クリアで引き延ばし守備から攻撃転換',
            'estimated_impact': '中',
            'basis': '戦術スタイル観察',
        })
    elif style.get('value') == 'defender':
        notes.append({
            'note': '相手は守備型 — ネット前攻略で主導権を握る',
            'estimated_impact': '高',
            'basis': '戦術スタイル観察',
        })

    cond = self_obs.get('self_condition', {})
    timing = self_obs.get('self_timing', {})
    if cond.get('value') in ('heavy', 'poor'):
        notes.append({
            'note': '自コンディション注意 — ラリーを短くする方針を検討',
            'estimated_impact': '高',
            'basis': '自コンディション観察',
        })
    elif timing.get('value') == 'off':
        notes.append({
            'note': 'タイミング感覚が乱れている — 立ち上がりを慎重に',
            'estimated_impact': '中',
            'basis': '自コンディション観察',
        })

    if sample_size < 5 and not notes:
        notes.append({
            'note': f'対戦データが少ない（{sample_size}試合） — 予測信頼度が低め',
            'estimated_impact': '低',
            'basis': 'サンプルサイズ',
        })

    return notes[:3]


def build_caution_flags(
    win_prob: float,
    sample_size: int,
    obs_context: dict,
) -> list[str]:
    """注意フラグ（最大2件）"""
    flags: list[str] = []
    if win_prob < 0.35:
        flags.append('過去の対戦成績が厳しい — 戦術の再検討が必要')
    elif win_prob > 0.70 and sample_size >= 5:
        flags.append('過去の勝率が高いが油断に注意')

    opp = obs_context.get('opponent', {})
    phys = opp.get('physical_caution', {})
    if phys.get('value') == 'heavy':
        flags.append('相手に重篤な身体的注意事項あり — 試合当日の変動に注意')

    return flags[:2]


def compute_match_narrative(
    player_name: str,
    opponent_name: str,
    win_prob: float,
    sample_size: int,
    set_distribution: dict,
    most_likely_scorelines: list,
    score_volatility: dict,
    recent_form: dict | None,
    obs_context: dict,
    h2h_count: int,
    tournament_level: str | None,
) -> dict:
    """
    試合前サマリーナレーション。
    既存の計算済み値を合成し、人間が読める「決め手 / ぐだりやすい局面 / 試合前の既知情報」を返す。

    Returns:
      verdict         : "勝利有力" | "やや優勢" | "五分五分" | "やや不利" | "苦戦が予想"
      verdict_level   : "win" | "neutral" | "loss"
      likely_score    : "2-1（21-18 / 19-21 / 21-16）" — 最有力スコアライン文字列
      deciding_factor : 決め手1〜2文
      risk_zones      : ぐだりやすい局面のリスト
      knowns          : 試合前に分かっていること（H2H・観察など）
    """
    # ── 判定 ───────────────────────────────────────────────────────────────
    if win_prob >= 0.63:
        verdict, verdict_level = '勝利有力', 'win'
    elif win_prob >= 0.53:
        verdict, verdict_level = 'やや優勢', 'win'
    elif win_prob >= 0.45:
        verdict, verdict_level = '五分五分', 'neutral'
    elif win_prob >= 0.35:
        verdict, verdict_level = 'やや不利', 'loss'
    else:
        verdict, verdict_level = '苦戦が予想', 'loss'

    # ── 最有力スコアライン ─────────────────────────────────────────────────
    likely_score = '—'
    if most_likely_scorelines:
        top = most_likely_scorelines[0]
        sets_str = ' / '.join(
            s for s in [top.get('set1_score'), top.get('set2_score'), top.get('set3_score')] if s
        )
        outcome_label = '勝利' if str(top.get('outcome', '')).startswith('2') else '敗北'
        pct = round(top.get('probability', 0) * 100)
        likely_score = f"{top.get('outcome', '?')} {outcome_label}（{sets_str}）— {pct}%"

    # ── 決め手 ─────────────────────────────────────────────────────────────
    deciding_parts: list[str] = []
    if h2h_count >= 3:
        h2h_wr = round(win_prob * 100)
        deciding_parts.append(f'直接対戦での実績（{h2h_count}試合 / 推定勝率{h2h_wr}%）')
    elif sample_size >= 5:
        deciding_parts.append(f'過去の総合成績（{sample_size}試合ベース）')

    rf = recent_form or {}
    if rf.get('trend') == 'improving' and rf.get('sample', 0) >= 3:
        deciding_parts.append('直近の調子が上向き')
    elif rf.get('trend') == 'declining' and rf.get('sample', 0) >= 3:
        deciding_parts.append('直近の調子が下降傾向（要注意）')

    sv = score_volatility or {}
    if sv.get('dominant_match_rate', 0) >= 0.5 and verdict_level == 'win':
        deciding_parts.append('ストレート勝ちが多く圧倒しやすい相手')
    elif sv.get('close_match_rate', 0) >= 0.5:
        deciding_parts.append('接戦が多く終盤の集中力が鍵')

    opp_obs = obs_context.get('opponent', {})
    if opp_obs.get('handedness', {}).get('value') == 'L':
        deciding_parts.append('相手が左利き（バック側への配球が有効）')
    if opp_obs.get('tactical_style', {}).get('value') == 'attacker':
        deciding_parts.append('相手の攻撃スタイルに対する守備安定が鍵')
    elif opp_obs.get('tactical_style', {}).get('value') == 'defender':
        deciding_parts.append('守備型の相手にネット前攻略で主導権を握れるか')

    deciding_factor = '。'.join(deciding_parts[:2]) if deciding_parts else f'データ不足（{sample_size}試合）のため不確実性が高い'
    if deciding_parts:
        deciding_factor += '。'

    # ── ぐだりやすい局面 ────────────────────────────────────────────────────
    risk_zones: list[str] = []
    if sv.get('close_match_rate', 0) >= 0.4:
        risk_zones.append(f'ファイナルセットに縺れやすい（過去{round(sv["close_match_rate"]*100)}%）')
    if sv.get('typical_margin') is not None and sv['typical_margin'] <= 4 and sv.get('sample', 0) >= 3:
        risk_zones.append('点差が僅差になりやすい（平均得点差{:.1f}点）'.format(sv['typical_margin']))

    # セット分布から第2セット接戦傾向を推定
    dist_21 = set_distribution.get('2-1', 0) + set_distribution.get('1-2', 0)
    if dist_21 >= 0.45:
        risk_zones.append(f'3セット戦になる可能性が高い（{round(dist_21*100)}%）')

    phys = opp_obs.get('physical_caution', {})
    if phys.get('value') in ('moderate', 'heavy'):
        risk_zones.append('相手の身体コンディション変動による展開の読みにくさ')

    self_obs = obs_context.get('self', {})
    if self_obs.get('self_condition', {}).get('value') in ('poor', 'heavy'):
        risk_zones.append('自コンディション不良 — スロースタートのリスク')

    if not risk_zones and sample_size >= 5:
        risk_zones.append('特段の波乱要因なし（過去実績が比較的安定）')
    elif not risk_zones:
        risk_zones.append('データが少なく局面予測の精度が低い')

    # ── 試合前の既知情報 ────────────────────────────────────────────────────
    knowns: list[str] = []
    if h2h_count > 0:
        knowns.append(f'直接対戦データ: {h2h_count}試合')
    if tournament_level:
        knowns.append(f'大会レベル: {tournament_level}')
    if opp_obs.get('handedness', {}).get('value') in ('L', 'R'):
        hand_label = '左利き' if opp_obs['handedness']['value'] == 'L' else '右利き'
        knowns.append(f'相手利き手: {hand_label}')
    if opp_obs.get('tactical_style', {}).get('value'):
        style_map = {'attacker': '攻撃型', 'defender': '守備型', 'balanced': 'バランス型'}
        style_label = style_map.get(opp_obs['tactical_style']['value'], opp_obs['tactical_style']['value'])
        knowns.append(f'相手戦術スタイル: {style_label}')
    if opp_obs.get('physical_caution', {}).get('value') not in (None, 'none'):
        phys_map = {'light': '軽度', 'moderate': '中程度', 'heavy': '重度'}
        phys_label = phys_map.get(phys.get('value', ''), phys.get('value', ''))
        knowns.append(f'相手身体的注意: {phys_label}')
    self_cond = self_obs.get('self_condition', {}).get('value')
    if self_cond and self_cond != 'normal':
        cond_map = {'great': '絶好調', 'poor': '不調', 'heavy': '重大注意'}
        knowns.append(f'自コンディション: {cond_map.get(self_cond, self_cond)}')
    if not knowns:
        knowns.append(f'事前観察なし — {sample_size}試合の統計データのみ')

    return {
        'verdict': verdict,
        'verdict_level': verdict_level,
        'likely_score': likely_score,
        'deciding_factor': deciding_factor,
        'risk_zones': risk_zones[:3],
        'knowns': knowns[:5],
    }


def compute_confidence_score(sample_size: int, similar_matches: int) -> float:
    """信頼度スコア (0.0–1.0)"""
    base = 1.0 - math.exp(-sample_size / 20.0)
    bonus = min(0.15, similar_matches * 0.015)
    return round(min(0.95, base + bonus), 4)


def compute_prediction_drivers(
    db: Session,
    player_id: int,
    opponent_id: Optional[int] = None,
    tournament_level: Optional[str] = None,
) -> dict:
    """
    予測に使ったデータソースの内訳と根拠を返す (Spec §3.5 / §3.6)
    """
    all_matches = get_matches_for_player(db, player_id)
    h2h_matches = (
        get_matches_for_player(db, player_id, opponent_id=opponent_id)
        if opponent_id else []
    )
    level_matches = (
        get_matches_for_player(db, player_id, tournament_level=tournament_level)
        if tournament_level else []
    )
    obs = get_observation_context(db, player_id, opponent_id)

    if len(h2h_matches) >= 3:
        primary_type = 'h2h'
        primary_count = len(h2h_matches)
    elif tournament_level and len(level_matches) >= 3:
        primary_type = 'level'
        primary_count = len(level_matches)
    else:
        primary_type = 'all'
        primary_count = len(all_matches)

    drivers: list[dict] = []
    if h2h_matches:
        drivers.append({
            'label': f'直接対戦実績',
            'type': 'h2h',
            'count': len(h2h_matches),
            'weight': 'primary' if primary_type == 'h2h' else 'secondary',
        })
    if tournament_level and level_matches:
        drivers.append({
            'label': f'{tournament_level}大会実績',
            'type': 'level',
            'count': len(level_matches),
            'weight': 'primary' if primary_type == 'level' else 'secondary',
        })
    drivers.append({
        'label': '全試合統計',
        'type': 'all',
        'count': len(all_matches),
        'weight': 'primary' if primary_type == 'all' else 'background',
    })
    if obs:
        obs_count = len(obs.get('opponent', {})) + len(obs.get('self', {}))
        if obs_count > 0:
            drivers.append({
                'label': 'ウォームアップ観察',
                'type': 'observation',
                'count': obs_count,
                'weight': 'contextual',
            })

    return {
        'primary_type': primary_type,
        'primary_count': primary_count,
        'h2h_count': len(h2h_matches),
        'same_level_count': len(level_matches),
        'all_count': len(all_matches),
        'has_observations': bool(obs),
        'drivers': drivers,
    }


def compute_calibrated_scorelines(
    matches: list[Match],
    player_id: int,
) -> list[dict]:
    """
    実測スコアラインの頻度ヒストグラム (Phase D キャリブレーション用)
    上位8件を返す。
    """
    counter: Counter = Counter()
    for m in matches:
        sets = sorted(m.sets or [], key=lambda s: s.set_num)
        if not sets:
            continue
        parts: list[str] = []
        wins_sets = 0
        for s in sets:
            if m.player_a_id == player_id:
                parts.append(f"{s.score_a}-{s.score_b}")
                if s.winner == 'player_a':
                    wins_sets += 1
            else:
                parts.append(f"{s.score_b}-{s.score_a}")
                if s.winner == 'player_b':
                    wins_sets += 1
        total_sets = len(sets)
        outcome = f"{wins_sets}-{total_sets - wins_sets}"
        counter[(outcome, ', '.join(parts))] += 1

    total = sum(counter.values())
    if not total:
        return []
    return [
        {
            'outcome': outcome,
            'scoreline': scoreline,
            'count': count,
            'frequency': round(count / total, 4),
        }
        for (outcome, scoreline), count in counter.most_common(8)
    ]


def _empty_fatigue_result() -> dict:
    return {
        'risk_score': 0.0,
        'risk_signals': [],
        'confidence': 0.0,
        'recommendation': None,
        'breakdown': {
            'temporal_drop': 0.0, 'long_rally_penalty': 0.0, 'pressure_drop': 0.0,
            'early_sample': 0, 'late_sample': 0, 'long_rally_sample': 0,
            'pressure_sample': 0, 'total_rallies': 0,
        },
    }


def compute_fatigue_risk(
    db: Session,
    player_id: int,
    tournament_level: Optional[str] = None,
) -> dict:
    """
    疲労・崩壊リスク推定 (Phase C)
    3指標の加重平均:
      - temporal_drop  (40%): 序盤(≤8点) vs 終盤(≥20点) の勝率差
      - long_rally_penalty (30%): 長ラリー(≥7打) 直後の勝率低下
      - pressure_drop  (30%): デュース時の勝率低下
    """
    matches = get_matches_for_player(db, player_id, tournament_level=tournament_level)
    if not matches:
        return _empty_fatigue_result()

    # set_id → Match の逆引き
    set_to_match: dict[int, Match] = {}
    all_set_ids: list[int] = []
    for m in matches:
        for s in (m.sets or []):
            set_to_match[s.id] = m
            all_set_ids.append(s.id)

    if not all_set_ids:
        return _empty_fatigue_result()

    rallies: list[Rally] = (
        db.query(Rally)
        .filter(Rally.set_id.in_(all_set_ids), Rally.is_skipped == False)
        .order_by(Rally.set_id, Rally.rally_num)
        .all()
    )

    if not rallies:
        return _empty_fatigue_result()

    def won(r: Rally) -> bool:
        m = set_to_match.get(r.set_id)
        if not m:
            return False
        return r.winner == ('player_a' if m.player_a_id == player_id else 'player_b')

    # ── temporal drop ──
    early_w = early_t = late_w = late_t = 0
    for r in rallies:
        total_pts = (r.score_a_after or 0) + (r.score_b_after or 0)
        w = won(r)
        if total_pts <= 8:
            early_t += 1
            if w:
                early_w += 1
        elif total_pts >= 20:
            late_t += 1
            if w:
                late_w += 1

    temporal_drop = 0.0
    if early_t >= 5 and late_t >= 5:
        temporal_drop = max(0.0, early_w / early_t - late_w / late_t)

    # ── long rally penalty ──
    LONG_THRESHOLD = 7
    rally_lookup = {(r.set_id, r.rally_num): r for r in rallies}
    post_long_w = post_long_t = 0
    for r in rallies:
        if (r.rally_length or 0) >= LONG_THRESHOLD:
            nxt = rally_lookup.get((r.set_id, r.rally_num + 1))
            if nxt:
                post_long_t += 1
                if won(nxt):
                    post_long_w += 1

    overall_wr = sum(1 for r in rallies if won(r)) / len(rallies)
    long_rally_penalty = 0.0
    if post_long_t >= 5:
        long_rally_penalty = max(0.0, overall_wr - post_long_w / post_long_t)

    # ── pressure drop (deuce) ──
    deuce_w = deuce_t = 0
    for r in rallies:
        if r.is_deuce:
            deuce_t += 1
            if won(r):
                deuce_w += 1

    pressure_drop = 0.0
    if deuce_t >= 5:
        pressure_drop = max(0.0, overall_wr - deuce_w / deuce_t)

    risk_score = temporal_drop * 0.40 + long_rally_penalty * 0.30 + pressure_drop * 0.30

    signals: list[str] = []
    if temporal_drop >= 0.08:
        signals.append(f'試合後半の得点率が序盤より {int(temporal_drop * 100)}% 低下')
    if long_rally_penalty >= 0.08:
        signals.append(f'長ラリー直後の勝率が通常より {int(long_rally_penalty * 100)}% 低下')
    if pressure_drop >= 0.08:
        signals.append(f'デュース時の勝率が通常より {int(pressure_drop * 100)}% 低下')

    recommendation: Optional[str] = None
    if risk_score >= 0.12:
        recommendation = '後半スタミナ管理が課題 — 早めに終わらせる配球・サービスパターンを意識'
    elif risk_score >= 0.06:
        recommendation = '終盤・デュース時の集中力維持に注意。事前にメンタルルーティンを準備'

    conf = compute_confidence_score(len(rallies) // 15, 0)

    return {
        'risk_score': round(risk_score, 4),
        'risk_signals': signals,
        'confidence': conf,
        'recommendation': recommendation,
        'breakdown': {
            'temporal_drop': round(temporal_drop, 4),
            'long_rally_penalty': round(long_rally_penalty, 4),
            'pressure_drop': round(pressure_drop, 4),
            'early_sample': early_t,
            'late_sample': late_t,
            'long_rally_sample': post_long_t,
            'pressure_sample': deuce_t,
            'total_rallies': len(rallies),
        },
    }


def confidence_meta(confidence: float, sample_size: int) -> dict:
    """ConfidenceBadge 互換のメタ情報"""
    if confidence >= 0.70:
        level, stars = 'high', '★★★'
    elif confidence >= 0.40:
        level, stars = 'medium', '★★☆'
    else:
        level, stars = 'low', '★☆☆'
    return {
        'level': level,
        'stars': stars,
        'label': f'信頼度 {int(confidence * 100)}%',
        'warning': f'サンプル {sample_size} 試合' if sample_size < 10 else None,
    }


# ─── Phase 1 Rebuild: 多特徴量モデル群 ────────────────────────────────────────

def compute_recent_form(
    matches: list[Match],
    player_id: int,
    n: int = 5,
) -> dict:
    """
    直近 n 試合の指数重み付き勝率とトレンド方向を返す。
    matches は日付降順（get_matches_for_player の出力）を想定。
    """
    if not matches:
        return {'win_rate': 0.5, 'sample': 0, 'trend': 'stable', 'results': [], 'overall_wr': 0.5}

    overall_wr, _ = compute_win_probability(matches, player_id)

    recent = matches[:n]
    sample = len(recent)

    # 指数重み: index 0 = 最新, decay = 0.85
    decay = 0.85
    weights = [decay ** i for i in range(sample)]
    w_sum = sum(weights)

    weighted_wins = sum(
        weights[i] for i, m in enumerate(recent)
        if _player_wins_match(m, player_id)
    )
    recent_wr = weighted_wins / w_sum if w_sum > 0 else 0.5

    # 結果列（古い順）: ['W', 'L', ...]
    results = ['W' if _player_wins_match(m, player_id) else 'L' for m in reversed(recent)]

    diff = recent_wr - overall_wr
    if diff > 0.08:
        trend = 'improving'
    elif diff < -0.08:
        trend = 'declining'
    else:
        trend = 'stable'

    return {
        'win_rate': round(recent_wr, 4),
        'sample': sample,
        'trend': trend,
        'results': results,
        'overall_wr': round(overall_wr, 4),
    }


def compute_growth_trend(
    matches: list[Match],
    player_id: int,
) -> dict:
    """
    試合を時系列バケットに分割し、セットごとの勝率トレンドを算出する。
    numpy.polyfit による線形回帰でスロープを計算。
    """
    if not matches:
        return {'buckets': [], 'slope': 0.0, 'direction': 'flat', 'sample': 0}

    # 古い順にソート
    sorted_matches = sorted(matches, key=lambda m: m.date)
    n = len(sorted_matches)

    # 最大6バケット、各バケット ≥1 試合
    n_buckets = min(6, n)
    chunks = [arr.tolist() for arr in np.array_split(sorted_matches, n_buckets) if len(arr) > 0]

    buckets: list[dict] = []
    for chunk in chunks:
        if not chunk:
            continue
        wins = sum(1 for m in chunk if _player_wins_match(m, player_id))
        total = len(chunk)
        wr = (wins + 0.5) / (total + 1.0)  # Laplace
        label = chunk[0].date.strftime('%y/%m') if hasattr(chunk[0].date, 'strftime') else str(chunk[0].date)[:7]
        buckets.append({'label': label, 'win_rate': round(wr, 4), 'sample': total})

    if len(buckets) >= 2:
        x = np.arange(len(buckets), dtype=float)
        y = np.array([b['win_rate'] for b in buckets])
        slope = float(np.polyfit(x, y, 1)[0])
    else:
        slope = 0.0

    if slope > 0.02:
        direction = 'up'
    elif slope < -0.02:
        direction = 'down'
    else:
        direction = 'flat'

    return {
        'buckets': buckets,
        'slope': round(slope, 6),
        'direction': direction,
        'sample': n,
    }


def compute_feature_win_prob(
    matches: list[Match],
    player_id: int,
    h2h_matches: list[Match],
    recent_form: dict,
    obs_context: dict,
) -> tuple[float, dict]:
    """
    多特徴量ブレンドによるキャリブレーション済み勝率。
    base_wr / recent_wr / h2h_wr を適応的な重みで統合し、
    観察コンテキストの修正値を加算する。
    """
    base_wr, _ = compute_win_probability(matches, player_id)
    recent_wr = recent_form.get('win_rate', base_wr)
    recent_n = recent_form.get('sample', 0)
    h2h_n = len(h2h_matches)

    h2h_wr: Optional[float] = None
    if h2h_n >= 3:
        h2h_wr, _ = compute_win_probability(h2h_matches, player_id)

    # 適応的重み選択
    if h2h_wr is not None:
        weights = {'base': 0.25, 'recent': 0.35, 'h2h': 0.40}
        raw_blend = base_wr * 0.25 + recent_wr * 0.35 + h2h_wr * 0.40
    elif recent_n >= 3:
        weights = {'base': 0.40, 'recent': 0.60}
        raw_blend = base_wr * 0.40 + recent_wr * 0.60
    else:
        weights = {'base': 1.0}
        raw_blend = base_wr

    # 観察コンテキスト修正
    opp_obs = obs_context.get('opponent', {})
    self_obs = obs_context.get('self', {})
    obs_modifier = 0.0
    if opp_obs.get('physical_caution', {}).get('value') in ('moderate', 'heavy'):
        obs_modifier += 0.03
    if self_obs.get('self_condition', {}).get('value') in ('poor', 'heavy'):
        obs_modifier -= 0.05
    if self_obs.get('self_timing', {}).get('value') == 'off':
        obs_modifier -= 0.04

    final = max(0.10, min(0.90, raw_blend + obs_modifier))

    breakdown = {
        'base_wr': round(base_wr, 4),
        'recent_wr': round(recent_wr, 4),
        'h2h_wr': round(h2h_wr, 4) if h2h_wr is not None else None,
        'weights': weights,
        'obs_modifier': round(obs_modifier, 4),
        'raw_blend': round(raw_blend, 4),
        'final': round(final, 4),
    }
    return round(final, 4), breakdown


def compute_set_model_v2(
    win_prob: float,
    observed_dist: Optional[dict],
) -> dict:
    """
    モメンタム考慮のセット分布モデル。
    observed_dist が渡された場合（実測 ≥ 5 試合）はそのまま使用。
    それ以外はモメンタムモデルで計算。
    数学的に 合計 = 1.0 が保証されるが、min/max クランプ後に正規化する。
    """
    if observed_dist is not None:
        return {'dist': observed_dist, 'model_type': 'observed'}

    p = win_prob
    # モメンタム係数
    p2_w = min(0.92, p * 1.12)   # セット1勝利後のセット2勝率
    p2_l = max(0.08, p * 0.88)   # セット1敗北後のセット2勝率
    p3 = p                        # 第3セットはリセット

    raw = {
        '2-0': p * p2_w,
        '2-1': p * (1 - p2_w) * p3 + (1 - p) * p2_l * p3,
        '1-2': p * (1 - p2_w) * (1 - p3) + (1 - p) * p2_l * (1 - p3),
        '0-2': (1 - p) * (1 - p2_l),
    }
    total = sum(raw.values())
    if total <= 0:
        total = 1.0
    dist = {k: round(v / total, 4) for k, v in raw.items()}

    return {'dist': dist, 'model_type': 'momentum'}


def compute_brier_score(
    matches: list[Match],
    player_id: int,
) -> dict:
    """
    Leave-one-out ブライアスコア。予測キャリブレーションの質を示す。
    < 0.20: 良好  /  0.20–0.25: 普通  /  > 0.25: 要注意
    5 試合未満は算出不可（score=None）。
    """
    if len(matches) < 5:
        return {'score': None, 'sample': len(matches), 'grade': None}

    squared_errors: list[float] = []
    for i, m in enumerate(matches):
        holdout = [x for x in matches if x is not m]
        pred, _ = compute_win_probability(holdout, player_id)
        actual = 1.0 if _player_wins_match(m, player_id) else 0.0
        squared_errors.append((pred - actual) ** 2)

    score = sum(squared_errors) / len(squared_errors)
    if score < 0.20:
        grade = 'good'
    elif score <= 0.25:
        grade = 'fair'
    else:
        grade = 'poor'

    return {'score': round(score, 4), 'sample': len(matches), 'grade': grade}


def compute_score_volatility(
    matches: list[Match],
    player_id: int,
) -> dict:
    """
    Phase S4: スコアボラティリティ（試合展開の荒れやすさ）を推定。
    - close_match_rate: 最終セットまで縺れた試合の割合
    - dominant_match_rate: 2-0 ストレート勝ち/負けの割合
    - typical_margin: 勝ったセットの典型的な得点差（自視点）
    - volatility_score: 0.0（安定）〜 1.0（不安定）
    """
    if not matches:
        return {
            'volatility_score': 0.0,
            'close_match_rate': 0.0,
            'dominant_match_rate': 0.0,
            'typical_margin': None,
            'sample': 0,
        }

    close = 0
    dominant = 0
    margins: list[float] = []

    for m in matches:
        sets = sorted(m.sets or [], key=lambda s: s.set_num)
        if not sets:
            continue
        n_sets = len(sets)
        if n_sets == 3:
            close += 1
        elif n_sets == 2:
            dominant += 1

        for s in sets:
            if m.player_a_id == player_id:
                my, opp = s.score_a, s.score_b
            else:
                my, opp = s.score_b, s.score_a
            if my is not None and opp is not None:
                margins.append(abs(my - opp))

    n = len(matches)
    close_rate = round(close / n, 4) if n else 0.0
    dominant_rate = round(dominant / n, 4) if n else 0.0
    typical_margin = round(sum(margins) / len(margins), 2) if margins else None

    # ボラティリティ: 接戦率が高いほど不安定
    volatility = close_rate * 0.7 + (1 - dominant_rate) * 0.3
    volatility = round(min(1.0, max(0.0, volatility)), 4)

    return {
        'volatility_score': volatility,
        'close_match_rate': close_rate,
        'dominant_match_rate': dominant_rate,
        'typical_margin': typical_margin,
        'sample': n,
    }


def compute_lineup_scores(
    db: Session,
    player_ids: list[int],
    opponent_id: Optional[int] = None,
    tournament_level: Optional[str] = None,
) -> list[dict]:
    """
    Phase S3: 複数選手の勝率予測をランク付けしてラインナップ最適化を支援。
    各 player_id に対して compute_feature_win_prob を実行し、降順で返す。
    """
    results: list[dict] = []
    for pid in player_ids:
        all_m = get_matches_for_player(db, pid)
        h2h_m = (
            get_matches_for_player(db, pid, opponent_id=opponent_id)
            if opponent_id else []
        )
        obs = get_observation_context(db, pid, opponent_id)
        recent = compute_recent_form(all_m, pid)
        win_prob, breakdown = compute_feature_win_prob(all_m, pid, h2h_m, recent, obs)
        conf = compute_confidence_score(len(all_m), len(h2h_m))
        player = db.get(Player, pid)
        results.append({
            'player_id': pid,
            'player_name': player.name if player else str(pid),
            'win_probability': win_prob,
            'confidence': conf,
            'sample_size': len(all_m),
            'h2h_sample': len(h2h_m),
            'recent_trend': recent.get('trend', 'stable'),
            'feature_breakdown': breakdown,
        })

    results.sort(key=lambda x: -x['win_probability'])
    return results


def find_nearest_matches(
    matches: list[Match],
    player_id: int,
    current_level: str,
    n: int = 5,
) -> list[dict]:
    """
    特徴量類似度に基づく最近傍試合エビデンスの取得。
    similarity_score: 同大会レベル +2 / 同フォーマット +1
    """
    if not matches:
        return []

    scored: list[tuple[int, Match]] = []
    for m in matches:
        score = 0
        if (m.tournament_level or '') == current_level:
            score += 2
        scored.append((score, m))

    scored.sort(key=lambda x: -x[0])

    result: list[dict] = []
    for sim_score, m in scored[:n]:
        # プレイヤー視点のスコアサマリーを構築
        score_parts: list[str] = []
        for s in sorted(m.sets or [], key=lambda s: s.set_num):
            if m.player_a_id == player_id:
                score_parts.append(f"{s.score_a}-{s.score_b}")
            else:
                score_parts.append(f"{s.score_b}-{s.score_a}")
        score_summary = ', '.join(score_parts) if score_parts else '—'

        date_val = m.date
        date_str = date_val.isoformat() if hasattr(date_val, 'isoformat') else str(date_val)

        result.append({
            'date': date_str,
            'tournament_level': m.tournament_level or '—',
            'result': 'win' if _player_wins_match(m, player_id) else 'loss',
            'score_summary': score_summary,
            'similarity_score': sim_score,
        })

    return result
