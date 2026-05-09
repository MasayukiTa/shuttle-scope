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
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from sqlalchemy import text
from backend.db.database import engine, get_db
from backend.db.models import Match, MatchCVArtifact

logger = logging.getLogger(__name__)
router = APIRouter()

# ─── スキーマ ─────────────────────────────────────────────────────────────────

class Point2D(BaseModel):
    # mass-assignment 防御 + 正規化座標 [0,1] + NaN/Inf 拒否。
    # round 224 H1 で発見した経路の対策:
    #   - x/y が [0,1] 範囲外 (例: 1.5) → 200 で受理されコート外へ matrix 計算
    #   - x/y に NaN / Inf → np.linalg.svd が "did not converge" で 500 リーク
    model_config = {"extra": "forbid"}
    x: float = Field(..., ge=0.0, le=1.0, allow_inf_nan=False)
    y: float = Field(..., ge=0.0, le=1.0, allow_inf_nan=False)

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
    model_config = {"extra": "forbid"}
    # points 数は 6 固定。配列長検証も Pydantic 層で行う (旧コードは handler で検査)。
    points: list[Point2D] = Field(..., min_length=6, max_length=6)
    # container 解像度はピクセル値。8K (7680x4320) を上限に正の整数に制限。
    container_width: Optional[int] = Field(default=None, ge=1, le=8192)
    container_height: Optional[int] = Field(default=None, ge=1, le=8192)

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
    request: Request,
    db: Session = Depends(get_db),
):
    """
    コートキャリブレーション 6点を保存し、ホモグラフィを計算して返す。
    同一 match_id の既存データは上書きされる。

    Round 258 R8 P1 fix (deep audit V-2):
    旧コードは Request を取らず middleware (TeamScopeAccessControlMiddleware) のみに
    依存していた。team_id=None の analyst (legacy / pending-team) は middleware が
    skip するため cross-team の match の calibration を上書き可能だった。
    """
    from backend.utils.auth import get_auth as _ga_cc, user_can_access_match as _uac_cc
    _ctx_cc = _ga_cc(request)
    if _ctx_cc.role is None:
        raise HTTPException(status_code=401, detail="認証が必要です")
    # Round 258 R12 P0 fix: R11 で `user_id is None` を required にしたが、これは
    # 以下の正当ケースを破壊していた:
    #   - bootstrap select login (sub=0 → user_id=None で AuthCtx 生成)
    #   - Electron loopback X-Role fallback (allow_legacy_header_auth 通過時)
    # X-Role 経路は既に control_plane 側で loopback + (optional) operator token に
    # gate されているため、ここで二重に user_id を要求すると正規ユーザを 401 にする。
    # admin 強権限への昇格だけ追加で防御する形に直す。
    if _ctx_cc.is_admin and _ctx_cc.user_id is None:
        # admin role を主張するが JWT sub が無い = X-Role spoof or bootstrap token。
        # admin write は厳格に拒否し、analyst/coach 以下にダウングレード扱いにはしない。
        raise HTTPException(status_code=401, detail="認証が必要です (admin には JWT が必要)")
    _m_cc = db.get(Match, match_id)
    if _m_cc is None:
        raise HTTPException(status_code=404, detail="試合が見つかりません")
    if not _ctx_cc.is_admin and not _uac_cc(_ctx_cc, _m_cc):
        raise HTTPException(status_code=404, detail="試合が見つかりません")
    # team_id None の analyst/coach は cross-team write を許さない
    if (_ctx_cc.is_coach or _ctx_cc.is_analyst) and _ctx_cc.team_id is None:
        raise HTTPException(status_code=403, detail="team_id 未設定のためキャリブレーションを保存できません")

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
    except Exception:
        # Round 258 R12 P2 fix (NEW-4): exc を detail に晒すと numpy / file path /
        # version 情報が漏れる。stable な opaque message に統一し、詳細はサーバ log のみ。
        logger.exception("ホモグラフィ計算 failed match_id=%s", match_id)
        raise HTTPException(status_code=500, detail="ホモグラフィ計算に失敗しました")

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
def get_court_calibration(match_id: int, request: Request, db: Session = Depends(get_db)):
    """コートキャリブレーション取得。未設定の場合は 404。

    Round 258 R10/R11 P0 fix (regression audit): 旧コードは Request を取らず middleware
    任せだった。R8 で POST 側に team scope check を入れたが GET 側の sibling は
    未対応で、player を含む任意ユーザが他チーム match のホモグラフィ・6点座標・
    ROI ポリゴンを読めていた (cross-team intelligence leak)。POST と同じ scope を
    適用する。
    R11 追加: X-Role header fallback 経由で `is_admin=True, user_id=None` 状態の擬装が
    残らないように `user_id is not None` を必ず要求する。
    """
    from backend.utils.auth import get_auth as _ga_cc_get, user_can_access_match as _uac_cc_get
    _ctx = _ga_cc_get(request)
    if _ctx.role is None:
        raise HTTPException(status_code=401, detail="認証が必要です")
    # Round 258 R12 P0 fix: 同上 — admin 主張時のみ user_id 要求 (bootstrap/X-Role
    # 経由で role=admin を擬装する経路を遮断、analyst/coach の正規 X-Role loopback は維持)
    if _ctx.is_admin and _ctx.user_id is None:
        raise HTTPException(status_code=401, detail="認証が必要です (admin には JWT が必要)")
    _m = db.get(Match, match_id)
    if _m is None:
        raise HTTPException(status_code=404, detail="試合が見つかりません")
    if not _ctx.is_admin and not _uac_cc_get(_ctx, _m):
        raise HTTPException(status_code=404, detail="試合が見つかりません")
    data = load_calibration_from_db(match_id, db)
    if data is None:
        raise HTTPException(status_code=404, detail="キャリブレーションが設定されていません")
    return {"success": True, "data": data}
