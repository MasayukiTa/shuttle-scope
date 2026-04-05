"""ショット影響度スコア計算エンジン（アナリスト/コーチ向け）"""
from collections import defaultdict
from typing import Any

# sklearn が利用可能かチェック
try:
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import OneHotEncoder
    import numpy as np
    _SKLEARN_AVAILABLE = True
except ImportError:
    _SKLEARN_AVAILABLE = False
    import numpy as np


SHOT_KEYS = [
    "short_service", "long_service", "net_shot", "clear", "push_rush",
    "smash", "defensive", "drive", "lob", "drop", "cross_net", "slice",
    "around_head", "cant_reach", "flick", "half_smash", "block", "other",
]

# ショット品質の重みマップ（ヒューリスティック）
_SHOT_QUALITY_WEIGHT = {
    "excellent": 1.5,
    "good": 1.2,
    "neutral": 1.0,
    "poor": 0.6,
}

# ショット種別の攻撃力スコア（ヒューリスティックEPV概算）
_SHOT_ATTACK_WEIGHT = {
    "smash": 0.85,
    "push_rush": 0.80,
    "half_smash": 0.75,
    "drop": 0.70,
    "cross_net": 0.65,
    "flick": 0.60,
    "net_shot": 0.55,
    "drive": 0.50,
    "slice": 0.45,
    "around_head": 0.50,
    "block": 0.40,
    "clear": 0.35,
    "lob": 0.30,
    "defensive": 0.25,
    "long_service": 0.40,
    "short_service": 0.55,
    "cant_reach": 0.0,
    "other": 0.40,
}


class ShotInfluenceAnalyzer:
    """ショット影響度スコア解析クラス"""

    def compute_heuristic_influence(
        self,
        strokes: list[dict],
        rally_won: bool,
    ) -> list[dict]:
        """ヒューリスティック法でショット影響度を計算する

        影響度 = ポジション係数 × ショット攻撃力 × 品質係数 × (勝利ラリーなら1.2)
        """
        results = []
        n = len(strokes)
        win_mult = 1.2 if rally_won else 0.8

        for i, stroke in enumerate(strokes):
            shot_type = stroke.get("shot_type", "other")
            quality = stroke.get("shot_quality") or "neutral"

            # ラリー内のポジション係数（後半ほど重要）
            position_coef = (i + 1) / n if n > 0 else 1.0
            attack_weight = _SHOT_ATTACK_WEIGHT.get(shot_type, 0.4)
            quality_weight = _SHOT_QUALITY_WEIGHT.get(quality, 1.0)

            influence = round(
                position_coef * attack_weight * quality_weight * win_mult, 4
            )
            results.append({
                "stroke_id": stroke.get("id"),
                "stroke_num": stroke.get("stroke_num"),
                "shot_type": shot_type,
                "influence_score": min(influence, 1.0),
            })

        return results

    def compute_logistic_influence(
        self,
        all_rallies: list[dict],
    ) -> dict[str, float]:
        """ロジスティック回帰でショット種別ごとの影響度を計算する

        all_rallies: [{strokes: [{shot_type, stroke_num, score_diff}], won: bool}]
        Returns: {shot_type: influence_coefficient}
        """
        if not _SKLEARN_AVAILABLE:
            # フォールバック: ヒューリスティック平均
            return {st: _SHOT_ATTACK_WEIGHT.get(st, 0.4) for st in SHOT_KEYS}

        X_rows = []
        y_labels = []

        for rally in all_rallies:
            won = int(rally.get("won", False))
            for stroke in rally.get("strokes", []):
                st = stroke.get("shot_type", "other")
                stroke_num = stroke.get("stroke_num", 1)
                score_diff = stroke.get("score_diff", 0)

                # ワンホットエンコード（ショット種別インデックス）
                shot_idx = SHOT_KEYS.index(st) if st in SHOT_KEYS else len(SHOT_KEYS) - 1
                row = [0.0] * len(SHOT_KEYS)
                row[shot_idx] = 1.0
                row.append(float(stroke_num))
                row.append(float(score_diff))

                X_rows.append(row)
                y_labels.append(won)

        if len(X_rows) < 10:
            return {st: _SHOT_ATTACK_WEIGHT.get(st, 0.4) for st in SHOT_KEYS}

        try:
            X = np.array(X_rows, dtype=float)
            y = np.array(y_labels, dtype=int)
            model = LogisticRegression(max_iter=200, C=1.0)
            model.fit(X, y)

            coefs = model.coef_[0][:len(SHOT_KEYS)]
            # 係数を0-1に正規化
            min_c = coefs.min()
            max_c = coefs.max()
            rng = max_c - min_c if max_c != min_c else 1.0
            normalized = {st: round(float((coefs[i] - min_c) / rng), 4) for i, st in enumerate(SHOT_KEYS)}
            return normalized
        except Exception:
            return {st: _SHOT_ATTACK_WEIGHT.get(st, 0.4) for st in SHOT_KEYS}
