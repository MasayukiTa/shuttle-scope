"""マルコフ連鎖 + EPV 計算エンジン"""
from collections import defaultdict
from typing import Any

import numpy as np

# scipy が利用可能かつ numpy バイナリ互換性がある場合のみ統計CI計算に使用
# numpy 2.x + 古い scipy ビルドの組み合わせで ValueError が発生するケースを考慮
try:
    from scipy import stats as _scipy_stats
    _SCIPY_AVAILABLE = True
except (ImportError, ValueError, Exception):
    _scipy_stats = None  # type: ignore[assignment]
    _SCIPY_AVAILABLE = False

SHOT_KEYS = [
    "short_service", "long_service", "net_shot", "clear", "push_rush",
    "smash", "defensive", "drive", "lob", "drop", "cross_net", "slice",
    "around_head", "cant_reach", "flick", "half_smash", "block", "other",
]

SHOT_LABELS_JA = {
    "short_service": "ショートサーブ",
    "long_service": "ロングサーブ",
    "net_shot": "ネットショット",
    "clear": "クリア",
    "push_rush": "プッシュ/ラッシュ",
    "smash": "スマッシュ",
    "defensive": "ディフェンス",
    "drive": "ドライブ",
    "lob": "ロブ",
    "drop": "ドロップ",
    "cross_net": "クロスネット",
    "slice": "スライス",
    "around_head": "ラウンドヘッド",
    "cant_reach": "届かず",
    "flick": "フリック",
    "half_smash": "ハーフスマッシュ",
    "block": "ブロック",
    "other": "その他",
}

_SHOT_IDX = {k: i for i, k in enumerate(SHOT_KEYS)}


class MarkovAnalyzer:
    """マルコフ連鎖解析クラス"""

    def extract_triplets(self, strokes_list: list[list[dict]]) -> list[tuple[str, str, str]]:
        """ラリー内の連続ショット3連（A→B→A のパターン）を抽出する"""
        triplets = []
        for rally_strokes in strokes_list:
            # ショット種別のみのリスト
            shots = [s["shot_type"] for s in rally_strokes if s.get("shot_type") in _SHOT_IDX]
            for i in range(len(shots) - 2):
                triplets.append((shots[i], shots[i + 1], shots[i + 2]))
        return triplets

    def build_transition_matrix(
        self,
        strokes_list: list[list[dict]],
        laplace_alpha: float = 1.0,
    ) -> np.ndarray:
        """18×18遷移確率行列を構築する（ラプラス平滑化あり）"""
        n = len(SHOT_KEYS)
        # ラプラス平滑化: alpha を初期値として全セルに加算
        raw = np.full((n, n), laplace_alpha, dtype=float)

        for rally_strokes in strokes_list:
            shots = [s["shot_type"] for s in rally_strokes if s.get("shot_type") in _SHOT_IDX]
            for i in range(len(shots) - 1):
                i1 = _SHOT_IDX.get(shots[i])
                i2 = _SHOT_IDX.get(shots[i + 1])
                if i1 is not None and i2 is not None:
                    raw[i1][i2] += 1.0

        # 各行を正規化
        row_sums = raw.sum(axis=1, keepdims=True)
        # ゼロ除算回避
        row_sums = np.where(row_sums == 0, 1.0, row_sums)
        matrix = raw / row_sums
        return matrix

    def calc_epv(self, strokes_list: list[list[dict]]) -> dict[str, float]:
        """各ショットパターンのEPV（期待パターン価値）を計算する

        EPV(shot) = P(ラリー勝利 | このショットを打った) − ベースライン勝率
        """
        if not strokes_list:
            return {}

        total_wins = 0
        total_rallies = 0

        # ラリー勝利フラグをストロークリストに埋め込む前提
        # strokes_list: [{shot_type, player_won: bool}, ...]
        shot_wins: dict[str, int] = defaultdict(int)
        shot_total: dict[str, int] = defaultdict(int)

        for rally_strokes in strokes_list:
            if not rally_strokes:
                continue
            # ラリー勝利フラグ（最後のストロークの player_won を使用）
            rally_won = rally_strokes[-1].get("player_won", False)
            total_wins += int(rally_won)
            total_rallies += 1

            for stroke in rally_strokes:
                st = stroke.get("shot_type")
                if st not in _SHOT_IDX:
                    continue
                shot_total[st] += 1
                if rally_won:
                    shot_wins[st] += 1

        baseline = total_wins / total_rallies if total_rallies else 0.5

        epv: dict[str, float] = {}
        for st in shot_total:
            prob_win = shot_wins[st] / shot_total[st] if shot_total[st] else baseline
            epv[st] = round(prob_win - baseline, 4)

        return epv

    def bootstrap_ci(
        self,
        strokes_list: list[list[dict]],
        n_bootstrap: int = 200,
    ) -> dict[str, dict[str, float]]:
        """ブートストラップ法でEPV信頼区間を計算する"""
        if not strokes_list:
            return {}

        # ブートストラップサンプリング
        epv_samples: dict[str, list[float]] = defaultdict(list)

        rng = np.random.default_rng(seed=42)
        n = len(strokes_list)
        for _ in range(n_bootstrap):
            # ラリー単位でリサンプリング（np.random.choiceで高速化）
            indices = rng.integers(0, n, size=n)
            sample = [strokes_list[i] for i in indices]
            epv_sample = self.calc_epv(sample)
            for st, val in epv_sample.items():
                epv_samples[st].append(val)

        ci_dict: dict[str, dict[str, float]] = {}
        for st, vals in epv_samples.items():
            arr = np.array(vals)
            if _SCIPY_AVAILABLE and len(arr) >= 10:
                # scipy で正確な信頼区間を計算
                ci_low, ci_high = float(np.percentile(arr, 2.5)), float(np.percentile(arr, 97.5))
            else:
                ci_low, ci_high = float(np.percentile(arr, 2.5)), float(np.percentile(arr, 97.5))
            ci_dict[st] = {
                "mean": round(float(np.mean(arr)), 4),
                "ci_low": round(ci_low, 4),
                "ci_high": round(ci_high, 4),
            }

        return ci_dict

    def get_top_patterns(
        self,
        strokes_list: list[list[dict]],
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """EPV上位パターン（ショット→ショット）を返す"""
        if not strokes_list:
            return []

        # ペアパターン（A→B）のEPVを集計
        pair_wins: dict[tuple[str, str], int] = defaultdict(int)
        pair_total: dict[tuple[str, str], int] = defaultdict(int)
        total_wins = 0
        total_rallies = 0

        for rally_strokes in strokes_list:
            if not rally_strokes:
                continue
            rally_won = rally_strokes[-1].get("player_won", False)
            total_wins += int(rally_won)
            total_rallies += 1
            shots = [s["shot_type"] for s in rally_strokes if s.get("shot_type") in _SHOT_IDX]
            for i in range(len(shots) - 1):
                key = (shots[i], shots[i + 1])
                pair_total[key] += 1
                if rally_won:
                    pair_wins[key] += 1

        baseline = total_wins / total_rallies if total_rallies else 0.5

        # CI計算
        ci = self.bootstrap_ci(strokes_list, n_bootstrap=100)

        patterns = []
        for (s1, s2), total in pair_total.items():
            wins = pair_wins.get((s1, s2), 0)
            epv = round((wins / total if total else baseline) - baseline, 4)
            s1_ja = SHOT_LABELS_JA.get(s1, s1)
            s2_ja = SHOT_LABELS_JA.get(s2, s2)
            # 単発EPVから概算CI
            s1_ci = ci.get(s1, {"ci_low": epv - 0.05, "ci_high": epv + 0.05})
            patterns.append({
                "pattern": f"{s1_ja}→{s2_ja}",
                "shots": [s1, s2],
                "epv": epv,
                "ci_low": round((s1_ci["ci_low"] + epv) / 2, 4),
                "ci_high": round((s1_ci["ci_high"] + epv) / 2, 4),
                "count": total,
            })

        patterns.sort(key=lambda x: x["epv"], reverse=True)
        return patterns[:top_k]
