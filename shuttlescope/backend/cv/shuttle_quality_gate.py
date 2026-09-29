"""シャトル検出 信頼度の正直化（quality-gate / A0）。

WASB/TrackNet が報告する raw confidence は過大申告（報告 87% vs 実視覚 17%、
ユニフォーム/ネット誤検出）になりがちで、着地ゾーン等の下流推定を歪める。

本モジュールは検出器の出力（フレーム列）を **後処理** し、以下 2 信号から
品質係数 quality_factor∈[0,1] を算出して raw_conf を減衰させる:

  (a) peak鋭さ (sharpness):
      ヒートマップが利用可能なら単峰性・鋭さ（鋭い単峰=本物 / なだらか・多峰=誤検出疑い）。
      heatmap が無い検出器では、検出スコア（confidence）と位置の局所安定性で近似する。
  (b) 動き整合 (motion):
      前後フレームの検出位置の連続性。シャトルは滑らかに移動するため、
      速度・加速度が物理的に妥当（ジャンプしない）なほど高スコア。

  gated_conf = raw_conf × quality_factor(a, b)

後方互換:
  - SS_SHUTTLE_QUALITY_GATE=0 で完全に無効化（gated_conf == raw_conf、フレーム無改変）。
  - 各重み・閾値も env で上書き可能。既定は ON。
  - WASB/TrackNet モデル本体・検出パイプ構造には一切触れない（純粋な後処理）。

使用するフレーム dict のキー（candidate_builder と同じ表現）:
  - "confidence": float  (raw 検出信頼度)
  - "x_norm" / "y_norm": Optional[float]  (正規化座標 0-1)
  - "timestamp_sec": float
  - "heatmap_peak" / "heatmap_sharpness": Optional[float]  (あれば peak 鋭さに使用)
出力: 各フレームに以下を追記（既存キーは破壊しない）:
  - "raw_confidence": float        (元の confidence を保全)
  - "quality_factor": float        (算出した品質係数)
  - "confidence": float            (= gated_conf。下流はこれを読む)
  - "quality_signals": {"sharpness": float, "motion": float}
"""
from __future__ import annotations

import logging
import math
import os
from typing import Optional

logger = logging.getLogger(__name__)


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off", "")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


# ── ON/OFF と各パラメータ（env 上書き可）─────────────────────────────────────
def gate_enabled() -> bool:
    """quality-gate が有効か（既定 ON）。呼び出し毎に env を読むのでテストで切替容易。"""
    return _env_flag("SS_SHUTTLE_QUALITY_GATE", True)


# sharpness と motion の合成重み（合計 1.0 が目安）。
def _weight_sharpness() -> float:
    return _env_float("SS_SHUTTLE_GATE_W_SHARPNESS", 0.5)


def _weight_motion() -> float:
    return _env_float("SS_SHUTTLE_GATE_W_MOTION", 0.5)


# quality_factor の下限（過度な減衰で全フレーム捨てないための床）。
def _quality_floor() -> float:
    return _env_float("SS_SHUTTLE_GATE_FLOOR", 0.15)


# 動き整合: フレーム間の妥当な最大移動量（正規化座標/フレーム）。
# これを超える瞬間移動は誤検出（ユニフォーム/ネットへの飛び）とみなし motion を下げる。
def _max_step_norm() -> float:
    return _env_float("SS_SHUTTLE_GATE_MAX_STEP", 0.18)


# sharpness 近似に使う、confidence をそのまま鋭さ指標に流用する際のゲイン。
def _sharpness_conf_gain() -> float:
    return _env_float("SS_SHUTTLE_GATE_SHARP_GAIN", 1.0)


# ─────────────────────────────────────────────────────────────────────────────
# (a) peak 鋭さ
# ─────────────────────────────────────────────────────────────────────────────

def _sharpness_score(frame: dict) -> float:
    """フレーム単体の peak 鋭さ ∈[0,1]。

    優先順:
      1. heatmap_sharpness が与えられていればそれを 0-1 にクリップして使う。
      2. heatmap_peak（ピーク値）があれば鋭さの近似として使う。
      3. どちらも無ければ raw confidence を鋭さの代理指標として使う
         （鋭い単峰ほど検出器の confidence は高く出やすい、という弱い仮定）。
    """
    hs = frame.get("heatmap_sharpness")
    if hs is not None:
        try:
            return max(0.0, min(1.0, float(hs)))
        except (TypeError, ValueError):
            pass

    hp = frame.get("heatmap_peak")
    if hp is not None:
        try:
            return max(0.0, min(1.0, float(hp)))
        except (TypeError, ValueError):
            pass

    raw = frame.get("confidence")
    try:
        raw = float(raw)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, raw * _sharpness_conf_gain()))


# ─────────────────────────────────────────────────────────────────────────────
# (b) 動き整合（前後フレームの連続性）
# ─────────────────────────────────────────────────────────────────────────────

def _frame_xy(frame: dict) -> Optional[tuple[float, float]]:
    x = frame.get("x_norm")
    y = frame.get("y_norm")
    if x is None or y is None:
        # WASB/TrackNet によっては x/y のキー名が異なる場合に備える
        x = frame.get("x")
        y = frame.get("y")
    if x is None or y is None:
        return None
    try:
        return float(x), float(y)
    except (TypeError, ValueError):
        return None


def _motion_scores(frames: list[dict]) -> list[float]:
    """各フレームの動き整合スコア ∈[0,1] を時系列順に返す。

    速度（前後位置差）と加速度（速度変化）が物理的に妥当なほど 1 に近い。
    瞬間移動（ユニフォーム/ネットへの飛び）や急激な速度反転は低スコア。
    座標が取れないフレームは中立 0.5 を返す（位置情報が無いだけで penalize しない）。
    """
    n = len(frames)
    if n == 0:
        return []
    xys: list[Optional[tuple[float, float]]] = [_frame_xy(f) for f in frames]
    max_step = max(_max_step_norm(), 1e-6)

    scores: list[float] = []
    for i in range(n):
        cur = xys[i]
        if cur is None:
            scores.append(0.5)
            continue

        # 前後の有効な近傍を探す
        prev = xys[i - 1] if i - 1 >= 0 else None
        nxt = xys[i + 1] if i + 1 < n else None

        steps: list[float] = []
        if prev is not None:
            steps.append(math.hypot(cur[0] - prev[0], cur[1] - prev[1]))
        if nxt is not None:
            steps.append(math.hypot(nxt[0] - cur[0], nxt[1] - cur[1]))

        if not steps:
            # 単独点（前後ともに座標なし）→ 連続性を評価できない、中立
            scores.append(0.5)
            continue

        # 速度の妥当性: step が max_step を超えると線形に 0 へ
        vel_ok = max(0.0, 1.0 - (sum(steps) / len(steps)) / max_step)

        # 加速度の妥当性: 前後 step の差が大きい（急な速度変化）ほど下げる
        if len(steps) == 2:
            accel = abs(steps[0] - steps[1])
            acc_ok = max(0.0, 1.0 - accel / max_step)
        else:
            acc_ok = vel_ok

        scores.append(max(0.0, min(1.0, 0.5 * vel_ok + 0.5 * acc_ok)))
    return scores


# ─────────────────────────────────────────────────────────────────────────────
# 合成
# ─────────────────────────────────────────────────────────────────────────────

def compute_quality_factor(sharpness: float, motion: float) -> float:
    """(a) sharpness と (b) motion から品質係数 ∈[floor,1] を合成する。"""
    ws = _weight_sharpness()
    wm = _weight_motion()
    total = ws + wm
    if total <= 0:
        factor = 0.5 * sharpness + 0.5 * motion
    else:
        factor = (ws * sharpness + wm * motion) / total
    floor = _quality_floor()
    return max(floor, min(1.0, factor))


def gate_frames(frames: list[dict]) -> list[dict]:
    """検出フレーム列に quality-gate を適用した **新しいリスト** を返す。

    - SS_SHUTTLE_QUALITY_GATE=0 のときは入力をそのまま返す（無改変・従来挙動）。
    - ON のときは各フレームを浅いコピーし、confidence を gated_conf に置換、
      raw_confidence / quality_factor / quality_signals を追記する。
      入力リスト・各 dict は破壊しない。
    """
    if not frames:
        return frames
    if not gate_enabled():
        return frames

    motion_scores = _motion_scores(frames)
    gated: list[dict] = []
    for i, f in enumerate(frames):
        raw = f.get("confidence")
        try:
            raw = float(raw)
        except (TypeError, ValueError):
            raw = 0.0
        sharp = _sharpness_score(f)
        motion = motion_scores[i] if i < len(motion_scores) else 0.5
        factor = compute_quality_factor(sharp, motion)
        gated_conf = round(raw * factor, 4)

        nf = dict(f)
        nf["raw_confidence"] = raw
        nf["quality_factor"] = round(factor, 4)
        nf["quality_signals"] = {
            "sharpness": round(sharp, 4),
            "motion": round(motion, 4),
        }
        nf["confidence"] = gated_conf
        gated.append(nf)

    if logger.isEnabledFor(logging.DEBUG):
        try:
            avg_raw = sum(g["raw_confidence"] for g in gated) / len(gated)
            avg_gated = sum(g["confidence"] for g in gated) / len(gated)
            logger.debug(
                "shuttle quality-gate: n=%d avg_raw=%.3f avg_gated=%.3f",
                len(gated), avg_raw, avg_gated,
            )
        except Exception:
            pass
    return gated
