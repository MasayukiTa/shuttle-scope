"""
conformal_engine.py — 分布フリー保証付き予測区間 (split-conformal prediction)

バドミントンのラリー勝敗に対して split-conformal 法を適用する。
ラプラス平滑化した経験的勝率をベーススコアラーとし、
「目標誤差率 alpha 以下」という分布フリーな周辺被覆保証を与える。

設計原則:
  - 純粋関数のみ (DB アクセスなし)。numpy 以外の依存なし。
  - 決定論的分割: 呼び出し側が事前に校正用・テスト用配列を渡す。
  - 予測集合: {"win"} / {"loss"} / {"win","loss"} のいずれか。
    {"win","loss"} は「棄権」= 保証を維持するためのカバレッジ確保。
"""
from __future__ import annotations

import math
from typing import Sequence

import numpy as np


# ── ベーススコアラー: グループ別ラプラス平滑化勝率 ─────────────────────────────

def fit_group_winrates(
    groups: Sequence[str],
    wins: Sequence[int],
    *,
    alpha_laplace: float = 1.0,
) -> dict[str, float]:
    """グループキー別に Laplace 平滑化した P(win) を推定する。

    groups: 各サンプルのグループキー文字列
    wins:   0/1 ラベル (1=勝ち)
    alpha_laplace: ラプラス疑似カウント (デフォルト 1.0)

    返り値: {group_key: p_win}
    未観測グループは 0.5 に倒れる (Laplace 両側疑似カウント)。
    """
    count: dict[str, int] = {}
    win_count: dict[str, int] = {}
    for g, w in zip(groups, wins):
        count[g] = count.get(g, 0) + 1
        win_count[g] = win_count.get(g, 0) + int(w)

    result: dict[str, float] = {}
    for g in count:
        n = count[g]
        w = win_count[g]
        # (w + alpha) / (n + 2*alpha) — n=0 なら 0.5
        result[g] = (w + alpha_laplace) / (n + 2.0 * alpha_laplace)
    return result


def predict_p_win(
    group: str,
    winrate_map: dict[str, float],
) -> float:
    """グループキーから P(win) を返す。未知グループは 0.5。"""
    return winrate_map.get(group, 0.5)


# ── split-conformal 手順 ────────────────────────────────────────────────────

def split_conformal(
    p_hat_cal: np.ndarray,
    y_cal: np.ndarray,
    alpha: float,
) -> float:
    """split-conformal の校正分位点 q を返す。

    非適合スコア: s_i = 1 - p̂(y_i)
      = y_i=1 (win) のとき 1 - p̂_win
      = y_i=0 (loss) のとき 1 - (1 - p̂_win) = p̂_win

    校正分位点: q = ceil((n_cal + 1)(1 - alpha)) / n_cal 番目の経験的分位点。
    有限サンプル補正を含むため、テスト点での被覆率 >= 1 - alpha が (周辺的に) 保証される。

    引数:
        p_hat_cal: 校正集合各点の P(win) 予測値 (shape [n_cal])
        y_cal:     校正集合の真のラベル {0, 1} (shape [n_cal])
        alpha:     目標誤差率 (例: 0.1 → 90% 被覆目標)

    返り値:
        q (float): 校正分位点。新規点の予測集合構築に使う。
    """
    p_hat_cal = np.asarray(p_hat_cal, dtype=float)
    y_cal = np.asarray(y_cal, dtype=float)
    n_cal = len(p_hat_cal)
    if n_cal == 0:
        return 1.0  # データなしは常に abstain

    # 非適合スコア
    p_true_label = np.where(y_cal == 1, p_hat_cal, 1.0 - p_hat_cal)
    scores = 1.0 - p_true_label  # s_i ∈ [0, 1]

    # 有限サンプル補正分位点レベル
    level = math.ceil((n_cal + 1) * (1.0 - alpha)) / n_cal
    level = min(level, 1.0)  # クリップ

    q = float(np.quantile(scores, level))
    return q


def prediction_set(p_win: float, q: float) -> list[str]:
    """新規点の予測集合を返す。

    ラベル l ∈ {win, loss} を集合に含める条件:
        1 - p̂(l) <= q
      ≡ p̂(l) >= 1 - q

    win  を含む: p_win  >= 1 - q
    loss を含む: (1 - p_win) >= 1 - q  ≡ p_win <= q

    返り値: サブセット (順序は loss → win で固定)
    """
    threshold = 1.0 - q
    result: list[str] = []
    if p_win <= q:          # loss の nonconformity score = p_win <= q
        result.append("loss")
    if p_win >= threshold:  # win の nonconformity score = 1 - p_win <= q
        result.append("win")
    return result


def evaluate_coverage(
    p_hat_test: np.ndarray,
    y_test: np.ndarray,
    q: float,
) -> dict:
    """テスト集合での経験的被覆率と平均集合サイズを計算する。

    「被覆」= 真のラベルが予測集合に含まれる割合。
    これが >= 1 - alpha になれば保証が実証的にも成立している。

    返り値:
        empirical_coverage: 経験的被覆率
        avg_set_size:       平均予測集合サイズ (1 = singleton, 2 = abstain)
        n:                  テストサンプル数
    """
    p_hat_test = np.asarray(p_hat_test, dtype=float)
    y_test = np.asarray(y_test, dtype=float)
    n = len(p_hat_test)
    if n == 0:
        return {"empirical_coverage": None, "avg_set_size": None, "n": 0}

    covered = 0
    total_set_size = 0.0

    for p_win, y in zip(p_hat_test, y_test):
        pset = prediction_set(float(p_win), q)
        size = len(pset)
        total_set_size += size
        label = "win" if int(y) == 1 else "loss"
        if label in pset:
            covered += 1

    empirical_coverage = covered / n
    avg_set_size = total_set_size / n

    return {
        "empirical_coverage": round(empirical_coverage, 4),
        "avg_set_size": round(avg_set_size, 4),
        "n": n,
    }
