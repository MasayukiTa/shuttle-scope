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
from pathlib import Path

# backend パッケージを import できるようにルートを通す
_THIS = Path(__file__).resolve()
_BACKEND_ROOT = _THIS.parent.parent.parent  # shuttlescope/
sys.path.insert(0, str(_BACKEND_ROOT))

from backend.utils.security_log import emit_security_event  # noqa: E402

# nginx ログの場所 (本番固定。環境変数で上書き可)
NGINX_LOG_DIR = Path(os.environ.get("SS_NGINX_LOG_DIR", r"C:\tools\nginx-1.31.0\logs"))
STATE_FILE = Path(os.environ.get("SS_NGINX_SHIPPER_STATE",
                                 str(_BACKEND_ROOT / "backend" / "data" / "nginx_shipper_state.json")))

# 1 回の起動で処理する最大行数 (暴走防止)
MAX_LINES = int(os.environ.get("SS_NGINX_SHIPPER_MAX_LINES", "5000"))


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
    """前回オフセット以降の新規行を yield。ローテーション検知付き。"""
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
        for line in f:
            line = line.strip()
            if line:
                yield line
                count += 1
                if count >= MAX_LINES:
                    break
        state[key] = f.tell()


def _ship_probe_log(state: dict) -> int:
    n = 0
    for line in _iter_new_lines(NGINX_LOG_DIR / "ss_probe.log", state):
        try:
            d = json.loads(line)
        except Exception:
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
        )
        n += 1
    return n


def _ship_access_429(state: dict) -> int:
    n = 0
    for line in _iter_new_lines(NGINX_LOG_DIR / "ss_access.log", state):
        try:
            d = json.loads(line)
        except Exception:
            continue
        if str(d.get("status")) != "429":
            continue
        emit_security_event(
            "nginx_rate_limit",
            severity="warn",
            ip_addr=d.get("cf") or d.get("remote"),
            path=d.get("uri"),
            method=d.get("method"),
            ua=d.get("ua"),
            details={
                "country": d.get("country"),
                "ray": d.get("ray"),
                "host": d.get("host"),
                "rt": d.get("rt"),
                "source": "nginx_limit_req",
            },
        )
        n += 1
    return n


def main() -> int:
    state = _load_state()
    try:
        probe = _ship_probe_log(state)
        rl = _ship_access_429(state)
        _save_state(state)
        print(f"[shipper] probe={probe} rate_limit={rl}")
        return 0
    except Exception as exc:
        print(f"[shipper] error: {exc}", file=sys.stderr)
        # state は途中まででも保存 (重複取り込みより取りこぼし回避は呼び出し側調整)
        _save_state(state)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
