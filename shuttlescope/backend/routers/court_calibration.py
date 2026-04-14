"""コートキャリブレーション

アノテーター画面のグリッドオーバーレイで設定した 6点（4コーナー＋ネット支柱2点）を
MatchCVArtifact に保存し、以下を計算して返す:

  - ホモグラフィ H  : 画像正規化座標 → コート正規化座標
  - 逆ホモグラフィ  : コート正規化座標 → 画像座標（再描画用）
  - ROI多角形       : YOLO フィルタ用コート境界（4コーナー）
  - ネット位置確認  : キャリブレーション精度のチェック

コート正規化座標:
  TL=(0,0), TR=(1,0), BR=(1,1), BL=(0,1)
  ネット: Y ≈ 0.5
  幅ゾーン: x ∈ [0,1/3] left / [1/3,2/3] center / [2/3,1] right
  奥行ゾーン: y ∈ [0,1/6],[1/6,2/6],[2/6,3/6] A側3段, [3/6,4/6],[4/6,5/6],[5/6,1] B側3段

エンドポイント:
  POST /api/matches/{match_id}/court_calibration
  GET  /api/matches/{match_id}/court_calibration
"""
from __future__ import annotations

import datetime
import json
import logging
from typing import Optional

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from sqlalchemy import text
from backend.db.database import engine, get_db
from backend.db.models import MatchCVArtifact

logger = logging.getLogger(__name__)
router = APIRouter()

# ─── スキーマ ─────────────────────────────────────────────────────────────────

class Point2D(BaseModel):
    x: float
    y: float

class CourtCalibrationRequest(BaseModel):
    """
    points[0]: コート左上 (TL)
    points[1]: コート右上 (TR)
    points[2]: コート右下 (BR)
    points[3]: コート左下 (BL)
    points[4]: ネット左支柱 (NetL)
    points[5]: ネット右支柱 (NetR)
    座標は動画コンテナを [0,1]×[0,1] とした正規化値。
    """
    points: list[Point2D]
    container_width: Optional[int] = None
    container_height: Optional[int] = None

# ─── ホモグラフィ演算 ─────────────────────────────────────────────────────────

def _compute_homography(
    src: list[tuple[float, float]],
    dst: list[tuple[float, float]],
) -> list[list[float]]:
    """4点対応から DLT 法でホモグラフィ行列を計算。3×3 の list[list[float]] を返す。"""
    A = []
    for (x, y), (xp, yp) in zip(src, dst):
        A.append([-x, -y, -1.0, 0.0, 0.0, 0.0, x * xp, y * xp, xp])
        A.append([0.0, 0.0, 0.0, -x, -y, -1.0, x * yp, y * yp, yp])
    _, _, Vt = np.linalg.svd(np.array(A, dtype=np.float64))
    H = Vt[-1].reshape(3, 3)
    return (H / H[2, 2]).tolist()


def _invert_homography(H: list[list[float]]) -> list[list[float]]:
    """ホモグラフィの逆行列（コート座標→画像座標）を返す。"""
    H_inv = np.linalg.inv(np.array(H, dtype=np.float64))
    H_inv /= H_inv[2, 2]
    return H_inv.tolist()


def apply_homography(H: list[list[float]], x: float, y: float) -> tuple[float, float]:
    """正規化座標 (x, y) にホモグラフィを適用して変換後座標を返す。"""
    arr = np.array(H, dtype=np.float64)
    pt = np.array([x, y, 1.0], dtype=np.float64)
    res = arr @ pt
    return float(res[0] / res[2]), float(res[1] / res[2])


def pixel_to_court_zone(
    x_norm: float,
    y_norm: float,
    H: list[list[float]],
) -> dict:
    """
    画像正規化座標 → コート正規化座標 → 18ゾーン情報。

    Returns dict:
      court_x, court_y  : コート正規化座標 [0,1]
      zone_id           : 0-17 (row*3+col)
      zone_name         : 例 "A_front_left"
      side              : 'A' | 'B'
      depth             : 'front' | 'mid' | 'back'
      col               : 'left' | 'center' | 'right'
    """
    cx, cy = apply_homography(H, x_norm, y_norm)
    cx = max(0.0, min(1.0, cx))
    cy = max(0.0, min(1.0, cy))

    col_i = min(int(cx * 3), 2)
    row_i = min(int(cy * 6), 5)

    col_names   = ("left", "center", "right")
    depth_names = ("front", "mid", "back")
    side        = "A" if row_i < 3 else "B"

    return {
        "court_x":   round(cx, 4),
        "court_y":   round(cy, 4),
        "zone_id":   row_i * 3 + col_i,
        "zone_name": f"{side}_{depth_names[row_i % 3]}_{col_names[col_i]}",
        "side":      side,
        "depth":     depth_names[row_i % 3],
        "col":       col_names[col_i],
    }


def is_inside_court(
    x: float,
    y: float,
    polygon: list[list[float]],
) -> bool:
    """
    点 (x, y) がコート多角形の内側にあるかを Ray casting で判定（YOLO ROI フィルタ用）。
    polygon: [[x,y], ...] 正規化座標の頂点リスト
    """
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


# ─── DB ヘルパー ──────────────────────────────────────────────────────────────

def load_calibration_from_db(match_id: int, db: Session) -> Optional[dict]:
    """DB からキャリブレーションを読み込む。未設定なら None。"""
    art = (
        db.query(MatchCVArtifact)
        .filter(
            MatchCVArtifact.match_id == match_id,
            MatchCVArtifact.artifact_type == "court_calibration",
        )
        .first()
    )
    if art and art.summary:
        return json.loads(art.summary)
    return None


def load_calibration_standalone(match_id: int) -> Optional[dict]:
    """バックグラウンドスレッドからキャリブレーションを読み込む（SessionLocal 使用）。"""
    from backend.db.database import SessionLocal
    db = SessionLocal()
    try:
        return load_calibration_from_db(match_id, db)
    except Exception as exc:
        logger.warning("Court calibration load failed: %s", exc)
        return None
    finally:
        db.close()


# ─── エンドポイント ───────────────────────────────────────────────────────────

@router.post("/matches/{match_id}/court_calibration")
def save_court_calibration(
    match_id: int,
    body: CourtCalibrationRequest,
    db: Session = Depends(get_db),
):
    """
    コートキャリブレーション 6点を保存し、ホモグラフィを計算して返す。
    同一 match_id の既存データは上書きされる。
    """
    if len(body.points) != 6:
        raise HTTPException(status_code=400, detail="6点が必要です（4コーナー＋ネット支柱2点）")

    pts = [(p.x, p.y) for p in body.points]

    # 4コーナーからホモグラフィを計算
    # 画像正規化座標(0-1) → コート正規化座標(0-1 の単位正方形)
    src_corners = [pts[0], pts[1], pts[2], pts[3]]
    dst_corners = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    try:
        H     = _compute_homography(src_corners, dst_corners)
        H_inv = _invert_homography(H)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"ホモグラフィ計算エラー: {exc}")

    # ネット支柱のコート座標（精度確認）
    net_l = apply_homography(H, *pts[4])
    net_r = apply_homography(H, *pts[5])
    net_y_avg = (net_l[1] + net_r[1]) / 2.0  # 理想値 = 0.5

    summary_data = {
        "points":         [[p.x, p.y] for p in body.points],
        "homography":     H,
        "homography_inv": H_inv,
        "roi_polygon":    [list(pts[i]) for i in range(4)],  # 4コーナー多角形
        "net_court_coords": {
            "left":  [round(net_l[0], 4), round(net_l[1], 4)],
            "right": [round(net_r[0], 4), round(net_r[1], 4)],
            "y_avg": round(net_y_avg, 4),
        },
        "container_size": {
            "w": body.container_width,
            "h": body.container_height,
        },
        "calibrated_at": datetime.datetime.utcnow().isoformat(),
    }
    summary_json = json.dumps(summary_data, ensure_ascii=False)

    def _upsert(session: Session) -> None:
        existing = (
            session.query(MatchCVArtifact)
            .filter(
                MatchCVArtifact.match_id == match_id,
                MatchCVArtifact.artifact_type == "court_calibration",
            )
            .first()
        )
        if existing:
            existing.summary    = summary_json
            existing.updated_at = datetime.datetime.utcnow()
        else:
            session.add(MatchCVArtifact(
                match_id=match_id,
                artifact_type="court_calibration",
                summary=summary_json,
            ))
        session.commit()

    # upsert — どんなカラム不足でも自己修復してリトライする
    try:
        _upsert(db)
    except Exception as exc:
        logger.warning("court_calibration save failed (%s) — running full migration and retrying", exc)
        db.rollback()
        # 全不足カラムを追加する（冪等）
        try:
            from backend.db.database import add_columns_if_missing
            add_columns_if_missing(engine)
        except Exception as mig_err:
            logger.error("migration failed: %s", mig_err)
        # リトライ（新しいセッションで）
        from backend.db.database import SessionLocal
        retry_db = SessionLocal()
        try:
            _upsert(retry_db)
            logger.info("court_calibration save retry succeeded")
        except Exception as retry_err:
            retry_db.rollback()
            retry_db.close()
            raise HTTPException(
                status_code=500,
                detail=f"DB保存失敗: {retry_err}（初回: {exc}）"
            )
        retry_db.close()

    logger.info(
        "Court calibration saved: match=%d  net_y_avg=%.3f (ideal=0.500)",
        match_id, net_y_avg,
    )
    return {"success": True, "data": summary_data}


@router.get("/matches/{match_id}/court_calibration")
def get_court_calibration(match_id: int, db: Session = Depends(get_db)):
    """コートキャリブレーション取得。未設定の場合は 404。"""
    data = load_calibration_from_db(match_id, db)
    if data is None:
        raise HTTPException(status_code=404, detail="キャリブレーションが設定されていません")
    return {"success": True, "data": data}
