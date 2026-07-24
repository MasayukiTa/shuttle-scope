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

# ── 90日バーの連続グラデーション (Atlassian Statuspage 準拠) ──────────────────
# Statuspage の稼働履歴バーは離散色ではなく、その日のダウンタイム深刻度を
# green→yellow→orange→red の 4 アンカー間で線形補間して fill 色を決めている。
# アンカー HEX は status.claude.com のバー SVG から実測した値:
#   green #76AD2A → yellow #FAA72A → orange #E86235 → red #E04343
# 深刻度 severity は各チェックが生メトリクス (CPU%/応答ms/VRAM使用率…) から連続値
# [0,1] で算出して health_samples.severity に保存する。バー/スロットの色はこの severity を
# 補間する (status の離散重みではない = degraded 内の「downしかけ」も色で表現できる)。
# severity 不明の旧行のみ status から離散フォールバックする。
_BAR_ANCHORS = (
    (0.0,        (0x76, 0xAD, 0x2A)),
    (1.0 / 3.0,  (0xFA, 0xA7, 0x2A)),
    (2.0 / 3.0,  (0xE8, 0x62, 0x35)),
    (1.0,        (0xE0, 0x43, 0x43)),
)
_RANK = {OPERATIONAL: 0, DEGRADED: 1, DOWN: 2}
_RANK_ST = {0: OPERATIONAL, 1: DEGRADED, 2: DOWN}


def severity_to_hex(sev: float) -> str:
    """深刻度スコア [0,1] を 4 アンカー線形補間で '#RRGGBB' に変換する。"""
    if sev <= 0.0:
        return "#%02X%02X%02X" % _BAR_ANCHORS[0][1]
    if sev >= 1.0:
        return "#%02X%02X%02X" % _BAR_ANCHORS[-1][1]
    for i in range(len(_BAR_ANCHORS) - 1):
        s0, c0 = _BAR_ANCHORS[i]
        s1, c1 = _BAR_ANCHORS[i + 1]
        if sev <= s1:
            t = (sev - s0) / (s1 - s0) if s1 > s0 else 0.0
            return "#%02X%02X%02X" % (
                round(c0[0] + (c1[0] - c0[0]) * t),
                round(c0[1] + (c1[1] - c0[1]) * t),
                round(c0[2] + (c1[2] - c0[2]) * t),
            )
    return "#%02X%02X%02X" % _BAR_ANCHORS[-1][1]


def _piecewise_severity(x, green, deg, crit) -> Optional[float]:
    """生メトリクス x を区分線形で severity 化する。

    green→0.0(緑) / deg→1/3(黄=degraded境界) / crit→1.0(赤=危機)。
    deg〜crit を連続 ramp するため「degraded のままでも crit に近いほど橙→赤」になる。
    x is None なら None (= severity 不明、status フォールバックに委ねる)。
    """
    if x is None:
        return None
    y = 1.0 / 3.0
    if x <= green:
        return 0.0
    if x <= deg:
        return y * (x - green) / (deg - green) if deg > green else y
    if x <= crit:
        return y + (1.0 - y) * (x - deg) / (crit - deg) if crit > deg else 1.0
    return 1.0


def _severity_from_status(status: str) -> float:
    """severity 未記録の旧行用の離散フォールバック (operational=0 / degraded=1/3 / down=1)。"""
    return {OPERATIONAL: 0.0, DEGRADED: 1.0 / 3.0, DOWN: 1.0}.get(status, 0.0)

# component 定義: key -> 表示名 + 自動 incident の severity (down/degraded 時)
COMPONENTS = [
    {"key": "api",      "ja": "バックエンドAPI", "en": "Backend API",      "sev_down": "critical", "sev_degraded": "minor"},
    {"key": "database", "ja": "データベース",     "en": "Database",         "sev_down": "critical", "sev_degraded": "major"},
    {"key": "tunnel",   "ja": "公開トンネル",     "en": "Public tunnel",    "sev_down": "critical", "sev_degraded": "major"},
    {"key": "gpu",      "ja": "GPU",              "en": "GPU",              "sev_down": "major",    "sev_degraded": "minor"},
    {"key": "worker",   "ja": "解析ワーカー",     "en": "Analysis worker",  "sev_down": "major",    "sev_degraded": "minor"},
    # 時計ズレは TOTP/MFA とトークン有効期限の前提。ずれるとログイン不能になる。
    {"key": "clock",    "ja": "サーバ時刻",       "en": "Server clock",     "sev_down": "critical", "sev_degraded": "minor"},
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
    "clock":    ("サーバ時刻がずれています",          "ログイン (二段階認証) が一時的に失敗する場合があります。"),
}


# ── 個別チェック (status, metric, detail, severity) を返す。例外は投げない。 ────
# severity ∈[0,1] は生メトリクスから算出した連続深刻度。None = 不明 (status フォールバック)。

def _check_api() -> tuple[str, Optional[float], Optional[str], Optional[float]]:
    """API プロセス自身。レスポンスできている時点で生存。CPU/RAM 逼迫を degraded に。
    severity は CPU% と RAM% の悪い方を連続 ramp (緑70/黄92・94/赤99)。"""
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=0.0)
        ram = psutil.virtual_memory().percent
    except Exception:
        return OPERATIONAL, None, None, None
    status = DEGRADED if (cpu >= 92 or ram >= 94) else OPERATIONAL
    sev = max(_piecewise_severity(cpu, 70, 92, 99),
              _piecewise_severity(ram, 75, 94, 99))
    return status, float(cpu), f"CPU {cpu:.0f}% / RAM {ram:.0f}%", sev


def _check_database(db) -> tuple[str, Optional[float], Optional[str], Optional[float]]:
    from sqlalchemy import text
    t0 = time.monotonic()
    try:
        db.execute(text("SELECT 1"))
        ms = (time.monotonic() - t0) * 1000.0
    except Exception:
        return DOWN, None, "応答なし", 1.0
    status = DEGRADED if ms >= 400 else OPERATIONAL
    sev = _piecewise_severity(ms, 50, 400, 1500)  # 緑50ms / 黄400ms / 赤1500ms
    return status, float(ms), f"応答 {ms:.0f}ms", sev


def _check_gpu() -> tuple[str, Optional[float], Optional[str], Optional[float]]:
    """高負荷は正常 (解析中は当然) なので util% は色に使わない。
    severity は VRAM 使用率で算出 (緑90% / 黄97%=現degraded境界 / 赤99.5%)。
    probe 不可 = down、VRAM 枯渇 = degraded。"""
    try:
        from backend.services import gpu_health
        p = gpu_health.probe()
    except Exception:
        return OPERATIONAL, None, None, None  # GPU 監視自体が無い環境では非対象扱い
    if not p.get("available"):
        return DOWN, None, "利用不可", 1.0
    devs = [d for d in p.get("devices", []) if "util_gpu_pct" in d]
    if not devs:
        return DOWN, None, "デバイス情報なし", 1.0
    util = max(int(d["util_gpu_pct"]) for d in devs)
    used = sum(int(d["vram_used_mb"]) for d in devs)
    total = sum(int(d["vram_total_mb"]) for d in devs)
    free_pct = 100.0 * (total - used) / total if total else 100.0
    used_pct = 100.0 * used / total if total else 0.0
    status = DEGRADED if free_pct < 3.0 else OPERATIONAL  # VRAM ほぼ枯渇のみ degraded
    # 色は VRAM 逼迫のみで動かす (util=混雑度は健全性ではないので severity に含めない)。
    sev = _piecewise_severity(used_pct, 90, 97, 99.5)
    detail = f"GPU {util}% / VRAM {used // 1024}.{(used % 1024) * 10 // 1024}/{total // 1024}GB"
    return status, float(util), detail, sev


def _worker_lock_path() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "worker.lock"


def _check_worker() -> tuple[str, Optional[float], Optional[str], Optional[float]]:
    """lock があり pid 生存 = 稼働。lock はあるが pid 死亡 = degraded(クラッシュ)。
    lock 無し = アイドル(operational 扱い: ワーカー常駐は必須ではないため誤報を避ける)。
    連続値が無いので severity は 2 値 (稼働/アイドル=0.0, クラッシュ=1.0)。"""
    lock = _worker_lock_path()
    try:
        if not lock.exists():
            return OPERATIONAL, None, "アイドル", 0.0
        from backend.pipeline.worker import _FileLock
        alive = _FileLock.is_pid_alive(str(lock))
        if alive:
            return OPERATIONAL, None, "稼働中", 0.0
        return DEGRADED, None, "応答なし", 1.0
    except Exception:
        return OPERATIONAL, None, None, None


def _check_tunnel() -> tuple[str, Optional[float], Optional[str], Optional[float]]:
    """cloudflared プロセス生存で判定。metrics endpoint が env で指定されていれば
    edge 接続数 (cloudflared_tunnel_ha_connections) も見る。
    連続値が無いので severity は 2 値 (接続あり=0.0 / 切断=1.0)。"""
    url = os.environ.get("CLOUDFLARED_METRICS_URL")
    if url:
        try:
            import urllib.request
            txt = urllib.request.urlopen(url, timeout=3).read().decode("utf-8", "replace")
            conns = _parse_ha_connections(txt)
            if conns is not None:
                return ((OPERATIONAL, float(conns), f"edge 接続 {conns}", 0.0) if conns > 0
                        else (DOWN, 0.0, "edge 切断", 1.0))
        except Exception:
            pass  # metrics 取得失敗 → プロセス判定にフォールバック
    try:
        import psutil
        for p in psutil.process_iter(["name"]):
            try:
                if "cloudflared" in (p.info.get("name") or "").lower():
                    return OPERATIONAL, None, "稼働中", 0.0
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        return OPERATIONAL, None, None, None  # psutil 不可環境では非対象
    return DOWN, None, "プロセス停止", 1.0


def _parse_ha_connections(metrics_text: str) -> Optional[int]:
    total = None
    for line in metrics_text.splitlines():
        if line.startswith("cloudflared_tunnel_ha_connections"):
            try:
                total = (total or 0) + int(float(line.rsplit(" ", 1)[1]))
            except (ValueError, IndexError):
                continue
    return total


# ── 時計ズレ (clock) ────────────────────────────────────────────────────────
#
# 背景 (障害): 2026-07 に Windows Time サービス (w32time) が停止し、サーバ時計が
# TOTP の検証窓 (±30 秒) を外れて admin が MFA でログインできなくなった。
# 時計がずれても「サービスは全部緑」で何の警告も出ず、原因判明まで時間を要した。
#
# 判定は 2 系統:
#   1) SNTP で外部の基準時刻と比較したオフセット (本命。実際に壊れる量そのもの)
#   2) w32time サービスの稼働状態 (Windows のみ。NTP に届かなくても検知できる)

_NTP_SERVERS = ("time.cloudflare.com", "ntp.nict.jp", "pool.ntp.org")
_NTP_TIMEOUT_SEC = 2.0
# TOTP の窓は ±30 秒 (前後 1 ステップ許容)。余裕を持って警告を出す。
_CLOCK_WARN_SEC = 5.0     # これを超えたら degraded
_CLOCK_DOWN_SEC = 25.0    # これを超えたら TOTP が落ち始める = down


def _sntp_offset_sec(server: str, timeout: float = _NTP_TIMEOUT_SEC) -> Optional[float]:
    """SNTP (RFC 4330) でサーバとのオフセット秒を返す。失敗時 None。

    外部ライブラリを足さずに済むよう 48 byte のパケットを直接組む。
    戻り値 > 0 はローカル時計が進んでいることを意味する。
    """
    import socket
    import struct as _struct

    # LI=0, VN=3, Mode=3 (client)
    packet = b"\x1b" + 47 * b"\0"
    # NTP epoch (1900-01-01) と UNIX epoch (1970-01-01) の差
    NTP_DELTA = 2_208_988_800
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(timeout)
        t0 = time.time()
        sock.sendto(packet, (server, 123))
        data, _ = sock.recvfrom(48)
        t3 = time.time()
    except Exception:
        return None
    finally:
        sock.close()
    if len(data) < 48:
        return None
    # transmit timestamp = offset 40..47 (秒 32bit + 小数 32bit)
    secs, frac = _struct.unpack("!II", data[40:48])
    server_time = (secs - NTP_DELTA) + frac / 2 ** 32
    # 往復遅延の半分を引いて片道分を補正する
    rtt = t3 - t0
    return (t0 + rtt / 2.0) - server_time


def _w32time_running() -> Optional[bool]:
    """Windows Time サービスが動いているか。Windows 以外 / 判定不能なら None。"""
    if os.name != "nt":
        return None
    try:
        import subprocess
        out = subprocess.run(
            ["sc", "query", "w32time"],
            capture_output=True, text=True, timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        return None
    if out.returncode != 0:
        return None
    return "RUNNING" in (out.stdout or "").upper()


def _check_clock() -> tuple[str, Optional[float], Optional[str], Optional[float]]:
    """時計ズレ。TOTP/MFA と署名検証の前提なので、ずれ始めた段階で気付けるようにする。"""
    offset: Optional[float] = None
    for server in _NTP_SERVERS:
        offset = _sntp_offset_sec(server)
        if offset is not None:
            break

    svc_running = _w32time_running()

    if offset is None:
        # NTP に到達できない環境 (UDP 123 遮断など) でも、時刻同期サービスが
        # 落ちていることは分かる。落ちていれば必ず degraded にする
        # (「測れないので緑」で 24 日気付かなかったのが前回の障害)。
        if svc_running is False:
            return DEGRADED, None, "時刻同期サービスが停止しています", 0.5
        return OPERATIONAL, None, "オフセット測定不可", None

    abs_off = abs(offset)
    if abs_off >= _CLOCK_DOWN_SEC:
        status = DOWN
    elif abs_off >= _CLOCK_WARN_SEC or svc_running is False:
        status = DEGRADED
    else:
        status = OPERATIONAL
    # detail は無認証の公開ステータスページに出るため、精密なオフセットを
    # そのまま晒さず秒単位に丸める (metric 側に生値は残る)。
    detail = "同期済み" if abs_off < 1.0 else f"ズレ 約{offset:+.0f}秒"
    if svc_running is False:
        detail += " / 時刻同期サービス停止"
    sev = _piecewise_severity(abs_off, 1.0, _CLOCK_WARN_SEC, _CLOCK_DOWN_SEC)
    return status, float(offset), detail, sev


_CHECKS = {
    "api": lambda db: _check_api(),
    "database": lambda db: _check_database(db),
    "tunnel": lambda db: _check_tunnel(),
    "gpu": lambda db: _check_gpu(),
    "worker": lambda db: _check_worker(),
    "clock": lambda db: _check_clock(),
}


# ── サンプリング + 自動 incident 管理 ────────────────────────────────────────

def sample_components(db) -> list[dict]:
    """全コンポーネントを 1 回チェックして結果リストを返す (DB 書き込みはしない)。"""
    out = []
    for key in COMPONENT_KEYS:
        try:
            status, metric, detail, severity = _CHECKS[key](db)
        except Exception as exc:  # noqa: BLE001
            logger.debug("health check %s failed: %s", key, exc)
            status, metric, detail, severity = OPERATIONAL, None, None, None
        out.append({"component": key, "status": status, "metric": metric,
                    "detail": detail, "severity": severity})
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
                            metric=s["metric"], severity=s.get("severity"),
                            detail=s["detail"], sampled_at=now))
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
            db.query(HealthSample.sampled_at, HealthSample.status, HealthSample.severity)
            .filter(HealthSample.component == key, HealthSample.sampled_at >= start_utc)
            .all()
        )
        # 日ごとに [severityの合計, サンプル数, 最悪ステータスrank] を集計する。
        # severity は記録値を使い、None の旧行は status から離散フォールバックする。
        buckets: dict = {}
        up_samples = 0
        for ts, st, sv in rows:
            b = buckets.setdefault((ts + jst).date(), [0.0, 0, 0])
            b[0] += sv if sv is not None else _severity_from_status(st)
            b[1] += 1
            r = _RANK.get(st, 0)
            if r > b[2]:
                b[2] = r
            if st == OPERATIONAL:
                up_samples += 1
        total_samples = len(rows)
        day_list = []
        for i in range(days):
            d = (start_jst + timedelta(days=i)).date()
            b = buckets.get(d)
            if not b or b[1] == 0:
                day_list.append({"d": d.isoformat(), "st": "nodata", "sev": None, "color": None})
                continue
            # 連続グラデーション: その日のダウンタイム深刻度 [0,1] を色に補間する
            # (Statuspage 同様に「離散の最悪色」ではなく downtime 比例の連続色)。
            # st は tooltip/凡例用に最悪ステータスも併記する。
            sev = b[0] / b[1]
            day_list.append({
                "d": d.isoformat(),
                "st": _RANK_ST[b[2]],
                "sev": round(sev, 4),
                "color": severity_to_hex(sev),
            })
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
