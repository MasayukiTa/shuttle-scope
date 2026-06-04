"""映像ベース時刻同期 (音声に依らない)。Mavic は録音無しのため必須。

両カメラは同じ試合を撮るので、ラリーの激しさ等「全体の動き量(motion-energy)」の
時系列は相関する。2 本の motion-energy 信号を相互相関し、最良ラグ = フレームオフセット。
(iOS/Android で音声がある場合は audio cross-corr が更に高精度。それは driver 側で選択。)
"""
from __future__ import annotations

from typing import Optional, Tuple

import numpy as np


def normalize_signal(sig: np.ndarray) -> np.ndarray:
    sig = np.asarray(sig, dtype=np.float64).ravel()
    sig = sig - sig.mean()
    std = sig.std()
    return sig / std if std > 1e-9 else sig


def cross_correlation_offset(sig1: np.ndarray, sig2: np.ndarray,
                             max_lag: Optional[int] = None) -> Tuple[int, float]:
    """sig2 を sig1 に合わせるラグ (フレーム) と正規化相関スコアを返す。

    返り値 lag>0 は「sig2 は sig1 より lag フレーム遅れている」。
    """
    a = normalize_signal(sig1)
    b = normalize_signal(sig2)
    n = min(len(a), len(b))
    a, b = a[:n], b[:n]
    if max_lag is None:
        max_lag = n - 1
    max_lag = int(min(max_lag, n - 1))
    best_lag, best_score = 0, -np.inf
    for lag in range(-max_lag, max_lag + 1):
        if lag >= 0:
            x, y = a[lag:], b[: n - lag]
        else:
            x, y = a[: n + lag], b[-lag:]
        if len(x) < 2:
            continue
        score = float(np.dot(x, y) / len(x))
        if score > best_score:
            best_score, best_lag = score, lag
    return best_lag, best_score


def motion_energy_from_gray(frames_gray) -> np.ndarray:
    """連続グレースケールフレーム列 → フレーム間差分の平均絶対値 (motion-energy)。

    driver 側で cv2 デコードしたフレームを渡す。ここは numpy のみで純粋・テスト可能。
    """
    frames = [np.asarray(f, dtype=np.float64) for f in frames_gray]
    energies = [0.0]
    for i in range(1, len(frames)):
        energies.append(float(np.mean(np.abs(frames[i] - frames[i - 1]))))
    return np.asarray(energies, dtype=np.float64)
