"""nginx のファイルログを DB (security_events) に取り込む shipper。

背景:
  nginx 段で 404 にした probe (/.env, /wp-admin 等) や limit_req による 429 は
  FastAPI に到達しないため request_logs / security_events に残らない。この穴を
  埋めるため、nginx の JSON ログを tail して security_events に流す。

取り込み対象:
  - ss_probe.log  -> security_events(event_type='nginx_probe_block', severity='warn')
  - ss_access.log の status==429 -> security_events(event_type='nginx_rate_limit')
    (backend 由来 429 は別途 security_events に入るが、nginx limit_req 由来は
     ここでしか拾えない。多少の重複より取りこぼし回避を優先)

冪等性:
  各ログファイルごとに「最後に読んだバイトオフセット」を state json に保存し、
  差分のみ処理する。ローテーション (サイズが縮んだ) を検知したら先頭から読み直す。

実行:
  Scheduled Task で 1〜5 分間隔で起動する想定 (常駐ではない)。
  backend venv の python で実行し、DATABASE_URL は .env / 環境変数から解決。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# backend パッケージを import できるようにルートを通す
_THIS = Path(__file__).resolve()
_BACKEND_ROOT = _THIS.parent.parent.parent  # shuttlescope/
sys.path.insert(0, str(_BACKEND_ROOT))

from backend.utils.security_log import emit_security_event, emit_request_log  # noqa: E402

# nginx ログの場所 (本番固定。環境変数で上書き可)
NGINX_LOG_DIR = Path(os.environ.get("SS_NGINX_LOG_DIR", r"C:\tools\nginx-1.31.0\logs"))
STATE_FILE = Path(os.environ.get("SS_NGINX_SHIPPER_STATE",
                                 str(_BACKEND_ROOT / "backend" / "data" / "nginx_shipper_state.json")))

# 1 回の起動で処理する最大行数 (暴走防止)。
# 39MB クラスの ss_access.log を実際にドレインしきれる値にしておく。
# 低すぎると「毎回 cap に当たって永久に追いつけない」状態が無音で続く
# (かつては 5000 でこれが起きていた)。
MAX_LINES = int(os.environ.get("SS_NGINX_SHIPPER_MAX_LINES", "50000"))

# 冪等性の安全網: state ファイル消失などで offset が失われても、
# この時間より古いログ行は "生きたイベント" としては取り込まない。
# 0 以下で無制限 (安全網を切る)。
MAX_AGE_HOURS = float(os.environ.get("SS_NGINX_SHIPPER_MAX_AGE_HOURS", "24"))


def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        print(f"[shipper] state save failed: {exc}", file=sys.stderr)


def _iter_new_lines(path: Path, state: dict):
    """前回オフセット以降の新規行を yield。ローテーション検知付き。

    NOTE (重要な過去バグ): `for line in f` はテキストファイルの内部で
    先読みバッファを使うため、ループを `break` した直後の `f.tell()` は
    「実際に yield した最後の行の直後」を指さない。先読み分だけ余計に
    進んでいることがあり、39MB の ss_access.log を MAX_LINES=5000 で
    毎回打ち切るケースではこのズレが致命的で、保存された offset が
    実際に読み終えた位置と一致せず、結果的に同じ範囲を何度も再取り込み
    し続けていた (production では state に ss_access.log のキー自体が
    一度も保存されず、常に offset=0 から読み直す状態になっていた)。
    `f.readline()` をループで呼ぶ方式なら先読みは発生せず、各呼び出し
    直後の `f.tell()` は「その行を読み終えた直後の厳密なバイトオフセッ
    ト」と一致する。これを利用して state[key] を必ず正確な値にする。"""
    key = path.name
    if not path.exists():
        return
    size = path.stat().st_size
    last = int(state.get(key, 0))
    if size < last:
        # truncate / rotate されたので先頭から
        last = 0
    if size == last:
        return
    count = 0
    with path.open("r", encoding="utf-8", errors="replace") as f:
        f.seek(last)
        pos = last
        while count < MAX_LINES:
            raw = f.readline()
            if not raw:
                break  # EOF
            pos = f.tell()  # この行を読み終えた直後の厳密なオフセット
            line = raw.strip()
            if line:
                yield line
                count += 1
        state[key] = pos
        if count >= MAX_LINES:
            remaining = max(0, size - pos)
            print(f"[shipper] WARNING: {key} hit MAX_LINES={MAX_LINES} cap, "
                  f"{remaining} bytes still unread (will continue next run)",
                  file=sys.stderr)


def _parse_log_ts(raw) -> "datetime | None":
    """ログ行の ts (ISO-8601, 例: 2026-07-24T09:45:21+09:00) を parse。
    失敗したら None を返す (呼び出し側は emit_* に ts を渡さず、
    DB 側の now() フォールバックに委ねる)。"""
    if not raw:
        return None
    try:
        s = str(raw)
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _too_old(ts, max_age_hours: float) -> bool:
    """冪等性の安全網。ts が cutoff より古ければ True。
    max_age_hours <= 0 は無制限 (常に False)。
    ts がオフセット無し (naive) で比較不能な場合も安全側で False。"""
    if max_age_hours <= 0 or ts is None:
        return False
    if ts.tzinfo is None:
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    return ts < cutoff


def _ship_probe_log(state: dict) -> tuple[int, int]:
    """戻り値: (取り込み件数, 古すぎて skip した件数)"""
    n = 0
    skipped_old = 0
    for line in _iter_new_lines(NGINX_LOG_DIR / "ss_probe.log", state):
        try:
            d = json.loads(line)
        except Exception:
            continue
        ts = _parse_log_ts(d.get("ts"))
        if _too_old(ts, MAX_AGE_HOURS):
            skipped_old += 1
            continue
        emit_security_event(
            "nginx_probe_block",
            severity="warn",
            ip_addr=d.get("cf") or d.get("remote"),
            path=d.get("uri"),
            method=d.get("method"),
            ua=d.get("ua"),
            details={
                "status": d.get("status"),
                "country": d.get("country"),
                "ray": d.get("ray"),
                "host": d.get("host"),
                "source": "nginx",
            },
            ts=ts,  # None なら emit 側が now() にフォールバック
        )
        n += 1
    if skipped_old:
        print(f"[shipper] ss_probe.log: skipped {skipped_old} line(s) older than "
              f"{MAX_AGE_HOURS}h (idempotence guard)")
    return n, skipped_old


def _to_ms(rt) -> int:
    # nginx $request_time は秒 (小数)。ms に変換。
    try:
        return int(round(float(rt) * 1000))
    except Exception:
        return 0


def _split_uri(uri: str):
    # "/path?query" -> ("/path", "query")
    if not uri:
        return "", None
    if "?" in uri:
        p, q = uri.split("?", 1)
        return p, q
    return uri, None


def _ship_access_log(state: dict) -> tuple[int, int]:
    """ss_access.log 全行を request_logs(source='nginx') に取り込む。
    backend RequestLogMiddleware の source='backend' 行とは区別される
    (proxy された request は 2 行になるが source で識別可能)。
    加えて status==429 は nginx limit_req 由来として security_events にも残す。
    戻り値: (取り込み件数, 古すぎて skip した件数)"""
    n = 0
    skipped_old = 0
    for line in _iter_new_lines(NGINX_LOG_DIR / "ss_access.log", state):
        try:
            d = json.loads(line)
        except Exception:
            continue
        ts = _parse_log_ts(d.get("ts"))
        if _too_old(ts, MAX_AGE_HOURS):
            skipped_old += 1
            continue
        path, query = _split_uri(d.get("uri") or "")
        try:
            status = int(d.get("status") or 0)
        except Exception:
            status = 0
        emit_request_log(
            method=d.get("method") or "",
            path=path,
            status=status,
            duration_ms=_to_ms(d.get("rt")),
            query=query,
            ip_addr=d.get("cf") or d.get("remote"),
            xff=d.get("xff"),
            ua=d.get("ua"),
            referer=d.get("ref"),
            cf_ray=d.get("ray"),
            country=d.get("country"),
            bytes_out=(int(d["bytes"]) if str(d.get("bytes", "")).isdigit() else None),
            source="nginx",
            ts=ts,  # None なら emit 側が now() にフォールバック
        )
        n += 1
        if status == 429:
            emit_security_event(
                "nginx_rate_limit",
                severity="warn",
                ip_addr=d.get("cf") or d.get("remote"),
                path=path,
                method=d.get("method"),
                ua=d.get("ua"),
                details={"country": d.get("country"), "ray": d.get("ray"),
                         "host": d.get("host"), "source": "nginx_limit_req"},
                ts=ts,  # 同じログ行由来なので同じ ts を使う (INSERT 時刻ではない)
            )
    if skipped_old:
        print(f"[shipper] ss_access.log: skipped {skipped_old} line(s) older than "
              f"{MAX_AGE_HOURS}h (idempotence guard)")
    return n, skipped_old


def main() -> int:
    state = _load_state()
    try:
        probe, probe_skipped = _ship_probe_log(state)
        access, access_skipped = _ship_access_log(state)
        _save_state(state)
        print(f"[shipper] probe={probe} access={access} "
              f"skipped_old={probe_skipped + access_skipped}")
        return 0
    except Exception as exc:
        print(f"[shipper] error: {exc}", file=sys.stderr)
        # state は途中まででも保存 (重複取り込みより取りこぼし回避は呼び出し側調整)
        _save_state(state)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
