"""稼働状況の自動監視 (status.claude.com 風)。

コンポーネント別 (api / database / tunnel / gpu / worker) にヘルスを定期サンプリングして
`health_samples` に記録し、劣化/停止が連続したら `status_incidents` を **自動 open/resolve**
する。公開ステータスページの「現在状態・負荷・稼働率(uptime)・障害区間」の集計元。

設計方針:
- backend と DB はローカルなので自己記録でき、外部認証情報は不要。
- 「いつ・どのコンポーネントが・どれくらい逼迫していたか」を残すのが目的。
- GPU の高負荷は正常 (解析中は当然) なので incident にはせず、metric として可視化のみ。
  GPU が「使えない/VRAM 枯渇」のときだけ degraded/down 扱いにする。
- 完全ダウン (backend 自体が死ぬ) は自己記録不可。そこは外部プローブ (将来) で補う。
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from backend.db.database import SessionLocal
from backend.db.models import HealthSample, StatusIncident

logger = logging.getLogger(__name__)

SAMPLE_INTERVAL_SEC = 600        # 10 分ごと (1 分は過剰なので緩和)
SAMPLE_RETENTION_DAYS = 95       # status.claude.com 風の 90 日バー + 余裕
UPTIME_WINDOW_DAYS = 90          # 稼働率/履歴バーの表示日数
CONSECUTIVE_TO_OPEN = 2          # 連続 N 回 劣化/停止 で incident 自動 open
CONSECUTIVE_TO_RESOLVE = 2       # 連続 N 回 operational で自動 resolve

OPERATIONAL, DEGRADED, DOWN = "operational", "degraded", "down"

# component 定義: key -> 表示名 + 自動 incident の severity (down/degraded 時)
COMPONENTS = [
    {"key": "api",      "ja": "バックエンドAPI", "en": "Backend API",      "sev_down": "critical", "sev_degraded": "minor"},
    {"key": "database", "ja": "データベース",     "en": "Database",         "sev_down": "critical", "sev_degraded": "major"},
    {"key": "tunnel",   "ja": "公開トンネル",     "en": "Public tunnel",    "sev_down": "critical", "sev_degraded": "major"},
    {"key": "gpu",      "ja": "GPU",              "en": "GPU",              "sev_down": "major",    "sev_degraded": "minor"},
    {"key": "worker",   "ja": "解析ワーカー",     "en": "Analysis worker",  "sev_down": "major",    "sev_degraded": "minor"},
]
_COMP_BY_KEY = {c["key"]: c for c in COMPONENTS}
COMPONENT_KEYS = [c["key"] for c in COMPONENTS]

# 公開ページに出す自動 incident の文言 (公開可・汎用。内部詳細は出さない)。
_AUTO_TEXT = {
    "api":      ("バックエンドが高負荷です",       "サーバの処理が一時的に混み合っています。"),
    "database": ("データベースが不安定です",        "データ処理の応答が一時的に低下しています。"),
    "tunnel":   ("公開トンネルに接続できません",     "外部からのアクセスが一時的に不可となっています。"),
    "gpu":      ("GPU が利用できません",             "解析処理が一時的に利用できない状態です。"),
    "worker":   ("解析ワーカーが応答しません",        "解析ジョブの処理が一時的に滞っています。"),
}


# ── 個別チェック (status, metric, detail) を返す。例外は投げない。 ──────────────

def _check_api() -> tuple[str, Optional[float], Optional[str]]:
    """API プロセス自身。レスポンスできている時点で生存。CPU/RAM 逼迫を degraded に。"""
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=0.0)
        ram = psutil.virtual_memory().percent
    except Exception:
        return OPERATIONAL, None, None
    status = DEGRADED if (cpu >= 92 or ram >= 94) else OPERATIONAL
    return status, float(cpu), f"CPU {cpu:.0f}% / RAM {ram:.0f}%"


def _check_database(db) -> tuple[str, Optional[float], Optional[str]]:
    from sqlalchemy import text
    t0 = time.monotonic()
    try:
        db.execute(text("SELECT 1"))
        ms = (time.monotonic() - t0) * 1000.0
    except Exception:
        return DOWN, None, "応答なし"
    status = DEGRADED if ms >= 400 else OPERATIONAL
    return status, float(ms), f"応答 {ms:.0f}ms"


def _check_gpu() -> tuple[str, Optional[float], Optional[str]]:
    """高負荷は正常 (解析中は当然) なので metric 表示のみ。
    probe 不可 = down、VRAM 枯渇 = degraded。"""
    try:
        from backend.services import gpu_health
        p = gpu_health.probe()
    except Exception:
        return OPERATIONAL, None, None  # GPU 監視自体が無い環境では非対象扱い
    if not p.get("available"):
        return DOWN, None, "利用不可"
    devs = [d for d in p.get("devices", []) if "util_gpu_pct" in d]
    if not devs:
        return DOWN, None, "デバイス情報なし"
    util = max(int(d["util_gpu_pct"]) for d in devs)
    used = sum(int(d["vram_used_mb"]) for d in devs)
    total = sum(int(d["vram_total_mb"]) for d in devs)
    free_pct = 100.0 * (total - used) / total if total else 100.0
    status = DEGRADED if free_pct < 3.0 else OPERATIONAL  # VRAM ほぼ枯渇のみ degraded
    detail = f"GPU {util}% / VRAM {used // 1024}.{(used % 1024) * 10 // 1024}/{total // 1024}GB"
    return status, float(util), detail


def _worker_lock_path() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "worker.lock"


def _check_worker() -> tuple[str, Optional[float], Optional[str]]:
    """lock があり pid 生存 = 稼働。lock はあるが pid 死亡 = degraded(クラッシュ)。
    lock 無し = アイドル(operational 扱い: ワーカー常駐は必須ではないため誤報を避ける)。"""
    lock = _worker_lock_path()
    try:
        if not lock.exists():
            return OPERATIONAL, None, "アイドル"
        from backend.pipeline.worker import _FileLock
        alive = _FileLock.is_pid_alive(str(lock))
        if alive:
            return OPERATIONAL, None, "稼働中"
        return DEGRADED, None, "応答なし"
    except Exception:
        return OPERATIONAL, None, None


def _check_tunnel() -> tuple[str, Optional[float], Optional[str]]:
    """cloudflared プロセス生存で判定。metrics endpoint が env で指定されていれば
    edge 接続数 (cloudflared_tunnel_ha_connections) も見る。"""
    url = os.environ.get("CLOUDFLARED_METRICS_URL")
    if url:
        try:
            import urllib.request
            txt = urllib.request.urlopen(url, timeout=3).read().decode("utf-8", "replace")
            conns = _parse_ha_connections(txt)
            if conns is not None:
                return (OPERATIONAL, float(conns), f"edge 接続 {conns}") if conns > 0 else (DOWN, 0.0, "edge 切断")
        except Exception:
            pass  # metrics 取得失敗 → プロセス判定にフォールバック
    try:
        import psutil
        for p in psutil.process_iter(["name"]):
            try:
                if "cloudflared" in (p.info.get("name") or "").lower():
                    return OPERATIONAL, None, "稼働中"
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        return OPERATIONAL, None, None  # psutil 不可環境では非対象
    return DOWN, None, "プロセス停止"


def _parse_ha_connections(metrics_text: str) -> Optional[int]:
    total = None
    for line in metrics_text.splitlines():
        if line.startswith("cloudflared_tunnel_ha_connections"):
            try:
                total = (total or 0) + int(float(line.rsplit(" ", 1)[1]))
            except (ValueError, IndexError):
                continue
    return total


_CHECKS = {
    "api": lambda db: _check_api(),
    "database": lambda db: _check_database(db),
    "tunnel": lambda db: _check_tunnel(),
    "gpu": lambda db: _check_gpu(),
    "worker": lambda db: _check_worker(),
}


# ── サンプリング + 自動 incident 管理 ────────────────────────────────────────

def sample_components(db) -> list[dict]:
    """全コンポーネントを 1 回チェックして結果リストを返す (DB 書き込みはしない)。"""
    out = []
    for key in COMPONENT_KEYS:
        try:
            status, metric, detail = _CHECKS[key](db)
        except Exception as exc:  # noqa: BLE001
            logger.debug("health check %s failed: %s", key, exc)
            status, metric, detail = OPERATIONAL, None, None
        out.append({"component": key, "status": status, "metric": metric, "detail": detail})
    return out


def _recent_statuses(db, component: str, limit: int) -> list[str]:
    rows = (
        db.query(HealthSample.status)
        .filter(HealthSample.component == component)
        .order_by(HealthSample.sampled_at.desc())
        .limit(limit)
        .all()
    )
    return [r[0] for r in rows]


def _open_auto_incident(db, component: str):
    return (
        db.query(StatusIncident)
        .filter(StatusIncident.source == "auto",
                StatusIncident.component == component,
                StatusIncident.status != "resolved")
        .order_by(StatusIncident.began_at.desc())
        .first()
    )


def _manage_auto_incident(db, component: str, now: datetime) -> None:
    """直近サンプルの連続性を見て自動 incident を open / resolve する。"""
    comp = _COMP_BY_KEY.get(component)
    if not comp:
        return
    recent = _recent_statuses(db, component, max(CONSECUTIVE_TO_OPEN, CONSECUTIVE_TO_RESOLVE))
    existing = _open_auto_incident(db, component)

    bad_streak = (
        len(recent) >= CONSECUTIVE_TO_OPEN
        and all(s in (DEGRADED, DOWN) for s in recent[:CONSECUTIVE_TO_OPEN])
    )
    good_streak = (
        len(recent) >= CONSECUTIVE_TO_RESOLVE
        and all(s == OPERATIONAL for s in recent[:CONSECUTIVE_TO_RESOLVE])
    )

    if existing is None and bad_streak:
        worst_down = any(s == DOWN for s in recent[:CONSECUTIVE_TO_OPEN])
        severity = comp["sev_down"] if worst_down else comp["sev_degraded"]
        title, reason = _AUTO_TEXT.get(component, (f"{component} 異常", None))
        db.add(StatusIncident(
            title=title, reason=reason, severity=severity, component=component,
            status="investigating", began_at=now, source="auto",
        ))
    elif existing is not None and good_streak:
        existing.status = "resolved"
        existing.resolved_at = now


def evaluate_and_record(db, now: Optional[datetime] = None) -> list[dict]:
    """1 tick: 全コンポーネントをサンプリング → health_samples 記録 → 自動 incident 管理 → 古い行を prune。"""
    now = now or datetime.utcnow()
    samples = sample_components(db)
    for s in samples:
        db.add(HealthSample(component=s["component"], status=s["status"],
                            metric=s["metric"], detail=s["detail"], sampled_at=now))
    db.flush()  # 直近サンプルを下の連続判定で参照できるように
    for s in samples:
        _manage_auto_incident(db, s["component"], now)
    # prune
    cutoff = now - timedelta(days=SAMPLE_RETENTION_DAYS)
    db.query(HealthSample).filter(HealthSample.sampled_at < cutoff).delete(synchronize_session=False)
    db.commit()
    return samples


def compute_components(db, now: Optional[datetime] = None) -> list[dict]:
    """公開ステータス用: コンポーネント別の現在状態 + 最新 metric + 24h 稼働率。"""
    from sqlalchemy import func
    now = now or datetime.utcnow()
    since = now - timedelta(hours=24)
    out = []
    for comp in COMPONENTS:
        key = comp["key"]
        latest = (
            db.query(HealthSample)
            .filter(HealthSample.component == key)
            .order_by(HealthSample.sampled_at.desc())
            .first()
        )
        total = (db.query(func.count(HealthSample.id))
                 .filter(HealthSample.component == key, HealthSample.sampled_at >= since).scalar() or 0)
        up = (db.query(func.count(HealthSample.id))
              .filter(HealthSample.component == key, HealthSample.sampled_at >= since,
                      HealthSample.status == OPERATIONAL).scalar() or 0)
        uptime = round(100.0 * up / total, 2) if total else None
        out.append({
            "key": key, "name_ja": comp["ja"], "name_en": comp["en"],
            "status": latest.status if latest else "unknown",
            "metric": latest.metric if latest else None,
            "detail": latest.detail if latest else None,
            "uptime_24h": uptime,
            "sampled_at": latest.sampled_at.isoformat() if latest and latest.sampled_at else None,
        })
    return out


def compute_component_history(db, days: int = UPTIME_WINDOW_DAYS, now: Optional[datetime] = None) -> dict:
    """status.claude.com 風の日次稼働履歴。コンポーネント毎に直近 `days` 日の
    日別ステータス (operational/degraded/down/nodata) と稼働率% を返す。

    重い集計なので /status ページのサーバ描画時のみ呼ぶ (公開 JSON /api/public/status には含めない)。
    日跨ぎ集計は DB 関数の方言差を避けるため Python 側でバケットする。"""
    now = now or datetime.utcnow()
    # バー/稼働率は JST (UTC+9, DST 無し) の暦日で集計する (日本のユーザ基準で「今日」の
    # 境界を合わせる)。health_samples.sampled_at は naive UTC なので +9h して JST 日付化する。
    jst = timedelta(hours=9)
    now_jst = now + jst
    start_jst = (now_jst - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = start_jst - jst  # DB フィルタは UTC のまま行う (sampled_at は naive UTC)
    out = {}
    for comp in COMPONENTS:
        key = comp["key"]
        rows = (
            db.query(HealthSample.sampled_at, HealthSample.status)
            .filter(HealthSample.component == key, HealthSample.sampled_at >= start_utc)
            .all()
        )
        buckets: dict = {}
        up_samples = 0
        for ts, st in rows:
            buckets.setdefault((ts + jst).date(), set()).add(st)
            if st == OPERATIONAL:
                up_samples += 1
        total_samples = len(rows)
        day_list = []
        for i in range(days):
            d = (start_jst + timedelta(days=i)).date()
            sts = buckets.get(d)
            if not sts:
                day_status = "nodata"
            elif DOWN in sts:
                day_status = "down"
            elif DEGRADED in sts:
                day_status = "degraded"
            else:
                day_status = "operational"
            # バーの色は「その日の最悪ステータス」で表現する (claude status 同様)。
            day_list.append({"d": d.isoformat(), "st": day_status})
        out[key] = {
            "days": day_list,
            # 稼働率は「日数」ではなく「サンプル比」で算出する。
            # 旧実装は 1 日に 144 サンプルあるうち 1 回でも down だとその日を丸ごと
            # 非稼働扱いし、観測日数が少ないと 0.00% になっていた (過度に厳しい)。
            # サンプル比なら 144 中 1 回 down は ~99.3% と妥当な値になる。
            "uptime_pct": round(100.0 * up_samples / total_samples, 2) if total_samples else None,
        }
    return out


# ── バックグラウンドループ (FastAPI lifespan から起動) ───────────────────────

def _tick_blocking() -> None:
    with SessionLocal() as db:
        try:
            evaluate_and_record(db)
        except Exception:
            db.rollback()
            raise


def _seconds_to_next_boundary(now: Optional[datetime] = None) -> float:
    """次の壁時計 10 分境界 (:00/:10/:20/:30/:40/:50) までの秒数を返す。
    sampled_at は UTC (datetime.utcnow) なので UTC 壁時計に揃える。
    境界ちょうどの場合は次の境界 (= SAMPLE_INTERVAL_SEC 後) を返し、二重発火を避ける。"""
    now = now or datetime.utcnow()
    step = SAMPLE_INTERVAL_SEC
    # 当日 0:00(UTC) からの経過秒で計算し、次の step 倍数までの残りを求める。
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed = (now - midnight).total_seconds()
    remainder = elapsed % step
    wait = step - remainder if remainder > 0 else step
    return wait


async def _monitor_loop() -> None:
    # 各 tick の前に次の壁時計 10 分境界まで sleep する。毎回再計算してドリフトを防ぐ
    # (固定 600s sleep はしない)。起動直後も境界まで待ってから開始するため、
    # テストの短命 lifespan では 1 度も tick しない = 副作用なし。
    while True:
        try:
            await asyncio.sleep(_seconds_to_next_boundary())
            await asyncio.get_event_loop().run_in_executor(None, _tick_blocking)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("status_monitor tick failed: %s", exc)


def start_status_monitor() -> "asyncio.Task":
    """lifespan から呼ぶ。監視ループの asyncio.Task を返す (shutdown 時に cancel する)。"""
    return asyncio.create_task(_monitor_loop())
