"""Expert Labeler: ミスストローク周辺のクリップ切り出し。

ffmpeg を subprocess 呼び出しで起動し、指定ストロークの
timestamp_sec を中心に fps*3 フレーム前 / fps*2 フレーム後の mp4 を生成する。
キャッシュ（ClipCache）に既に登録されていれば再生成せず返す。
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from backend.db.models import ClipCache, Match, Rally, Stroke

logger = logging.getLogger(__name__)

DEFAULT_FPS = 30
# クリップ出力ルート（backend/data/expert_clips/{match_id}/{stroke_id}.mp4）
CLIP_ROOT = Path(__file__).resolve().parent.parent / "data" / "expert_clips"


class ClipGenerationError(Exception):
    """クリップ生成時のエラー。"""


def _resolve_fps(match: Match) -> int:
    """Match.source_fps を優先、未設定なら DEFAULT_FPS。"""
    fps = getattr(match, "source_fps", None)
    try:
        if fps and int(fps) > 0:
            return int(fps)
    except (TypeError, ValueError):
        pass
    return DEFAULT_FPS


def compute_frame_index(timestamp_sec: Optional[float], fps: int) -> int:
    """timestamp_sec * fps を frame_index として算出（None は 0）。"""
    if timestamp_sec is None:
        return 0
    try:
        return max(0, int(round(float(timestamp_sec) * fps)))
    except (TypeError, ValueError):
        return 0


def generate_miss_clip(
    db: Session,
    match_id: int,
    stroke_id: int,
    *,
    force: bool = False,
) -> Optional[ClipCache]:
    """ミスストロークの前後クリップを生成し ClipCache に登録する。

    前 fps*3 フレーム / 後 fps*2 フレーム。ffmpeg 呼び出しに失敗した場合は None。
    既にキャッシュがあれば再生成せず返す（force=True で再生成）。
    """
    # 既存キャッシュチェック
    existing = db.query(ClipCache).filter(ClipCache.stroke_id == stroke_id).one_or_none()
    if existing and not force:
        if Path(existing.clip_path).exists():
            return existing
        # ファイルが消えていれば作り直し
        db.delete(existing)
        db.flush()

    match = db.get(Match, match_id)
    if not match:
        raise ClipGenerationError(f"match_id={match_id} が存在しません")
    if not match.video_local_path:
        raise ClipGenerationError(f"match_id={match_id} に video_local_path がありません")
    # localfile:/// プレフィックスを剥がす（DB 保存形式から OS パスへ）
    raw = match.video_local_path
    if raw.startswith("localfile:///"):
        raw = raw[len("localfile:///"):]
    video_path = Path(raw)
    if not video_path.exists():
        raise ClipGenerationError(f"動画ファイルが存在しません: {video_path}")
    # path_jail: HDD 上の許可外データ（ドローン映像等）への解析誤起動を遮断
    from backend.utils.path_jail import is_allowed_video_path, allowed_video_roots
    if not is_allowed_video_path(video_path):
        roots = [str(r) for r in allowed_video_roots()]
        raise ClipGenerationError(
            f"動画パスが許可ルート外です: {video_path}. 許可ルート: {roots}"
        )

    stroke = db.get(Stroke, stroke_id)
    if not stroke:
        raise ClipGenerationError(f"stroke_id={stroke_id} が存在しません")

    fps = _resolve_fps(match)
    frame_index = compute_frame_index(stroke.timestamp_sec, fps)
    start_frame = max(0, frame_index - fps * 3)
    end_frame = frame_index + fps * 2

    start_sec = start_frame / fps
    duration_sec = max(0.1, (end_frame - start_frame) / fps)

    # 出力先
    out_dir = CLIP_ROOT / str(match_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{stroke_id}.mp4"

    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        raise ClipGenerationError("ffmpeg が PATH に見つかりません")

    from backend.pipeline.clips import _video_encoder, _build_cmd
    encoder, hw_args, enc_args = _video_encoder()
    cmd = _build_cmd(
        ffmpeg_bin, video_path, start_sec, duration_sec, out_path,
        encoder, hw_args, enc_args, ff_threads=4,
    )
    # -an で音声除去 (Expert Labeler クリップは映像のみ)
    if "-c:a" in cmd:
        idx = cmd.index("-c:a")
        cmd[idx:idx+2] = ["-an"]
    logger.info("ffmpeg clip: match=%s stroke=%s encoder=%s", match_id, stroke_id, encoder)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        logger.error("ffmpeg failed: %s", proc.stderr[-2000:] if proc.stderr else "")
        raise ClipGenerationError(f"ffmpeg failed rc={proc.returncode}")

    cache = ClipCache(
        match_id=match_id,
        stroke_id=stroke_id,
        clip_path=str(out_path),
        start_frame=start_frame,
        end_frame=end_frame,
    )
    db.add(cache)
    db.commit()
    db.refresh(cache)
    return cache


def iter_miss_strokes(db: Session, match_id: int):
    """ミスストローク判定プロキシ:
    Rally.end_type IN (unforced_error, forced_error) の
    そのラリーの敗北側（winner の反対）の最終ストロークを返す。
    """
    # match 配下の全 Rally を set 経由で取得
    from backend.db.models import GameSet

    rallies = (
        db.query(Rally)
        .join(GameSet, GameSet.id == Rally.set_id)
        .filter(GameSet.match_id == match_id)
        .filter(Rally.end_type.in_(["unforced_error", "forced_error"]))
        .all()
    )
    results: list[tuple[Rally, Stroke]] = []
    for rally in rallies:
        # winner の反対側がミスした側
        loser = "player_b" if rally.winner == "player_a" else "player_a"
        strokes = (
            db.query(Stroke)
            .filter(Stroke.rally_id == rally.id)
            .order_by(Stroke.stroke_num.desc())
            .all()
        )
        # 敗者側の最終ストロークを探す（partner_x も同一サイド扱い）
        side = loser[-1]  # 'a' or 'b'
        miss = None
        for s in strokes:
            if s.player in (f"player_{side}", f"partner_{side}"):
                miss = s
                break
        # 見つからなければ単純に最終ストローク
        if miss is None and strokes:
            miss = strokes[0]
        if miss is not None:
            results.append((rally, miss))
    return results
