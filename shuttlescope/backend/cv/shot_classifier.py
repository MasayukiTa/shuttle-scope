"""ショット分類（ルールベース・GPU 不要）。

Stroke の既存特徴（shot_type, hit/land zone, is_backhand 等）を基に
軽量ルールでショット種別と確信度を推定する。

rule-v1 (A1-1):
  打点フレーム近傍の PoseFrame が利用可能なら、打球側の肩-肘-手首角・打球側手首の
  高さ・体幹前傾などポーズ特徴を算出し、shot_type と整合する典型フォームに近いほど
  confidence を上げ、外れるほど下げる。PoseFrame が無ければ rule-v0 のルールに
  フォールバックする。学習・外部モデルは導入しない（特徴ベースのヒューリスティック）。
"""
from __future__ import annotations

import statistics
from typing import Any, Optional, Sequence


MODEL_VERSION = "rule-v1"

# MediaPipe Pose ランドマークのインデックス（33点フォーマット）
_LM = {
    "left_shoulder": 11, "right_shoulder": 12,
    "left_elbow": 13, "right_elbow": 14,
    "left_wrist": 15, "right_wrist": 16,
    "left_hip": 23, "right_hip": 24,
}

# shot_type ごとの「典型フォーム」プロファイル。
# wrist_above_shoulder: 打球側手首が肩より上にある（=オーバーヘッド系）ことを期待するか
#   True  → 手首が肩より高いほど整合
#   False → 手首が肩より低い（アンダー/ドライブ系）ほど整合
#   None  → どちらでも可（中立）
# elbow_extended: 肘がよく伸びている（角度大）ほど整合するか
_SHOT_PROFILES: dict[str, dict] = {
    "smash":      {"wrist_above_shoulder": True,  "elbow_extended": True},
    "clear":      {"wrist_above_shoulder": True,  "elbow_extended": True},
    "drop":       {"wrist_above_shoulder": True,  "elbow_extended": False},
    "lob":        {"wrist_above_shoulder": False, "elbow_extended": True},
    "lift":       {"wrist_above_shoulder": False, "elbow_extended": True},
    "drive":      {"wrist_above_shoulder": None,  "elbow_extended": True},
    "net":        {"wrist_above_shoulder": False, "elbow_extended": False},
    "netshot":    {"wrist_above_shoulder": False, "elbow_extended": False},
    "serve":      {"wrist_above_shoulder": False, "elbow_extended": False},
    "push":       {"wrist_above_shoulder": None,  "elbow_extended": False},
}


def _get(obj: Any, key: str, default=None):
    """ORM 属性 / dict のどちらからでも取得する。"""
    val = getattr(obj, key, None)
    if val is None and isinstance(obj, dict):
        val = obj.get(key)
    return val if val is not None else default


def classify_stroke(stroke: Any, pose_frames: Optional[Sequence[Any]] = None) -> dict:
    """Stroke ORM or dict を受け取り、shot_type と confidence を返す。

    Args:
        stroke: Stroke ORM もしくは dict。
        pose_frames: 打点フレーム近傍の PoseFrame（ORM or dict）の列。任意。
            与えられた場合はポーズ特徴で confidence を補正する（rule-v1）。
            None / 空 / 抽出失敗時は rule-v0 のルールにフォールバックする。
    """
    # 既存の shot_type を正とし、軌跡や打点属性から確信度を粗く補正する
    shot_type = _get(stroke, "shot_type") or "unknown"

    base = 0.6
    # バックハンドや around_head は難度が高く、分類曖昧性が上がる
    is_bh = bool(_get(stroke, "is_backhand", False))
    if is_bh:
        base -= 0.1
    # hit_zone があるほど確信度が上がる
    hz = _get(stroke, "hit_zone")
    if hz:
        base += 0.1

    # ── rule-v1: ポーズ特徴による補正（利用可能な場合のみ） ────────────────────
    pose_adj = 0.0
    if pose_frames:
        pose_adj = _pose_confidence_adjustment(shot_type, is_bh, pose_frames)
    base += pose_adj

    confidence = max(0.05, min(0.99, base))
    return {
        "shot_type": shot_type,
        "confidence": float(confidence),
        "model_version": MODEL_VERSION,
    }


# ── ポーズ特徴抽出・補正 ──────────────────────────────────────────────────────

def _pose_confidence_adjustment(
    shot_type: str,
    is_backhand: bool,
    pose_frames: Sequence[Any],
) -> float:
    """ポーズ特徴と shot_type の整合度から confidence 補正量 ∈[-0.2, +0.2] を返す。

    整合（典型フォームに近い）→ 正、乖離 → 負。特徴抽出できなければ 0。
    """
    feats = _extract_pose_features(pose_frames, is_backhand)
    if feats is None:
        return 0.0

    profile = _SHOT_PROFILES.get((shot_type or "").lower())
    if not profile:
        # 未知 shot_type: フォームの明瞭さ（手首-肩の高低差が明確）だけを弱く反映
        clarity = min(1.0, abs(feats["wrist_minus_shoulder_y"]) * 4.0)
        return round((clarity - 0.5) * 0.1, 4)

    score = 0.0
    n = 0

    # (1) 打球側手首の高さ（肩との上下関係）。
    #     画像座標は y が下向きに増加するため、wrist_y < shoulder_y → 手首が上。
    want_above = profile["wrist_above_shoulder"]
    if want_above is not None:
        dy = feats["wrist_minus_shoulder_y"]  # 正: 手首が肩より下 / 負: 手首が肩より上
        if want_above:
            # 手首が肩より上(dy<0)なら整合。tanh で [-1,1] に圧縮。
            score += _squash(-dy * 5.0)
        else:
            score += _squash(dy * 5.0)
        n += 1

    # (2) 肘の伸展（打球側 肩-肘-手首角）。
    want_extended = profile["elbow_extended"]
    if want_extended is not None and feats["elbow_angle"] is not None:
        # 角度 180°=完全伸展。120°を中立点として正規化。
        norm = (feats["elbow_angle"] - 120.0) / 60.0  # 180°→+1, 60°→-1
        norm = max(-1.0, min(1.0, norm))
        score += norm if want_extended else -norm
        n += 1

    # (3) 体幹前傾（攻撃的なオーバーヘッドはやや前傾しやすい）。補助的に弱く加点。
    if profile.get("wrist_above_shoulder") and feats["forward_lean"] is not None:
        score += 0.3 * _squash(feats["forward_lean"] * 4.0)
        n += 0.3

    if n <= 0:
        return 0.0
    mean = score / n
    # ±0.2 の範囲に収める
    return round(max(-0.2, min(0.2, mean * 0.2)), 4)


def _extract_pose_features(
    pose_frames: Sequence[Any],
    is_backhand: bool,
) -> Optional[dict]:
    """近傍 PoseFrame 群から打球側のポーズ特徴を集約する。

    各 PoseFrame の landmarks_json（gzip JSON、pose_storage.decode_landmarks で復元）
    から MediaPipe 33点を取り、フレーム平均で以下を返す:
      - wrist_minus_shoulder_y: 打球側 (手首 y − 肩 y)（正規化座標、+下/−上）
      - elbow_angle: 打球側 肩-肘-手首角（度）
      - forward_lean: 肩中心 y − 腰中心 y（負ほど前傾相当）
    抽出不能なら None。
    """
    from backend.pipeline.pose_storage import decode_landmarks

    wms: list[float] = []
    angles: list[float] = []
    leans: list[float] = []

    for pf in pose_frames:
        raw = _get(pf, "landmarks_json")
        if raw is None and isinstance(pf, dict):
            raw = pf.get("landmarks")
        try:
            lms = decode_landmarks(raw) if not isinstance(raw, list) else raw
        except Exception:
            continue
        if not lms or len(lms) < 25:
            continue

        # 打球側の選択: バックハンドかどうかでは利き手は確定しないが、
        # 「打球側＝より高く上がっている手首側」をフレーム単位で選ぶ近似を採用。
        side = _select_hitting_side(lms)
        if side is None:
            continue
        sh_i, el_i, wr_i = _LM[f"{side}_shoulder"], _LM[f"{side}_elbow"], _LM[f"{side}_wrist"]

        sh = _xy(lms, sh_i)
        el = _xy(lms, el_i)
        wr = _xy(lms, wr_i)
        if sh is None or wr is None:
            continue

        wms.append(wr[1] - sh[1])
        if el is not None:
            ang = _angle(sh, el, wr)
            if ang is not None:
                angles.append(ang)

        # 体幹前傾: 肩中心 y − 腰中心 y
        lsh = _xy(lms, _LM["left_shoulder"]); rsh = _xy(lms, _LM["right_shoulder"])
        lhp = _xy(lms, _LM["left_hip"]);      rhp = _xy(lms, _LM["right_hip"])
        if lsh and rsh and lhp and rhp:
            sh_cy = (lsh[1] + rsh[1]) / 2.0
            hp_cy = (lhp[1] + rhp[1]) / 2.0
            leans.append(sh_cy - hp_cy)

    if not wms:
        return None

    return {
        "wrist_minus_shoulder_y": statistics.mean(wms),
        "elbow_angle": statistics.mean(angles) if angles else None,
        "forward_lean": statistics.mean(leans) if leans else None,
    }


def _select_hitting_side(lms: list) -> Optional[str]:
    """打球側（left/right）をフレーム内で近似選択する。

    より高く上がっている手首（y が小さい側）を打球側とみなす。
    座標が取れなければ None。
    """
    lw = _xy(lms, _LM["left_wrist"])
    rw = _xy(lms, _LM["right_wrist"])
    if lw is None and rw is None:
        return None
    if lw is None:
        return "right"
    if rw is None:
        return "left"
    # y が小さい（=画面上で高い）方を打球側に
    return "left" if lw[1] <= rw[1] else "right"


def _xy(lms: list, idx: int) -> Optional[tuple[float, float]]:
    if idx >= len(lms):
        return None
    p = lms[idx]
    if isinstance(p, dict):
        x, y = p.get("x"), p.get("y")
    elif isinstance(p, (list, tuple)) and len(p) >= 2:
        x, y = p[0], p[1]
    else:
        return None
    if x is None or y is None:
        return None
    try:
        return float(x), float(y)
    except (TypeError, ValueError):
        return None


def _angle(a: tuple, b: tuple, c: tuple) -> Optional[float]:
    """点 b を頂点とする ∠abc を度で返す。"""
    import math
    bax, bay = a[0] - b[0], a[1] - b[1]
    bcx, bcy = c[0] - b[0], c[1] - b[1]
    na = math.hypot(bax, bay)
    nc = math.hypot(bcx, bcy)
    if na < 1e-9 or nc < 1e-9:
        return None
    cos = (bax * bcx + bay * bcy) / (na * nc)
    cos = max(-1.0, min(1.0, cos))
    return math.degrees(math.acos(cos))


def _squash(v: float) -> float:
    """tanh で [-1, 1] に圧縮。"""
    import math
    return math.tanh(v)
