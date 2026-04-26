"""ShuttleScope FastAPI メインアプリケーション"""
import sys
import os

# Windows の CP932 デフォルトエンコーディングを UTF-8 に強制する。
# Electron の Node.js 側が data.toString('utf8') で受け取るため、
# stdout/stderr ともに UTF-8 で出力しなければ日本語が文字化けする。
if sys.platform == "win32":
    import io as _io
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = _io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Windows マルチノード Ray クラスタを有効化
os.environ.setdefault("RAY_ENABLE_WINDOWS_OR_OSX_CLUSTER", "1")

# `python backend/main.py` で直接実行された場合でも
# shuttlescope/ をルートとしてimportできるようパスを追加
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

# PyTorch 同梱の CUDA/cuDNN DLL を ONNX Runtime GPU が見つけられるようにする。
# Windows は Python 3.8+ で secure DLL search を導入したため、PATH だけでなく
# os.add_dll_directory() 経由で登録する必要がある。
try:
    import torch as _torch
    _torch_lib = os.path.join(os.path.dirname(_torch.__file__), "lib")
    if os.path.isdir(_torch_lib):
        if _torch_lib not in os.environ.get("PATH", ""):
            os.environ["PATH"] = _torch_lib + os.pathsep + os.environ.get("PATH", "")
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(_torch_lib)
except Exception:
    pass

import asyncio
import logging

# ── ロギング設定（Electron コンソールへ全ログを流す） ─────────────────────────
# basicConfig は最初の呼び出しのみ有効。uvicorn が先に設定した場合は force=True で上書き。
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
    force=True,
)
# uvicorn のアクセスログはノイズが多いので WARNING に落とす
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
# Ray 内部ワーカーの接続リトライログを抑制（クラスタ未使用時の spam 防止）
logging.getLogger("ray").setLevel(logging.WARNING)
logging.getLogger("ray.worker").setLevel(logging.WARNING)
logging.getLogger("ray._private.worker").setLevel(logging.WARNING)
import mimetypes
import uvicorn
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query, WebSocket

# Windows では .js の MIME タイプが未登録の場合があり type="module" が動作しないため追加
# （StaticFiles の明示ルートによる直接指定と併用）
mimetypes.add_type('application/javascript', '.js')
mimetypes.add_type('application/javascript', '.mjs')
mimetypes.add_type('text/css', '.css')

logger = logging.getLogger(__name__)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response as StarletteResponse
from fastapi.staticfiles import StaticFiles

from backend.config import settings as app_settings
from backend.db.database import engine, get_db, bootstrap_database
from backend.routers import matches, rallies, strokes, players, analysis, reports, sets, tracknet
from backend.routers import settings as settings_router
from backend.routers import sessions, comments, bookmarks, network_diag, warmup
from backend.routers import prediction, tunnel
from backend.routers import human_forecast
from backend.routers import sync as sync_router
from backend.routers import yolo
from backend.routers import cv_candidates
from backend.routers import cv_benchmark
from backend.routers import video_import
from backend.routers import court_calibration
from backend.routers import conditions as conditions_router
from backend.routers import condition_tags as condition_tags_router
from backend.routers import expert as expert_router
from backend.routers import db_maintenance as db_maintenance_router
from backend.routers import review as review_router
from backend.routers import data_package as data_package_router
from backend.routers import cluster as cluster_router
from backend.routers import auth as auth_router
from backend.routers import public_site
from backend.routers import uploads as uploads_router
from backend.utils.video_downloader import video_downloader
from backend.utils import response_cache
import json as _json_cache

# React renderer ビルド出力パス（Electron / ブラウザ共用）
_RENDERER_DIR = Path(__file__).resolve().parent.parent / "out" / "renderer"


async def _stale_device_cleanup():
    """60 秒以上ハートビートがないデバイスを is_connected=False にする（30 秒ごと）"""
    from backend.db.database import SessionLocal
    from backend.db.models import SessionParticipant
    while True:
        await asyncio.sleep(30)
        try:
            # try/finally で確実にセッションを返却（30秒毎ループでの蓄積リーク防止）
            with SessionLocal() as db:
                cutoff = datetime.utcnow() - timedelta(seconds=60)
                stale = (
                    db.query(SessionParticipant)
                    .filter(
                        SessionParticipant.is_connected.is_(True),
                        SessionParticipant.last_heartbeat.isnot(None),
                        SessionParticipant.last_heartbeat < cutoff,
                    )
                    .all()
                )
                for p in stale:
                    p.is_connected = False
                    logger.debug("stale device disconnected: participant_id=%d", p.id)
                if stale:
                    db.commit()
        except Exception as exc:
            logger.warning("stale cleanup error: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """アプリ起動時にテーブル作成 + stale cleanup タスク開始"""
    try:
        loop = asyncio.get_event_loop()
        await asyncio.wait_for(
            loop.run_in_executor(None, lambda: bootstrap_database(None, app_settings.DATABASE_URL)),
            timeout=30.0,
        )
    except asyncio.TimeoutError:
        logger.warning("bootstrap_database がタイムアウト（30s）— 起動を続行します")
    except Exception as exc:
        logger.warning("bootstrap_database エラー: %s — 起動を続行します", exc)

    # 期限切れ AnalysisCache 行をクリーンアップ（起動時のみ）
    try:
        from backend.db.database import SessionLocal
        from backend.db.models import AnalysisCache
        with SessionLocal() as _s:
            _s.query(AnalysisCache).filter(AnalysisCache.expires_at < datetime.utcnow()).delete()
            _s.commit()
    except Exception as exc:
        logger.debug("AnalysisCache cleanup skipped: %s", exc)

    # 期限切れ JWT ブラックリストエントリをクリーンアップ（起動時のみ）
    try:
        from backend.utils.jwt_utils import cleanup_expired_revoked_tokens
        deleted = cleanup_expired_revoked_tokens()
        if deleted:
            logger.info("revoked_tokens cleanup: %d expired entries removed", deleted)
    except Exception as exc:
        logger.debug("revoked_tokens cleanup skipped: %s", exc)

    # ── INFRA Phase A: GPU ヘルスプローブ ────────────────────────────────────
    try:
        from backend.services import gpu_health
        status = gpu_health.probe()
        logger.info("[INFRA] gpu_health.probe: %s", status)
    except Exception as exc:
        logger.debug("[INFRA] gpu_health.probe skipped: %s", exc)

    # ── INFRA Phase B: JobRunner 起動 ─────────────────────────────────────
    try:
        from backend.pipeline.jobs import start_job_runner  # type: ignore
        start_job_runner()
    except ImportError:
        pass
    except Exception as exc:
        logger.debug("[INFRA] start_job_runner skipped: %s", exc)

    # ── INFRA Phase D: Ray クラスタ自動検出 ──────────────────────────────
    # クラスタモードが primary / ray のとき、起動済み Ray を自動検出して接続フラグを立てる
    def _auto_detect_ray():
        try:
            from backend.cluster import topology as _topo
            from backend.cluster.bootstrap import (
                subprocess_ray_status, mark_ray_connected,
                _find_ray_cmd, _subprocess_kwargs,
            )
            import subprocess as _sp, time as _time

            mode = _topo.get_mode()
            if mode not in ("primary", "ray"):
                return

            status = subprocess_ray_status()
            if status.get("running"):
                mark_ray_connected()
                logger.info("[INFRA] Ray クラスタ自動検出: active_nodes=%d", status.get("active_count", 0))
                return

            # ray.auto_start: true の場合は ray start --head を自動実行
            cfg = _topo.load_config()
            if not cfg.get("ray", {}).get("auto_start"):
                logger.debug("[INFRA] Ray 未起動・auto_start 無効のためスキップ")
                return

            primary_ip = cfg.get("network", {}).get("primary_ip", "")
            if not primary_ip:
                logger.warning("[INFRA] auto_start: primary_ip 未設定のため Ray 自動起動をスキップ")
                return
            # Command-injection 防止: primary_ip を IP アドレスとして検証
            import ipaddress as _ipaddr
            try:
                primary_ip = str(_ipaddr.ip_address(primary_ip))
            except (ValueError, TypeError):
                logger.warning("[INFRA] auto_start: primary_ip が不正 (%r) のためスキップ", primary_ip)
                return

            logger.info("[INFRA] auto_start: ray start --head を実行 ip=%s", primary_ip)
            import os as _os
            env = _os.environ.copy()
            env["RAY_ENABLE_WINDOWS_OR_OSX_CLUSTER"] = "1"
            ray_cmd = _find_ray_cmd()
            kw = _subprocess_kwargs()
            kw["env"] = env
            # int 強制で command-injection 防止
            _raw_cpus = cfg.get("ray", {}).get("num_cpus")
            _raw_gpus = cfg.get("ray", {}).get("num_gpus")
            try:
                num_cpus = int(_raw_cpus) if _raw_cpus is not None else None
            except (ValueError, TypeError):
                num_cpus = None
            try:
                num_gpus = int(_raw_gpus) if _raw_gpus is not None else None
            except (ValueError, TypeError):
                num_gpus = None
            cmd = [ray_cmd, "start", "--head",
                   f"--node-ip-address={primary_ip}", "--port=6379",
                   "--dashboard-host=0.0.0.0"]
            if num_cpus is not None:
                cmd.append(f"--num-cpus={num_cpus}")
            if num_gpus is not None:
                cmd.append(f"--num-gpus={num_gpus}")
            result = _sp.run(cmd, **kw)
            if result.returncode == 0:
                _time.sleep(2)
                if subprocess_ray_status().get("running"):
                    mark_ray_connected()
                    logger.info("[INFRA] auto_start: Ray head 起動成功")
            else:
                logger.warning("[INFRA] auto_start: ray start 失敗: %s", result.stderr)
        except Exception as exc:
            logger.debug("[INFRA] Ray 自動検出スキップ: %s", exc)

    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _auto_detect_ray)
    except Exception as exc:
        logger.debug("[INFRA] _auto_detect_ray skipped: %s", exc)

    cleanup_task = asyncio.create_task(_stale_device_cleanup())

    # 分割アップロードのアイドル GC
    try:
        from backend.routers.uploads import gc_loop as _uploads_gc_loop
        uploads_gc_task = asyncio.create_task(_uploads_gc_loop())
    except Exception as exc:
        logger.debug("uploads GC skipped: %s", exc)
        uploads_gc_task = None

    yield
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    if uploads_gc_task is not None:
        uploads_gc_task.cancel()
        try:
            await uploads_gc_task
        except asyncio.CancelledError:
            pass


# PUBLIC_MODE=True または HIDE_API_DOCS=True ではドキュメントエンドポイントを無効化
_hide_docs   = app_settings.PUBLIC_MODE or app_settings.HIDE_API_DOCS
_docs_url    = None if _hide_docs else "/docs"
_redoc_url   = None if _hide_docs else "/redoc"
_openapi_url = None if _hide_docs else "/openapi.json"


# ─── タイムゾーン整合: naive datetime を UTC として ISO+"Z" で返す ─────────────
# backend は datetime.utcnow() で naive UTC 値を保存している。フロントの
# JavaScript Date() が "Z" suffix を見て自動で local TZ (JST 等) に変換できるよう、
# JSON シリアライズ時にすべての naive datetime に UTC 識別子を付与する。
#
# FastAPI は response 作成前に fastapi.encoders.jsonable_encoder を呼ぶため、
# ENCODERS_BY_TYPE のグローバルマップを上書きすることで全エンドポイントに
# 影響を与える。Pydantic v2 のモデル経由でも、最終的に jsonable_encoder を
# 通すため共通的に適用される。
from datetime import datetime as _dt_iso
from fastapi.encoders import ENCODERS_BY_TYPE as _FA_ENCODERS

def _serialize_datetime(value):
    if value.tzinfo is None:
        return value.isoformat() + "Z"
    return value.isoformat()

_FA_ENCODERS[_dt_iso] = _serialize_datetime


app = FastAPI(
    title="ShuttleScope API",
    version="1.0.0",
    description="バドミントン動画アノテーション・解析API",
    lifespan=lifespan,
    docs_url=_docs_url,
    redoc_url=_redoc_url,
    openapi_url=_openapi_url,
)

# Phase B で実装される pipeline ルーター。未実装なら何もしない。
try:
    from backend.routers import pipeline as _pipeline_router  # type: ignore
    app.include_router(_pipeline_router.router, prefix="/api")
except ImportError:
    pass

# ベンチマーク用デバイス自動検出 + ジョブ管理ルーター（PUBLIC_MODE 時はマウント除外）
if not app_settings.PUBLIC_MODE:
    try:
        from backend.routers import benchmark as _bm_router  # type: ignore
        app.include_router(_bm_router.router, prefix="/api")
    except ImportError:
        pass


# ─── HTTP ボディサイズ上限ミドルウェア ────────────────────────────────────────
# 動画は local path 参照のため HTTP upload なし。
# sync .sspkg: アプリ層で 50 MB 制限済み。ここでは Content-Length ヘッダーによる
# 早期拒否（100 MB）で多層防御とする。チャンク転送はアプリ層で catch する。
_HTTP_UPLOAD_LIMIT = 100 * 1024 * 1024  # 100 MB
_AUTH_BODY_LIMIT   =  4 * 1024          # 4 KB（auth エンドポイント）


class UploadSizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: StarletteRequest, call_next):
        cl = request.headers.get("content-length")
        if cl:
            cl_int = int(cl)
            limit = _AUTH_BODY_LIMIT if request.url.path.startswith("/api/auth/") else _HTTP_UPLOAD_LIMIT
            if cl_int > limit:
                return StarletteResponse(
                    "リクエストボディが上限を超えています",
                    status_code=413,
                    media_type="application/json",
                )
        return await call_next(request)


app.add_middleware(UploadSizeLimitMiddleware)


# ─── アクセス制御ミドルウェア（role=player のみ強制） ────────────────────────
# POCフェーズの簡易実装:
#   ロール自体は自己申告(X-Role)だが、role=player の場合は X-Player-Id が
#   リクエスト対象リソース(試合/選手)に関連付けられているかを DB 照合する。
#   これにより ID 書き換えによる他選手データ覗き見を塞ぐ。
#   将来 JWT + チーム区分へ拡張する際はここを差し替える。
import re as _re_acl

# パスからリソース種別と ID を抽出する正規表現。/api/ プレフィックスは付く場合/付かない場合両対応。
# match_id: 試合に紐づく全エンドポイント。
_MATCH_ID_PATTERNS = [
    _re_acl.compile(r"^/api/matches/(\d+)(?:/.*)?$"),
    _re_acl.compile(r"^/api/sets/match/(\d+)$"),
    _re_acl.compile(r"^/api/sessions/match/(\d+)$"),
    _re_acl.compile(r"^/api/warmup/observations/(\d+)$"),
    _re_acl.compile(r"^/api/annotation/(\d+)(?:/.*)?$"),
    _re_acl.compile(r"^/api/cv-candidates/(?:build|apply|review-queue)/(\d+)$"),
    _re_acl.compile(r"^/api/cv-candidates/(\d+)$"),
    _re_acl.compile(r"^/api/yolo/(?:batch|results|align|alignment|frame_detect|assign_and_track|identity_track|movement_stats|doubles_analysis)/(\d+)(?:/.*)?$"),
    _re_acl.compile(r"^/api/tracknet/(?:shuttle_track|resume_check|batch)/(\d+)$"),
    _re_acl.compile(r"^/api/prediction/human_forecast/(\d+)$"),
    _re_acl.compile(r"^/api/analysis/[A-Za-z_/-]+/(\d+)(?:/.*)?$"),
    _re_acl.compile(r"^/api/reports/[A-Za-z_/-]+/(\d+)(?:/.*)?$"),
    _re_acl.compile(r"^/api/rallies/match/(\d+)(?:/.*)?$"),
    _re_acl.compile(r"^/api/strokes/match/(\d+)(?:/.*)?$"),
]
# player_id: 選手個別データ。
_PLAYER_ID_PATTERNS = [
    _re_acl.compile(r"^/api/players/(\d+)(?:/.*)?$"),
    _re_acl.compile(r"^/api/prediction/benchmark/(\d+)$"),
    _re_acl.compile(r"^/api/export/player/(\d+)$"),
]


# ─── player ロールに対する research / weakness / 対戦相手解析の禁止 ─────────
# CLAUDE.md 非交渉ルール:
#   - "Never show player-facing screens direct EPV or direct weakness summaries"
#   - research-tier 出力は player ロールに絶対に露出させない
#   - PLAYER_SENSITIVE_KEYS = {win_rate_vs_opponent, epv, weakness_zones,
#     rival_comparison, bottom_patterns}
# 自己 player_id へのリクエストでもブロックする (own EPV / own weakness も対象外)。
#
# 構成:
#  1. analysis_research / analysis_spine / analysis_bundle に登録された全ルート
#     (research tier + research spine + cross-tier research bundle)
#  2. analysis_advanced / analysis_stable のうち weakness / 対戦相手 / 直接比較
#     系の specific paths
#
# advanced-tier の中立 stat (pressure_performance, transition, temporal,
# growth_*, court_coverage_split 等) は player に露出しても問題ないため除外。
def _build_player_forbidden_analysis_paths() -> frozenset[str]:
    forbidden: set[str] = set()
    # 1) research / spine / bundle/research 全部
    try:
        from backend.routers import (
            analysis_research as _r,
            analysis_spine as _sp,
            analysis_bundle as _b,
        )
        for sub in (_r.router, _sp.router, _b.router):
            for route in getattr(sub, "routes", []):
                p = getattr(route, "path", None)
                if p:
                    forbidden.add(f"/api{p}")
    except Exception:
        pass
    # 2) PLAYER_SENSITIVE_KEYS にマッチする individual paths (advanced + stable)
    forbidden.update({
        # weakness / vulnerability
        "/api/analysis/received_vulnerability",
        "/api/analysis/received_vulnerability/zone_detail",
        "/api/analysis/opponent_vulnerability",
        # 対戦相手スカウティング (rival_comparison)
        "/api/analysis/opponent_card",
        "/api/analysis/opponent_stats",
        # 直接 win_rate vs opponent
        "/api/analysis/win_loss_comparison",
        "/api/analysis/partner_comparison",
        # advanced-tier opponent 系 (analysis_advanced.py)
        "/api/analysis/opponent_type_affinity",
        "/api/analysis/opponent_adaptive_shots",
        "/api/analysis/opponent_policy",
    })
    return frozenset(forbidden)


_PLAYER_FORBIDDEN_ANALYSIS_PATHS = _build_player_forbidden_analysis_paths()


def _extract_id(path: str, patterns) -> int | None:
    for pat in patterns:
        m = pat.match(path)
        if m:
            try:
                return int(m.group(1))
            except (ValueError, TypeError):
                return None
    return None


class PlayerAccessControlMiddleware(BaseHTTPMiddleware):
    """role=player と role=coach のリクエストに対し、対象リソースへのアクセス可否を DB 検証する。

    - player: 自 player_id の対戦/解析/コンディションのみ
    - coach: 自 team_name の player のみ (他チーム scouting は opponent_id 経由で
      OK だが、`?player_id=X` に他チーム player を渡すのは scope leak とみなす)
    """

    async def dispatch(self, request: StarletteRequest, call_next):
        # JWT 優先、フォールバックは X-Role
        role = None
        pid_raw = ""
        team_name = ""
        payload = None
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            from backend.utils.jwt_utils import verify_token
            payload = verify_token(token)
            if payload:
                role = payload.get("role")
                pid_raw = str(payload.get("player_id", "")) if payload.get("player_id") else ""
                team_name = payload.get("team_name", "") or ""

        # ── coach: クエリ ?player_id= に対する team scope 強制 ──
        # CLAUDE.md "coach: 自チーム所属選手" の原則を analysis / conditions /
        # reports / human_forecast / warmup に貫徹する。
        # round 4 の live attack で coach が他チーム player の EPV/heatmap/insights
        # を取得できる scope leak を確認したため middleware で塞ぐ。
        if role == "coach":
            path_co = request.url.path
            if (
                path_co.startswith("/api/analysis/")
                or path_co.startswith("/api/reports/")
                or path_co.startswith("/api/conditions/")
                or path_co.startswith("/api/conditions")
                or path_co.startswith("/api/human_forecast/")
                or path_co.startswith("/api/warmup/")
            ):
                qp_pids = request.query_params.getlist("player_id")
                if qp_pids:
                    coach_team = (team_name or "").strip()
                    if not coach_team:
                        return StarletteResponse(
                            "team_name 未設定の coach はこの解析にアクセスできません",
                            status_code=403,
                        )
                    from backend.db.database import SessionLocal as _SL_co
                    from backend.db.models import Player as _P_co
                    with _SL_co() as _db_co:
                        for qp_pid_raw in qp_pids:
                            try:
                                qp_pid = int(qp_pid_raw)
                            except (ValueError, TypeError):
                                continue
                            if qp_pid <= 0:
                                continue
                            p = _db_co.get(_P_co, qp_pid)
                            if p is None or (p.team or "").strip() != coach_team:
                                try:
                                    from backend.utils.access_log import log_access as _la
                                    with _SL_co() as _log_db:
                                        _la(_log_db, "access_denied_coach_scope",
                                            details={"path": path_co, "player_id": qp_pid})
                                except Exception:
                                    pass
                                return StarletteResponse(
                                    "この選手データはあなたのチームに所属していません",
                                    status_code=403,
                                )

        # X-Role ヘッダーによるフォールバックは削除（攻撃者が任意ロールを偽称できるため）
        # JWT にロールがない場合は player 制限を適用しない（非 player 扱い）
        if role != "player":
            return await call_next(request)

        if not pid_raw:
            pid_raw = request.headers.get("X-Player-Id")
        try:
            pid = int(pid_raw) if pid_raw else None
        except (ValueError, TypeError):
            pid = None

        if not pid or pid <= 0:
            # player ロールを名乗るが player_id を持たない → 常に拒否
            # （再ログインして選手を選ばせる）
            return StarletteResponse(
                "選手 ID が指定されていません。再ログインしてください。",
                status_code=401,
            )

        # JWT の player_id が DB の user.player_id と一致するかを検証する。
        # (admin が user.player_id を変更した / 古いトークンの再利用を塞ぐ防御的チェック)
        uid_raw = payload.get("sub") if payload else None
        if uid_raw:
            try:
                uid = int(uid_raw)
            except (ValueError, TypeError):
                uid = None
            if uid and uid > 0:
                try:
                    from backend.db.database import SessionLocal as _SL
                    from backend.db.models import User as _User
                    with _SL() as _db:
                        _u = _db.get(_User, uid)
                        if _u is None or _u.role != "player" or _u.player_id != pid:
                            return StarletteResponse(
                                "セッション情報が最新ではありません。再ログインしてください。",
                                status_code=401,
                            )
                except Exception:
                    pass

        path = request.url.path

        # ── player ロールの書き込み制限 ──
        # player が変更可能なエンドポイントは極めて限定的（自分の User / Player 情報更新のみ）。
        # 他はすべて 403 にする。データ改ざん・リソース作成の全面防御。
        method = request.method.upper()
        if method in ("POST", "PUT", "PATCH", "DELETE") and path.startswith("/api/"):
            _player_write_allowed = False
            # 自分の User レコードへの PUT (password/pin/display_name 更新など) は OK
            if payload and method == "PUT" and path == f"/api/auth/users/{payload.get('sub')}":
                _player_write_allowed = True
            # 自分の Player レコードへの PUT は OK
            if method == "PUT" and path == f"/api/players/{pid}":
                _player_write_allowed = True
            # MFA / ログアウト
            if path in ("/api/auth/logout", "/api/auth/mfa/setup", "/api/auth/mfa/confirm",
                        "/api/auth/mfa/disable", "/api/auth/mfa/login"):
                _player_write_allowed = True
            if not _player_write_allowed:
                try:
                    from backend.utils.access_log import log_access
                    from backend.db.database import SessionLocal
                    with SessionLocal() as _log_db:
                        log_access(_log_db, "access_denied_write",
                                   details={"method": method, "path": path})
                except Exception:
                    pass
                return StarletteResponse(
                    "この操作を行う権限がありません",
                    status_code=403,
                )

        # ── match スコープ ──
        mid = _extract_id(path, _MATCH_ID_PATTERNS)
        if mid is not None:
            from backend.db.database import SessionLocal
            from backend.db.models import Match
            db = SessionLocal()
            try:
                m = db.get(Match, mid)
                if m is None:
                    return StarletteResponse("試合が見つかりません", status_code=404)
                player_ids = {m.player_a_id, m.partner_a_id, m.player_b_id, m.partner_b_id}
                if pid not in player_ids:
                    try:
                        from backend.utils.access_log import log_access
                        from backend.db.database import SessionLocal
                        with SessionLocal() as _log_db:
                            log_access(_log_db, "access_denied", details={"path": path, "match_id": mid})
                    except Exception:
                        pass
                    return StarletteResponse(
                        "この試合へのアクセス権限がありません",
                        status_code=403,
                    )
            finally:
                db.close()

        # ── player スコープ（パスパラメータ） ──
        tgt_pid = _extract_id(path, _PLAYER_ID_PATTERNS)
        if tgt_pid is not None and tgt_pid != pid:
            try:
                from backend.utils.access_log import log_access
                from backend.db.database import SessionLocal
                with SessionLocal() as _log_db:
                    log_access(_log_db, "access_denied", details={"path": path, "target_player_id": tgt_pid})
            except Exception:
                pass
            return StarletteResponse(
                "この選手データへのアクセス権限がありません",
                status_code=403,
            )

        # ── player_id クエリパラメータ（解析系 IDOR 対策） ──
        # /api/analysis/*, /api/reports/*, /api/conditions/*, /api/human_forecast/*,
        # /api/warmup/* は player_id をクエリパラメータで受け取るため
        # パスパターンでは捕捉できない。クエリパラメータを直接検証する。
        # (`/api/conditions/insights` や `/api/conditions/best_profile` で他選手の
        #  ?player_id を指定すると 200 が返る IDOR を round 4 で検出。
        #  middleware 側で広めに塞ぐ。)
        if (
            path.startswith("/api/analysis/")
            or path.startswith("/api/reports/")
            or path.startswith("/api/conditions/")
            or path.startswith("/api/conditions")
            or path.startswith("/api/human_forecast/")
            or path.startswith("/api/warmup/")
        ):
            # HPP 対策: ?player_id=12&player_id=5 のような重複指定は、
            # どれか 1 つでも自分の player_id と異なる値が含まれていれば拒否する。
            qp_pids_raw = request.query_params.getlist("player_id")
            mismatched = False
            for qp_pid_raw in qp_pids_raw:
                if not qp_pid_raw:
                    continue
                try:
                    qp_pid = int(qp_pid_raw)
                except (ValueError, TypeError):
                    qp_pid = None
                if qp_pid and qp_pid != pid:
                    mismatched = True
                    break
            if mismatched:
                try:
                    from backend.utils.access_log import log_access
                    from backend.db.database import SessionLocal
                    with SessionLocal() as _log_db:
                        log_access(_log_db, "access_denied", details={"path": path, "query_player_ids": qp_pids_raw})
                except Exception:
                    pass
                return StarletteResponse(
                    "この選手データへのアクセス権限がありません",
                    status_code=403,
                )

        # ── research / advanced / weakness 解析の player ロール禁止 ──
        # 自己 player_id を渡されたケースでも、CLAUDE.md 非交渉ルールに従い
        # 直接 EPV / 弱点サマリ / research-tier の生データを player に露出させない。
        if path in _PLAYER_FORBIDDEN_ANALYSIS_PATHS:
            try:
                from backend.utils.access_log import log_access
                from backend.db.database import SessionLocal
                with SessionLocal() as _log_db:
                    log_access(_log_db, "access_denied_research", details={"path": path})
            except Exception:
                pass
            return StarletteResponse(
                "この解析は player ロールでは参照できません",
                status_code=403,
            )

        return await call_next(request)


app.add_middleware(PlayerAccessControlMiddleware)


# ─── Exfil 異常検知: 大量データ要求を閾値超過で警告ログ + 極端時のみブロック ──
# 設計方針: 正当な analyst 業務（全選手コンディション分析、match 一括レビュー、
# レポート生成等）を妨害してはならない。よって以下の 2 段階設計:
#   1. 通常閾値 (60s で 50MB / 600req) を超えたら WARNING ログを出して通す
#      → SIEM/ログ監視側で検知・人間による判断を可能にする
#   2. 極端閾値 (60s で 500MB / 6000req) を超えたら 429 でブロック
#      → 人間では到達し得ない機械的 exfil のみを止める
# role=admin はいずれも除外（運用上の大量アクセス・DB メンテを許容）。
class ExfilRateLimitMiddleware(BaseHTTPMiddleware):
    _window_sec = 60
    # ALERT: WARNING ログを吐く閾値 (正当業務の上限付近)
    _alert_bytes = 50 * 1024 * 1024     # 50 MB/60s
    _alert_requests = 600               # 600 req/60s
    # HARD BLOCK: 人間では到達し得ない閾値 (APT の機械 exfil のみを止める)
    _max_bytes_per_window = 500 * 1024 * 1024   # 500 MB/60s
    _max_requests_per_window = 6000             # 6000 req/60s

    def __init__(self, app):
        super().__init__(app)
        import threading as _th
        self._lock = _th.Lock()
        self._state: dict[int, list] = {}  # {user_id: [ts_start, bytes, count, alerted]}

    async def dispatch(self, request: StarletteRequest, call_next):
        path = request.url.path
        if not path.startswith("/api/") or path.startswith("/api/auth/login") or path.startswith("/api/health") or path.startswith("/api/public"):
            return await call_next(request)
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return await call_next(request)
        from backend.utils.jwt_utils import verify_token
        payload = verify_token(auth[7:])
        if not payload:
            return await call_next(request)
        role = payload.get("role")
        # admin は exfil 制限完全除外 (運用・メンテ業務)
        if role == "admin":
            return await call_next(request)
        try:
            uid = int(payload.get("sub", 0))
        except (ValueError, TypeError):
            return await call_next(request)
        if uid <= 0:
            return await call_next(request)

        import time as _t
        import logging as _lg
        _logger = _lg.getLogger("shuttlescope.exfil")
        now = _t.time()
        with self._lock:
            st = self._state.get(uid)
            if not st or now - st[0] > self._window_sec:
                st = [now, 0, 0, False]  # start_ts, bytes, count, alerted
                self._state[uid] = st
            st[2] += 1

            # HARD BLOCK: 機械的 exfil のみ止める
            if st[2] > self._max_requests_per_window or st[1] > self._max_bytes_per_window:
                _logger.error(
                    "exfil HARD BLOCK user_id=%s role=%s bytes=%s req=%s path=%s",
                    uid, role, st[1], st[2], path,
                )
                return StarletteResponse(
                    '{"detail":"短時間に極端に大量のリクエストを検出しました。しばらくしてから再試行してください。"}',
                    status_code=429,
                    media_type="application/json",
                )
            # ALERT: 通常業務の上限付近で WARNING ログ出力 (ブロックしない)
            if not st[3] and (st[2] > self._alert_requests or st[1] > self._alert_bytes):
                _logger.warning(
                    "exfil ALERT user_id=%s role=%s bytes=%s req=%s path=%s (not blocked)",
                    uid, role, st[1], st[2], path,
                )
                st[3] = True

        response = await call_next(request)
        try:
            cl = int(response.headers.get("content-length", "0") or 0)
        except (ValueError, TypeError):
            cl = 0
        with self._lock:
            st = self._state.get(uid)
            if st:
                st[1] += cl
        return response


app.add_middleware(ExfilRateLimitMiddleware)


# ─── チーム境界アクセス制御ミドルウェア（Phase B-6） ─────────────────────────
# coach/analyst のリクエストに対し、対象 match_id がチーム境界内（owner_team_id 一致 /
# is_public_pool / 自チーム選手登場）であるかを DB 検証する。
# admin / player は本ミドルウェアでは素通し（player は PlayerAccessControlMiddleware で処理済み）。
class TeamScopeAccessControlMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: StarletteRequest, call_next):
        if not request.url.path.startswith("/api/"):
            return await call_next(request)
        # JWT 必須（GlobalAuthMiddleware で先に弾かれるが念のため）
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return await call_next(request)
        from backend.utils.jwt_utils import verify_token
        payload = verify_token(auth_header[7:])
        if not payload:
            return await call_next(request)
        role = payload.get("role")
        # admin / player はスキップ（admin は全許可、player は別ミドルウェアで処理）
        if role not in ("coach", "analyst"):
            return await call_next(request)
        team_id_raw = payload.get("team_id")
        try:
            team_id = int(team_id_raw) if team_id_raw is not None else None
        except (ValueError, TypeError):
            team_id = None

        path = request.url.path
        mid = _extract_id(path, _MATCH_ID_PATTERNS)
        if mid is None:
            return await call_next(request)

        from backend.db.database import SessionLocal
        from backend.db.models import Match, Player
        try:
            with SessionLocal() as _db:
                m = _db.get(Match, mid)
                if m is None:
                    return StarletteResponse("試合が見つかりません", status_code=404)
                # 1) public プール
                if bool(getattr(m, "is_public_pool", False)):
                    return await call_next(request)
                # 2) 自チームが owner
                if team_id is not None and getattr(m, "owner_team_id", None) == team_id:
                    return await call_next(request)
                # 3) 自チーム選手が登場
                if team_id is not None:
                    pids = [m.player_a_id, m.player_b_id, m.partner_a_id, m.partner_b_id]
                    pids = [p for p in pids if p]
                    if pids:
                        hit = (
                            _db.query(Player.id)
                            .filter(Player.id.in_(pids), Player.team_id == team_id)
                            .first()
                        )
                        if hit is not None:
                            return await call_next(request)
                # いずれにも該当しない → 存在を隠して 404
                try:
                    from backend.utils.access_log import log_access
                    log_access(_db, "access_denied",
                               details={"path": path, "match_id": mid, "team_id": team_id})
                except Exception:
                    pass
                return StarletteResponse("試合が見つかりません", status_code=404)
        except Exception:
            # 例外時は安全側に倒し、後段の DB エラーに委ねる
            return await call_next(request)


app.add_middleware(TeamScopeAccessControlMiddleware)


# ─── /api/analysis/* GET レスポンスキャッシュミドルウェア ────────────────────
# 読み専用エンドポイントをプロセス内メモリにキャッシュし、解析タブの
# 再描画を高速化する。認証ヘッダ（X-Role / X-Player-Id / X-Team-Name）を
# キーに含めることで、role=player 絞り込み結果の漏洩を防ぐ。
# mutation 系ルーターで `response_cache.bump_version()` を呼ぶことで
# 一括無効化される。

class AnalysisCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: StarletteRequest, call_next):
        if request.method != "GET" or not request.url.path.startswith("/api/analysis/"):
            return await call_next(request)
        path = request.url.path
        query = str(request.url.query)
        # キャッシュキーは必ずJWT検証済みのclaimsから生成する。
        # X-Role/X-Player-Id ヘッダーはユーザーが自由に設定できるため、
        # キャッシュキーに使うと PlayerAccessControlMiddleware をバイパスできる。
        jwt_role = ""
        jwt_pid = ""
        jwt_team = ""
        jwt_team_id = ""
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            from backend.utils.jwt_utils import verify_token
            _payload = verify_token(auth_header[7:])
            if _payload:
                jwt_role = _payload.get("role", "")
                jwt_pid = str(_payload.get("player_id", "")) if _payload.get("player_id") else ""
                jwt_team = _payload.get("team_name", "") or ""
                _tid = _payload.get("team_id")
                jwt_team_id = str(_tid) if _tid is not None else ""
        params = {
            "q": query,
            "role": jwt_role,
            "pid": jwt_pid,
            "team": jwt_team,
            # Phase B-8: チーム ID をキャッシュキーに含めることで他チーム閲覧結果の漏出を防ぐ
            "team_id": jwt_team_id,
        }
        key = response_cache.build_key(path, params)
        cached = response_cache.get(key)
        if cached is not None:
            from fastapi.responses import JSONResponse
            return JSONResponse(content=cached, headers={"X-Cache": "HIT"})
        response = await call_next(request)
        # 200 かつ JSON のみキャッシュ対象
        if (
            response.status_code == 200
            and response.headers.get("content-type", "").startswith("application/json")
        ):
            body = b""
            async for chunk in response.body_iterator:
                body += chunk
            try:
                payload = _json_cache.loads(body)
                # DB 永続化用メタデータ: JWT検証済みpidを優先、なければクエリパラメータ
                pid: int | None
                if jwt_pid.isdigit():
                    pid = int(jwt_pid)
                else:
                    import re as _re
                    m = _re.search(r"player_id=(\d+)", query)
                    pid = int(m.group(1)) if m else None
                analysis_type = path.replace("/api/analysis/", "", 1).split("/")[0] or "unknown"
                try:
                    filters_json = _json_cache.dumps(params)
                except Exception:
                    filters_json = "{}"
                response_cache.set(
                    key,
                    payload,
                    ttl=300,
                    player_id=pid,
                    analysis_type=analysis_type,
                    filters_json=filters_json,
                )
            except Exception:
                pass
            new_headers = dict(response.headers)
            new_headers["X-Cache"] = "MISS"
            # content-length を body で作り直すため既存ヘッダは削除
            new_headers.pop("content-length", None)
            return StarletteResponse(
                content=body,
                status_code=200,
                headers=new_headers,
                media_type="application/json",
            )
        return response


app.add_middleware(AnalysisCacheMiddleware)


# ─── グローバル認証ミドルウェア ────────────────────────────────────────────────
# 全 /api/ ルートに Bearer JWT を必須とする。
# 除外: /api/auth/login, /api/auth/logout, /api/auth/bootstrap-status のみ
#       （/api/auth/analysts, /api/auth/players 等は要認証）
# loopback (Electron ローカル起動) は X-Role フォールバックを維持するため除外。
# CORS preflight (OPTIONS) も除外。
_GLOBAL_AUTH_EXEMPT = _re_acl.compile(
    r"^/api/(auth/(login|logout|bootstrap-status)|health|public(/.*)?)"
)


class GlobalAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: StarletteRequest, call_next):
        if not request.url.path.startswith("/api/"):
            return await call_next(request)
        if request.method == "OPTIONS":
            return await call_next(request)
        if _GLOBAL_AUTH_EXEMPT.match(request.url.path):
            return await call_next(request)
        # PUBLIC_MODE（Cloudflare 公開）では loopback 緩和を適用しない。
        # Cloudflare 設定ミス等で CF-Connecting-IP が欠落した場合も全リクエストが
        # 127.0.0.1 として届くため、そこを唯一の信頼点にしてはならない。
        if not app_settings.PUBLIC_MODE:
            from backend.utils.control_plane import is_loopback_request
            if is_loopback_request(request):
                return await call_next(request)
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return StarletteResponse(
                '{"detail":"認証が必要です"}',
                status_code=401,
                media_type="application/json",
            )
        from backend.utils.jwt_utils import verify_token
        payload = verify_token(auth_header[7:])
        if not payload:
            return StarletteResponse(
                '{"detail":"トークンが無効または期限切れです"}',
                status_code=401,
                media_type="application/json",
            )
        return await call_next(request)


app.add_middleware(GlobalAuthMiddleware)


# ─── 422 バリデーションエラーの input エコー時に機密フィールドをマスク ────────
# FastAPI デフォルトはリクエストボディをそのまま返すため、パスワードがログや
# プロキシに残るリスクがある。password/token/secret 系をマスクしてから返す。
from fastapi.exceptions import RequestValidationError as _ReqValidationError
from fastapi.responses import JSONResponse as _JSONResp

_SENSITIVE_FIELD_NAMES = frozenset({
    "password", "new_password", "old_password", "current_password",
    "token", "access_token", "refresh_token", "secret", "api_key",
    "totp", "totp_code", "mfa_code", "otp", "hashed_credential",
})


# バリデーションエラー input の長大 string 閾値。ここを超える文字列は `***(truncated)`
# に置換する。XML/バイナリ/巨大ペイロードがログやプロキシに生で載らないようにする。
_INPUT_STRING_MAX_LEN = 200


def _mask_sensitive(value, depth: int = 0):
    if depth > 4:
        return "***"
    if isinstance(value, dict):
        return {
            k: ("***" if k.lower() in _SENSITIVE_FIELD_NAMES else _mask_sensitive(v, depth + 1))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_mask_sensitive(v, depth + 1) for v in value[:20]]
    if isinstance(value, str):
        # 長大な文字列 / バイナリっぽい文字列はマスク
        if len(value) > _INPUT_STRING_MAX_LEN:
            return "***(truncated)"
        # XML/HTML/ SQL っぽいペイロードはマスク
        lowered = value.lstrip().lower()
        if lowered.startswith(("<?xml", "<!doctype", "<html", "<script")):
            return "***(xml/html)"
        return value
    if isinstance(value, bytes):
        return f"***(bytes,len={len(value)})"
    return value


@app.exception_handler(_ReqValidationError)
async def _validation_error_handler(request: StarletteRequest, exc: _ReqValidationError):
    errs = []
    for e in exc.errors():
        e2 = dict(e)
        # loc に機密フィールドが含まれる場合は input 全体をマスク
        loc = e2.get("loc", ())
        if any(isinstance(seg, str) and seg.lower() in _SENSITIVE_FIELD_NAMES for seg in loc):
            e2["input"] = "***"
        else:
            e2["input"] = _mask_sensitive(e2.get("input"))
        # ctx (Pydantic が検証詳細を入れる) にも機密が混じる可能性があるのでマスク
        if "ctx" in e2:
            e2["ctx"] = _mask_sensitive(e2.get("ctx"))
        errs.append(e2)
    return _JSONResp({"detail": errs}, status_code=422)


# ─── グローバル例外ハンドラ（PUBLIC_MODE / HIDE_STACK_TRACES でスタックトレースを隠す） ─
import traceback as _traceback


# SQLite INTEGER オーバーフロー（int64 範囲外）を 422 に変換する。
# 攻撃者が `{"player_a_id": 99999999999999999999}` のような巨大整数を送ると
# sqlite3 ドライバが OverflowError を投げて 500 を返すため、422 で明示的に拒否する。
@app.exception_handler(OverflowError)
async def _overflow_handler(request: StarletteRequest, exc: OverflowError):
    _logger = logging.getLogger("shuttlescope.unhandled")
    _logger.warning("OverflowError on %s %s: %s", request.method, request.url.path, exc)
    return _JSONResp(
        {"detail": "数値が許容範囲を超えています (SQLite INTEGER は ±2^63 の範囲内)"},
        status_code=422,
    )


# SQLAlchemy の DataError / StatementError 内でラップされた OverflowError にも対応。
from sqlalchemy.exc import StatementError as _SAStatementError

@app.exception_handler(_SAStatementError)
async def _sa_statement_handler(request: StarletteRequest, exc: _SAStatementError):
    # 内部原因が OverflowError なら 422、それ以外はグローバルハンドラへ伝播させる
    cause = getattr(exc, "orig", None)
    if isinstance(cause, OverflowError):
        _logger = logging.getLogger("shuttlescope.unhandled")
        _logger.warning("SQLAlchemy OverflowError on %s %s", request.method, request.url.path)
        return _JSONResp(
            {"detail": "数値が許容範囲を超えています (SQLite INTEGER は ±2^63 の範囲内)"},
            status_code=422,
        )
    # それ以外は raise して下段のグローバルハンドラへ
    raise exc


@app.exception_handler(Exception)
async def _global_exception_handler(request: StarletteRequest, exc: Exception):
    _logger = logging.getLogger("shuttlescope.unhandled")
    _logger.error("Unhandled exception %s %s", request.method, request.url.path, exc_info=exc)
    if app_settings.PUBLIC_MODE or app_settings.HIDE_STACK_TRACES:
        return StarletteResponse(
            '{"detail":"内部エラーが発生しました"}',
            status_code=500,
            media_type="application/json",
        )
    # 開発時はトレースバックをレスポンスに含める
    tb = _traceback.format_exc()
    import json as _json
    return StarletteResponse(
        _json.dumps({"detail": str(exc), "traceback": tb}),
        status_code=500,
        media_type="application/json",
    )


# ─── セキュリティヘッダーミドルウェア ─────────────────────────────────────────
# 最後に add するため実行は一番最初（Starlette は逆順実行）。
# CSP は React の動的スタイル・スクリプトと衝突しうるため除外。
# HSTS は HTTPS 終端の Cloudflare 側でも設定されるが多層防御として追加。
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: StarletteRequest, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if app_settings.PUBLIC_MODE:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        # 認証 Bearer 付きの API レスポンスは機密扱い — 中間キャッシュ禁止
        # /api/auth/* はログイン時に access/refresh token を返すが、初回呼び出しには
        # Authorization ヘッダがないため Bearer 条件では拾えない。トークンが共有
        # HTTP キャッシュ (CDN / プロキシ) に残らないよう /api/auth/ も明示的に
        # no-store にする (CWE-525 / OWASP A05)。
        path = request.url.path
        is_auth_path = path.startswith("/api/auth/")
        has_bearer = request.headers.get("Authorization", "").startswith("Bearer ")
        if (has_bearer and path.startswith("/api/")) or is_auth_path:
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
        # CSP: API/JSON 応答には厳格なポリシーを設定（レンダラーは default-src 'none' で十分）
        ctype = response.headers.get("content-type", "")
        if path.startswith("/api/") and "application/json" in ctype:
            response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        return response


# ─── CORS設定 ───────────────────────────────────────────────────────────────
# PUBLIC_MODE=True（Cloudflare公開）: 許可オリジンをトンネルホスト名に限定。
# PUBLIC_MODE=False（LAN / Electron）: wildcard。LAN デバイスは任意 IP のため。
_cors_origins = (
    [f"https://{app_settings.CLOUDFLARE_TUNNEL_HOSTNAME}"]
    if app_settings.PUBLIC_MODE
    else ["*"]
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Accept", "Authorization", "X-Session-Token", "X-Role", "X-Player-Id", "X-Team-Name"],
)

# ルーター登録
app.include_router(players.router, prefix="/api")
app.include_router(matches.router, prefix="/api")
app.include_router(rallies.router, prefix="/api")
app.include_router(strokes.router, prefix="/api")
app.include_router(sets.router, prefix="/api")
app.include_router(analysis.router, prefix="/api")
app.include_router(reports.router, prefix="/api")
app.include_router(settings_router.router, prefix="/api")
app.include_router(tracknet.router, prefix="/api")
app.include_router(yolo.router, prefix="/api")
# CV補助アノテーション候補
app.include_router(cv_candidates.router, prefix="/api")
# R-001/R-002: 共有セッション
app.include_router(sessions.router, prefix="/api")
# S-003: コメント
app.include_router(comments.router, prefix="/api")
# U-001: ブックマーク
app.include_router(bookmarks.router, prefix="/api")
# G3: ウォームアップ観察
app.include_router(warmup.router, prefix="/api")
# 予測エンジン (Phase A+B)
app.include_router(prediction.router, prefix="/api")
# Cloudflare Tunnel 管理
app.include_router(tunnel.router, prefix="/api")
# Phase S2: ヒューマンベンチマーク
app.include_router(human_forecast.router, prefix="/api")
# データ同期（Export / Import / Backup）
app.include_router(sync_router.router, prefix="/api")
# 動画インポート & バックグラウンド解析（iGPU優先）
app.include_router(video_import.router, prefix="/api")
# コートキャリブレーション（ホモグラフィ + ROI）
app.include_router(court_calibration.router, prefix="/api")
# コンディション（体調）Phase 1
app.include_router(conditions_router.router)
app.include_router(condition_tags_router.router)
# Expert Labeler Phase 1（コーチ・アナリスト専用アノテーション）
app.include_router(expert_router.router, prefix="/api")
# B: 高速レビュー導線 / D: セット間支援
app.include_router(review_router.router, prefix="/api")
# E: データ資産化 JSON パッケージ
app.include_router(data_package_router.router, prefix="/api")
# 分割動画アップロード（ブラウザ用。iOS Safari 含む）
app.include_router(uploads_router.router, prefix="/api")

# PUBLIC_MODE=0（デフォルト）の場合のみマウントする危険ルーター群
if not app_settings.PUBLIC_MODE:
    # CV モデルベンチマーク
    app.include_router(cv_benchmark.router, prefix="/api")
    # Q-002/Q-008: ネットワーク診断
    app.include_router(network_diag.router, prefix="/api")
    # DB メンテナンス
    app.include_router(db_maintenance_router.router, prefix="/api")
    # クラスタ管理 API
    app.include_router(cluster_router.router, prefix="/api")
# Phase A: 認証
app.include_router(auth_router.router, prefix="/api")
app.include_router(public_site.router)



@app.get("/api/health")
async def health():
    """ヘルスチェック（Electron起動確認用）"""
    # 無認証でアクセス可能なため、内部モード（PUBLIC_MODE）/ バージョンは返さない
    return {"status": "ok"}


@app.post("/api/cache/invalidate")
async def cache_invalidate(request: StarletteRequest):
    """解析レスポンスキャッシュを手動で全無効化する（admin のみ）"""
    from backend.utils.auth import get_auth
    ctx = get_auth(request)
    if not ctx.is_admin:
        from starlette.responses import Response as StarletteResp
        return StarletteResp('{"detail":"管理者権限が必要です"}', status_code=403, media_type="application/json")
    version = response_cache.bump_version()
    return {"success": True, "data_version": version, "stats": response_cache.stats()}


@app.get("/api/cache/stats")
async def cache_stats(request: StarletteRequest):
    """キャッシュ統計（admin のみ）"""
    from backend.utils.auth import get_auth
    ctx = get_auth(request)
    if not ctx.is_admin:
        from starlette.responses import Response as StarletteResp
        return StarletteResp('{"detail":"管理者権限が必要です"}', status_code=403, media_type="application/json")
    return {"success": True, "stats": response_cache.stats()}


# ─── WebSocket 共通: JWT 認証ヘルパー ────────────────────────────────────────

async def _ws_require_auth(websocket: WebSocket) -> bool:
    """WS 接続時のJWT事前検証（accept() 前に呼ぶ）。

    許可条件（優先順）:
      1. loopback (127.0.0.1 / ::1) — Electron ローカル起動
      2. 平文 WS (ws://) — LAN 直接接続。session_code が暗黙の shared-secret として機能
      3. ?token=<jwt> クエリパラメータが有効 — Cloudflare 経由の外部接続
    上記いずれも満たさない場合は接続を拒否する。
    """
    from backend.utils.jwt_utils import verify_token

    # PUBLIC_MODE（Cloudflare 公開）では、cloudflared が 127.0.0.1 から接続するため
    # loopback / ws:// の緩和条件を許容すると外部から JWT 無しで WS に繋げてしまう。
    # したがって PUBLIC_MODE 時は例外なく JWT を要求する。
    if app_settings.PUBLIC_MODE:
        token = websocket.query_params.get("token", "")
        if token and verify_token(token):
            return True
        await websocket.close(code=4401)
        return False

    client_ip = websocket.client.host if websocket.client else ""
    if client_ip in ("127.0.0.1", "::1", "localhost", ""):
        return True

    # LAN 直接接続（ws://）は session_code が認証代替として機能
    if websocket.url.scheme == "ws":
        return True

    # Cloudflare 経由（wss://）は JWT 必須
    token = websocket.query_params.get("token", "")
    if token and verify_token(token):
        return True

    await websocket.close(code=4401)
    return False


# ─── S-001: WebSocket ライブフィード ─────────────────────────────────────────

@app.websocket("/ws/live/{session_code}")
async def ws_live(session_code: str, websocket: WebSocket):
    """コーチ / ビューワーがリアルタイムでスコア・ラリー情報を受け取る WS エンドポイント"""
    if not await _ws_require_auth(websocket):
        return
    from backend.ws.live import ws_live_handler
    db = next(get_db())
    try:
        await ws_live_handler(session_code, websocket, db)
    finally:
        db.close()


# ─── LAN カメラ: WebRTC シグナリング WS ──────────────────────────────────────

# ─── ブラウザ中継リアルタイム YOLO WS ───────────────────────────────────────

@app.websocket("/ws/yolo/realtime/{session_code}")
async def ws_yolo_realtime(session_code: str, websocket: WebSocket):
    """オペレーター PC から送られる JPEG を yolov8n で推論し bbox を返す WS。

    セッションごとに独立、接続ごとに独立タスクで動作するため、複数 PC からの
    並列接続が自然にサポートされる（共有状態なし）。
    """
    if not await _ws_require_auth(websocket):
        return
    from backend.routers.yolo_realtime import ws_realtime_yolo_handler
    await ws_realtime_yolo_handler(session_code, websocket)


@app.websocket("/ws/camera/{session_code}")
async def ws_camera(
    session_code: str,
    websocket: WebSocket,
    role: str = Query(default=None),
    participant_id: str = Query(default=None),
    viewer_id: str = Query(default=None),
):
    """WebRTC シグナリング中継エンドポイント
    ?role=operator               → PC オペレーター
    ?role=viewer&viewer_id={id}  → ビューワーデバイス（他PC / タブレット）
    ?participant_id={id}         → iOS / タブレット 送信デバイス
    """
    if not await _ws_require_auth(websocket):
        return
    from backend.ws.camera import ws_camera_handler
    await ws_camera_handler(
        session_code, websocket,
        role=role, participant_id=participant_id, viewer_id=viewer_id,
    )


# ─── S-001: コーチビュー HTML（LAN ブラウザ向けスタンドアロンページ） ──────────

_COACH_HTML = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ShuttleScope コーチビュー</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0f172a; color: #f1f5f9; font-family: system-ui, -apple-system, sans-serif; min-height: 100vh; }
  .header { background: #1e293b; border-bottom: 1px solid #334155; padding: 12px 20px; display: flex; align-items: center; gap: 12px; }
  .header h1 { font-size: 1.1rem; font-weight: 700; }
  .status-dot { width: 8px; height: 8px; border-radius: 50%; background: #64748b; flex-shrink: 0; }
  .status-dot.connected { background: #22c55e; animation: pulse 2s infinite; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.5} }
  .session-code { font-size: 0.75rem; color: #94a3b8; margin-left: auto; }
  .main { padding: 20px; max-width: 600px; margin: 0 auto; }
  .score-card { background: #1e293b; border-radius: 12px; padding: 24px; margin-bottom: 16px; text-align: center; }
  .score-row { display: flex; align-items: center; justify-content: center; gap: 24px; margin-bottom: 12px; }
  .score-val { font-size: 3.5rem; font-weight: 800; line-height: 1; }
  .score-sep { font-size: 2rem; color: #475569; font-weight: 300; }
  .player-label { font-size: 0.8rem; color: #94a3b8; margin-top: 4px; }
  .set-badges { display: flex; gap: 8px; justify-content: center; flex-wrap: wrap; margin-top: 12px; }
  .set-badge { background: #0f172a; border-radius: 6px; padding: 4px 10px; font-size: 0.75rem; color: #94a3b8; }
  .set-badge.win { color: #60a5fa; border: 1px solid #3b82f6; }
  .section-title { font-size: 0.75rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; color: #64748b; margin-bottom: 8px; }
  .rally-list { background: #1e293b; border-radius: 12px; overflow: hidden; }
  .rally-item { display: flex; align-items: center; gap: 12px; padding: 10px 16px; border-bottom: 1px solid #0f172a; font-size: 0.85rem; }
  .rally-item:last-child { border-bottom: none; }
  .rally-num { color: #64748b; width: 28px; flex-shrink: 0; }
  .rally-score { font-weight: 600; color: #e2e8f0; }
  .rally-winner { width: 20px; height: 20px; border-radius: 50%; background: #3b82f6; display: flex; align-items: center; justify-content: center; font-size: 0.6rem; font-weight: 700; flex-shrink: 0; }
  .rally-winner.b { background: #f59e0b; }
  .rally-end { color: #94a3b8; font-size: 0.75rem; margin-left: auto; }
  .progress-bar { height: 4px; background: #0f172a; border-radius: 2px; overflow: hidden; margin-top: 12px; }
  .progress-fill { height: 100%; background: #3b82f6; transition: width 0.5s; }
  .empty { text-align: center; color: #475569; padding: 32px; font-size: 0.9rem; }
  .error-banner { background: #7f1d1d; color: #fca5a5; padding: 10px 16px; border-radius: 8px; font-size: 0.85rem; margin-bottom: 12px; }
  .participants { font-size: 0.75rem; color: #64748b; text-align: center; margin-top: 8px; }
</style>
</head>
<body>
<div class="header">
  <div class="status-dot" id="statusDot"></div>
  <h1>ShuttleScope コーチビュー</h1>
  <span class="session-code" id="sessionCodeLabel"></span>
</div>
<div class="main">
  <div id="errorBanner" class="error-banner" style="display:none"></div>
  <div class="score-card">
    <div class="score-row">
      <div>
        <div class="score-val" id="scoreA">-</div>
        <div class="player-label" id="playerALabel">A</div>
      </div>
      <div class="score-sep">:</div>
      <div>
        <div class="score-val" id="scoreB">-</div>
        <div class="player-label" id="playerBLabel">B</div>
      </div>
    </div>
    <div class="set-badges" id="setBadges"></div>
    <div class="progress-bar"><div class="progress-fill" id="progressFill" style="width:0%"></div></div>
    <div class="participants" id="participantsLabel"></div>
  </div>
  <div class="section-title">直近ラリー</div>
  <div class="rally-list" id="rallyList"><div class="empty">データ待機中…</div></div>
</div>
<script>
const SESSION_CODE = location.pathname.split('/coach/')[1] || '';
const API_BASE = location.origin;
document.getElementById('sessionCodeLabel').textContent = 'セッション: ' + SESSION_CODE;

// XSS防止: innerHTML に埋め込む値を必ずエスケープする
function escHtml(s) {
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

let scoreA = '-', scoreB = '-';

function setDot(connected) {
  document.getElementById('statusDot').className = 'status-dot' + (connected ? ' connected' : '');
}

function renderSnapshot(data) {
  const sets = data.set_scores || [];
  if (sets.length > 0) {
    const latest = sets[sets.length - 1];
    document.getElementById('scoreA').textContent = latest.score_a;
    document.getElementById('scoreB').textContent = latest.score_b;
  }
  const badges = document.getElementById('setBadges');
  badges.innerHTML = sets.slice(0, -1).map(s =>
    `<span class="set-badge ${s.winner ? 'win' : ''}">${escHtml(s.set_num)}セット ${escHtml(s.score_a)}-${escHtml(s.score_b)}</span>`
  ).join('');
  const progress = Math.round((data.annotation_progress || 0) * 100);
  document.getElementById('progressFill').style.width = progress + '%';
  const pc = data.participants || 0;
  document.getElementById('participantsLabel').textContent = pc + ' 名が接続中';
  renderRallies(data.recent_rallies || []);
}

function renderRallies(rallies) {
  const el = document.getElementById('rallyList');
  if (!rallies.length) { el.innerHTML = '<div class="empty">ラリーなし</div>'; return; }
  el.innerHTML = rallies.map(r => {
    const isA = r.winner === 'player_a';
    return `<div class="rally-item">
      <span class="rally-num">#${escHtml(r.rally_num)}</span>
      <div class="rally-winner ${isA ? 'a' : 'b'}">${isA ? 'A' : 'B'}</div>
      <span class="rally-score">${escHtml(r.score_a)} : ${escHtml(r.score_b)}</span>
      <span class="rally-end">${escHtml(r.end_type)} / ${escHtml(r.rally_length)}球</span>
    </div>`;
  }).join('');
}

function appendRally(data) {
  const el = document.getElementById('rallyList');
  if (el.querySelector('.empty')) el.innerHTML = '';
  const isA = data.winner === 'player_a';
  const div = document.createElement('div');
  div.className = 'rally-item';
  div.innerHTML = `<span class="rally-num">#${escHtml(data.rally_num)}</span>
    <div class="rally-winner ${isA ? 'a' : 'b'}">${isA ? 'A' : 'B'}</div>
    <span class="rally-score">${escHtml(data.score_a)} : ${escHtml(data.score_b)}</span>
    <span class="rally-end">${escHtml(data.end_type)} / ${escHtml(data.rally_length)}球</span>`;
  el.insertBefore(div, el.firstChild);
  while (el.children.length > 8) el.removeChild(el.lastChild);
  document.getElementById('scoreA').textContent = data.score_a;
  document.getElementById('scoreB').textContent = data.score_b;
}

// 初期スナップショットを REST で取得
fetch(API_BASE + '/api/sessions/' + SESSION_CODE + '/state')
  .then(r => r.json())
  .then(res => { if (res.success) renderSnapshot(res.data); })
  .catch(() => {});

// WebSocket 接続
function connectWS() {
  const wsProto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(wsProto + '://' + location.host + '/ws/live/' + SESSION_CODE);
  ws.onopen = () => setDot(true);
  ws.onclose = () => { setDot(false); setTimeout(connectWS, 3000); };
  ws.onerror = () => setDot(false);
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === 'snapshot') { renderSnapshot(msg.data); }
    else if (msg.type === 'rally_saved') { appendRally(msg.data); }
    else if (msg.type === 'comment') {
      // コメントはシンプルにトースト表示
      const d = msg.data;
      if (d.is_flagged) {
        const banner = document.getElementById('errorBanner');
        banner.style.display = 'block';
        banner.textContent = '⚑ ' + (d.author_role === 'coach' ? 'コーチ' : 'アナリスト') + ': ' + d.text;
        setTimeout(() => { banner.style.display = 'none'; }, 8000);
      }
    }
    else if (msg.type === 'ping') { ws.send(JSON.stringify({type:'ping'})); }
  };
}
connectWS();
</script>
</body>
</html>"""


@app.get("/coach/{session_code}", response_class=HTMLResponse)
async def coach_view(session_code: str):
    """S-001: コーチビュー HTML ページ（後方互換、フル React アプリへ誘導）"""
    # React SPA が利用可能な場合はリダイレクト
    if _RENDERER_DIR.exists():
        return HTMLResponse(
            content=f'<meta http-equiv="refresh" content="0; url=/#/"><script>location.replace("/#/");</script>',
            status_code=302,
        )
    return HTMLResponse(content=_COACH_HTML)


@app.get("/api/system/capabilities")
async def system_capabilities():
    """動作環境の依存ツール可用性を返す（フロントエンド向け）
    - yt_dlp: ダウンロード機能が使えるか
    - ffmpeg: 高画質マージダウンロードが使えるか（未インストール時は低画質フォールバック）
    """
    caps = video_downloader.get_capabilities()
    return {"success": True, "data": caps}


@app.get("/api/version")
async def version():
    """バージョン情報。

    バージョンは SPA フッターで使う可能性があるため公開。
    ただし environment (production/development) は攻撃面情報を漏らすため返さない。
    """
    return {"version": "1.0.0"}


# ─── React SPA 配信（LAN / トンネルブラウザアクセス用）───────────────────────
# HashRouter 使用のため / を常に返せば全クライアントサイドルートが動作する。
# StaticFiles の条件マウントではなく明示ルートで配信（MIME タイプを直接指定）。
_assets_dir = _RENDERER_DIR / "assets"
_INDEX_HTML = _RENDERER_DIR / "index.html"

# 拡張子 → Content-Type の明示マッピング（Windows mimetypes に依存しない）
_MIME_MAP: dict[str, str] = {
    ".js":    "application/javascript; charset=utf-8",
    ".mjs":   "application/javascript; charset=utf-8",
    ".css":   "text/css; charset=utf-8",
    ".html":  "text/html; charset=utf-8",
    ".json":  "application/json",
    ".png":   "image/png",
    ".jpg":   "image/jpeg",
    ".jpeg":  "image/jpeg",
    ".svg":   "image/svg+xml",
    ".ico":   "image/x-icon",
    ".woff":  "font/woff",
    ".woff2": "font/woff2",
    ".ttf":   "font/ttf",
    ".map":   "application/json",
}

_FALLBACK_HTML = """<!DOCTYPE html>
<html lang="ja">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ShuttleScope</title>
<style>
  body{font-family:system-ui,sans-serif;background:#0f172a;color:#f1f5f9;
       display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;}
  .card{background:#1e293b;border-radius:12px;padding:32px 40px;text-align:center;max-width:400px;}
  h1{font-size:1.4rem;margin-bottom:8px;}
  p{color:#94a3b8;font-size:.9rem;line-height:1.6;}
  code{background:#0f172a;padding:2px 6px;border-radius:4px;font-size:.85rem;color:#60a5fa;}
</style>
</head>
<body>
<div class="card">
  <h1>ShuttleScope</h1>
  <p>バックエンドは起動しています。<br>
  フロントエンドを配信するには一度ビルドが必要です。</p>
  <p style="margin-top:12px;"><code>npm run build</code><br>
  <span style="font-size:.8rem;color:#64748b;">実行後に再起動してください</span></p>
</div>
</body>
</html>"""


_ASSETS_ALLOWED_EXTS = {".js", ".mjs", ".css", ".map", ".woff", ".woff2", ".ttf", ".otf",
                        ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico",
                        ".json", ".txt", ".wasm"}
_ASSETS_SEGMENT_RE = _re_acl.compile(r"^[A-Za-z0-9_.\-]+$")


@app.get("/assets/{asset_path:path}")
async def serve_assets(asset_path: str):
    """静的アセット配信（JS/CSS/Font 等）— Windows mimetypes に依存せず Content-Type を明示指定"""
    # Path-injection 防止: 事前にセグメントをホワイトリスト化し、絶対パス/空文字/.. を拒否
    if not asset_path or asset_path.startswith(("/", "\\")):
        raise HTTPException(status_code=404)
    segments = asset_path.replace("\\", "/").split("/")
    for seg in segments:
        if not seg or seg in (".", "..") or not _ASSETS_SEGMENT_RE.match(seg):
            raise HTTPException(status_code=404)
    _assets_root = _assets_dir.resolve()
    candidate = (_assets_root / "/".join(segments)).resolve()
    # Path 配下限定
    try:
        candidate.relative_to(_assets_root)
    except ValueError:
        raise HTTPException(status_code=404)
    if candidate.suffix.lower() not in _ASSETS_ALLOWED_EXTS:
        raise HTTPException(status_code=404)
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404)
    media_type = _MIME_MAP.get(candidate.suffix.lower(), "application/octet-stream")
    return FileResponse(str(candidate), media_type=media_type)


@app.get("/")
async def spa_root(request: StarletteRequest):
    """React SPA エントリポイント（ブラウザ / LAN / トンネルアクセス用）"""
    if public_site.should_serve_public_site(request):
        return public_site.render_public_home(request)
    if _INDEX_HTML.exists():
        return FileResponse(str(_INDEX_HTML), media_type="text/html; charset=utf-8")
    return HTMLResponse(content=_FALLBACK_HTML)


@app.get("/index.html")
async def spa_index():
    if _INDEX_HTML.exists():
        return FileResponse(str(_INDEX_HTML), media_type="text/html; charset=utf-8")
    return HTMLResponse(content=_FALLBACK_HTML)


@app.get("/{path:path}")
async def spa_catch_all(path: str, request: StarletteRequest):
    """HashRouter 用リダイレクト: /login などのパスを /#/<path> に転送する。
    HashRouter はハッシュ部分でルーティングするため、サーバー側パスで配信すると
    /#/ が /login# になってしまう。リダイレクトで root に統一する。
    公開サイトホストの場合は 404 を返す。"""
    if public_site.should_serve_public_site(request):
        raise HTTPException(status_code=404)
    from fastapi.responses import RedirectResponse
    # Open-redirect 防止: スキーム/プロトコル相対 URL/逆スラッシュを禁止し、英数と一部記号のみ許容
    safe_path = path.lstrip("/").lstrip("\\")
    if "://" in safe_path or safe_path.startswith(("/", "\\")) or "\\" in safe_path:
        raise HTTPException(status_code=404)
    if not _re_acl.match(r"^[A-Za-z0-9_\-./]*$", safe_path):
        raise HTTPException(status_code=404)
    return RedirectResponse(url=f"/#/{safe_path}", status_code=302)


if __name__ == "__main__":
    # R-002: LAN_MODE=true のとき 0.0.0.0 でバインドして LAN 内からアクセス可能にする
    host = "0.0.0.0" if app_settings.LAN_MODE else "127.0.0.1"
    uvicorn.run(
        "backend.main:app",
        host=host,
        port=app_settings.API_PORT,
        reload=app_settings.ENVIRONMENT == "development",
        log_level="info",
        # uvicorn の dictConfig による basicConfig 上書きを防ぐ
        # （これがないとアプリ側 logger.info/warning が全て黙殺される）
        log_config=None,
    )
