"""
dr_ope_engine.py — 二重ロバスト オフポリシー評価 (DR-OPE) エンジン (Research)

各ゲーム状態を文脈的バンディットとして扱う:
  - 状態 s: ゲーム状態キー (例: "early|server")
  - 行動 a: ショット種別バケット (例: "smash", "net", …)
  - 報酬 r ∈ {0, 1}: そのラリーで対象選手が勝てば 1

ターゲット方策 π_e を ソフトマックス(Q/temp) で構築し、
行動方策 π_b (実測頻度) と比べた期待報酬の差 (uplift) を
単一ステップ DR 推定量で定量化する。

DR 推定量:
  V_DR = mean_i [ Σ_a π_e(a) q(a)
                  + (π_e(a_i) / π_b(a_i)) * (r_i − q(a_i)) ]

  第一項 = π_e に対するダイレクト・メソッド推定 (全行動期待値の重み付き和)
  第二項 = IPS 補正 (観測行動 a_i の重要度サンプリング残差)

DR 推定量は以下を満たす:
  - q が正確ならダイレクト推定に一致 (IPS 残差がゼロ)
  - π_b が正確なら IPS 推定に一致 (分散を吸収)
  → 一方が正しければ一致性を持つ二重ロバスト性

ブートストラップ CI:
  - q と π_b/π_e はデータ全体で固定 (per-resample 再推定は不安定になりやすいため)
  - 残差項 (π_e(a_i)/π_b(a_i)) * (r_i − q(a_i)) をリサンプリングして分散を推定
  - numpy default_rng(seed) で再現性を保証

設計原則:
  - 純粋関数のみ (DB アクセス無し)
  - numpy 以外の依存無し
  - サンプル数が閾値未満 (デフォルト 20) の状態は None を返す
"""
from __future__ import annotations

from typing import Optional

import numpy as np


# ── 最小サンプル閾値 ─────────────────────────────────────────────────────────

MIN_STATE_SAMPLES = 20


# ── 基本推定関数 ─────────────────────────────────────────────────────────────

def empirical_policy(action_counts: dict[str, int]) -> dict[str, float]:
    """観測行動頻度から行動方策 π_b(a) を推定する (正規化)。

    Args:
        action_counts: {action_label: count} の辞書

    Returns:
        {action_label: probability} の辞書 (和 = 1)
        counts がすべてゼロの場合は一様分布を返す。
    """
    total = sum(action_counts.values())
    if total == 0:
        n = len(action_counts)
        return {a: 1.0 / n for a in action_counts} if n > 0 else {}
    return {a: c / total for a, c in action_counts.items()}


def q_hat(records: list[dict]) -> dict[str, float]:
    """各行動の Laplace 平滑化勝率 q(a) を推定する。

    平滑化: q(a) = (wins_a + 1) / (count_a + 2)
    これにより観測ゼロ行動でも q(a) = 0.5 となり、
    IPS 残差計算での不安定を防ぐ。

    Args:
        records: [{"a": str, "win": 0|1}, ...]

    Returns:
        {action_label: smoothed_win_rate} の辞書
    """
    win_counts: dict[str, int] = {}
    total_counts: dict[str, int] = {}
    for r in records:
        a = r.get("a")
        if a is None:
            continue
        win = int(r.get("win", 0))
        win_counts[a] = win_counts.get(a, 0) + win
        total_counts[a] = total_counts.get(a, 0) + 1
    # Laplace 平滑化: alpha=1 → (wins+1)/(total+2)
    return {
        a: (win_counts.get(a, 0) + 1) / (total_counts.get(a, 0) + 2)
        for a in total_counts
    }


def softmax_target_policy(
    q: dict[str, float],
    temp: float = 0.25,
) -> dict[str, float]:
    """Q 値のソフトマックスからターゲット方策 π_e(a) を構築する。

    π_e(a) = softmax(q(a) / temp)

    temp → 0: 貪欲 (最高 Q 行動に集中)
    temp → ∞: 一様分布 (行動方策に近づく)

    デフォルト temp=0.25 は高 Q 行動に強くマスを寄せながらも
    サポート全体をカバーする適度な集中度。

    Args:
        q: {action_label: q_value} の辞書
        temp: ソフトマックス温度 (> 0)

    Returns:
        {action_label: probability} の辞書 (和 = 1)
    """
    if not q:
        return {}
    actions = list(q.keys())
    values = np.array([q[a] for a in actions], dtype=float)
    # 数値安定化: 最大値を引く (log-sum-exp トリック)
    shifted = (values - values.max()) / max(temp, 1e-9)
    exp_vals = np.exp(shifted)
    probs = exp_vals / exp_vals.sum()
    return {a: float(probs[i]) for i, a in enumerate(actions)}


def direct_value(pi: dict[str, float], q: dict[str, float]) -> float:
    """ダイレクト・メソッドによる期待報酬推定量。

    V_DM(π) = Σ_a π(a) * q(a)

    q に存在しない行動は 0 として扱う。

    Args:
        pi: {action_label: probability}
        q:  {action_label: q_value}

    Returns:
        float 期待報酬推定値
    """
    return sum(p * q.get(a, 0.0) for a, p in pi.items())


def dr_value(
    records: list[dict],
    pi_b: dict[str, float],
    pi_e: dict[str, float],
    q: dict[str, float],
) -> float:
    """単一ステップ DR 推定量を計算する。

    V_DR = mean_i [ Σ_a π_e(a) q(a)
                    + (π_e(a_i) / π_b(a_i)) * (r_i − q(a_i)) ]

    第一項はサンプルによらず定数 (= direct_value(π_e, q))。
    第二項は観測行動の IPS 残差でサンプルごとに変動する。

    IPS クリッピング: π_b(a_i) < 1e-6 のとき重要度比を 0 にクリップし
    極端な発散を防ぐ (coverage 外行動の残差は無視)。

    Args:
        records: [{"a": str, "win": 0|1}, ...]
        pi_b:    行動方策 {action: prob}
        pi_e:    ターゲット方策 {action: prob}
        q:       Q 値推定 {action: q_value}

    Returns:
        float DR 推定値
    """
    dm_term = direct_value(pi_e, q)
    ips_residuals: list[float] = []
    for r in records:
        a = r.get("a")
        if a is None:
            continue
        reward = float(r.get("win", 0))
        pi_b_a = pi_b.get(a, 0.0)
        pi_e_a = pi_e.get(a, 0.0)
        if pi_b_a < 1e-6:
            # π_b でカバーされていない行動: IPS 残差を 0 にクリップ
            ratio = 0.0
        else:
            ratio = pi_e_a / pi_b_a
        q_a = q.get(a, 0.5)
        ips_residuals.append(ratio * (reward - q_a))

    if not ips_residuals:
        return dm_term

    correction = float(np.mean(ips_residuals))
    return dm_term + correction


def bootstrap_ci(
    records: list[dict],
    pi_b: dict[str, float],
    pi_e: dict[str, float],
    q: dict[str, float],
    n_boot: int = 500,
    alpha: float = 0.1,
    seed: int = 0,
) -> tuple[float, float]:
    """DR 推定量のブートストラップ信頼区間を返す。

    設計選択:
      - q, pi_b, pi_e はデータ全体で固定し、リサンプリングでは保持する。
        (per-resample 再推定は高分散かつ小サンプルで不安定になるため)
      - IPS 残差項 (π_e(a_i)/π_b(a_i)) * (r_i − q(a_i)) をリサンプリングして
        dr_value の統計的変動を推定する。
      - numpy default_rng(seed) で再現性を保証。Date/Math.random 等は不使用。

    Args:
        records:  [{"a": str, "win": 0|1}, ...]
        pi_b:     行動方策 (固定)
        pi_e:     ターゲット方策 (固定)
        q:        Q 値推定 (固定)
        n_boot:   ブートストラップ回数
        alpha:    有意水準 (CI は [alpha/2, 1-alpha/2] パーセンタイル)
        seed:     乱数シード (再現性用)

    Returns:
        (ci_low, ci_high): alpha/2 および 1-alpha/2 パーセンタイル点
    """
    rng = np.random.default_rng(seed)
    n = len(records)
    if n == 0:
        return (0.0, 0.0)

    # 各レコードの IPS 残差を事前計算
    dm_term = direct_value(pi_e, q)
    residuals = np.zeros(n, dtype=float)
    for i, r in enumerate(records):
        a = r.get("a")
        if a is None:
            continue
        reward = float(r.get("win", 0))
        pi_b_a = pi_b.get(a, 0.0)
        pi_e_a = pi_e.get(a, 0.0)
        if pi_b_a < 1e-6:
            ratio = 0.0
        else:
            ratio = pi_e_a / pi_b_a
        q_a = q.get(a, 0.5)
        residuals[i] = ratio * (reward - q_a)

    # ブートストラップ: 残差列をリサンプリング
    boot_values = np.zeros(n_boot, dtype=float)
    for b in range(n_boot):
        idx = rng.integers(0, n, size=n)
        boot_values[b] = dm_term + residuals[idx].mean()

    low = float(np.percentile(boot_values, 100.0 * alpha / 2))
    high = float(np.percentile(boot_values, 100.0 * (1.0 - alpha / 2)))
    return (low, high)


# ── ハイレベル API ───────────────────────────────────────────────────────────

def evaluate_state(
    records: list[dict],
    temp: float = 0.25,
    n_boot: int = 500,
    seed: int = 0,
    min_samples: int = MIN_STATE_SAMPLES,
) -> Optional[dict]:
    """1 状態のレコードから DR-OPE 評価結果を返す。

    Args:
        records:     [{"a": str, "win": 0|1}, ...]  (1 状態に属するレコード群)
        temp:        ソフトマックス温度 (高いほど方策が一様に近づく)
        n_boot:      ブートストラップ回数
        seed:        ブートストラップ乱数シード
        min_samples: 最小サンプル数 (未達時は None を返す)

    Returns:
        サンプル十分:
          {
            "n":                int,    # サンプル数
            "value_behavior":   float,  # π_b の期待報酬 (DM)
            "value_target":     float,  # π_e の DR 推定値
            "uplift":           float,  # value_target − value_behavior
            "ci_low":           float,  # value_target の CI 下限
            "ci_high":          float,  # value_target の CI 上限
            "behavior_policy":  dict,   # {action: prob} π_b
            "target_policy":    dict,   # {action: prob} π_e
          }
        サンプル不足: None
    """
    valid = [r for r in records if r.get("a") is not None]
    n = len(valid)
    if n < min_samples:
        return None

    # 行動カウント → π_b
    action_counts: dict[str, int] = {}
    for r in valid:
        a = r["a"]
        action_counts[a] = action_counts.get(a, 0) + 1

    pi_b = empirical_policy(action_counts)
    q = q_hat(valid)
    pi_e = softmax_target_policy(q, temp=temp)

    v_behavior = direct_value(pi_b, q)
    v_target = dr_value(valid, pi_b, pi_e, q)
    uplift = v_target - v_behavior
    ci_low, ci_high = bootstrap_ci(valid, pi_b, pi_e, q, n_boot=n_boot, seed=seed)

    return {
        "n": n,
        "value_behavior": round(v_behavior, 4),
        "value_target": round(v_target, 4),
        "uplift": round(uplift, 4),
        "ci_low": round(ci_low, 4),
        "ci_high": round(ci_high, 4),
        "behavior_policy": {a: round(p, 4) for a, p in pi_b.items()},
        "target_policy": {a: round(p, 4) for a, p in pi_e.items()},
    }
