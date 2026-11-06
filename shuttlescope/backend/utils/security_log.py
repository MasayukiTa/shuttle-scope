"""security_events / request_logs への低レベル書き込みヘルパ。

設計方針:
  - 失敗しても上位処理を絶対に止めない (DB 落ち時も request は通る)
  - 大量 row に耐えるよう、access_log.py の HMAC chain は使わない
  - request_logs はホットパスから呼ばれるので合成 cost を最小化
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from backend.db.database import SessionLocal
from backend.db.models import RequestLog, SecurityEvent, ErrorLog, AuditEvent


_log = logging.getLogger("shuttlescope.security_log")


def emit_security_event(
    event_type: str,
    *,
    severity: str = "info",
    ip_addr: Optional[str] = None,
    user_id: Optional[int] = None,
    path: Optional[str] = None,
    method: Optional[str] = None,
    ua: Optional[str] = None,
    request_id: Optional[str] = None,
    details: Optional[dict] = None,
    ts: Optional[datetime] = None,
) -> None:
    """security_events に 1 行追加。例外は飲み込んで stdlib log に流す。

    ts: 省略時は DB 側の server_default (INSERT 時刻) が使われる。
    ログ取り込み系 (nginx_log_shipper.py 等) は「イベントが実際に
    発生した時刻」と「INSERT された時刻」がズレるため、ログ行自身の
    ts をここに明示的に渡すこと。渡さないと過去ログの再取り込みが
    "今起きたイベント" として見えてしまう (実際にあったバグ)。"""
    try:
        # JSON column 型なので dict をそのまま渡す (SA が dialect 別に変換)
        body = details or {}
        db: Session = SessionLocal()
        try:
            kwargs = dict(
                event_type=event_type[:40],
                severity=severity[:10],
                ip_addr=(ip_addr or "")[:64] or None,
                user_id=user_id,
                path=(path or "")[:512] or None,
                method=(method or "")[:8] or None,
                ua=(ua or "")[:255] or None,
                request_id=(request_id or "")[:36] or None,
                details=body,
            )
            if ts is not None:
                kwargs["ts"] = ts
            row = SecurityEvent(**kwargs)
            db.add(row)
            db.commit()
        finally:
            db.close()
    except Exception as exc:
        _log.warning("emit_security_event failed: %s (event_type=%s)", exc, event_type)


def emit_request_log(
    *,
    method: str,
    path: str,
    status: int,
    duration_ms: int,
    query: Optional[str] = None,
    user_id: Optional[int] = None,
    ip_addr: Optional[str] = None,
    xff: Optional[str] = None,
    ua: Optional[str] = None,
    referer: Optional[str] = None,
    request_id: Optional[str] = None,
    bytes_in: Optional[int] = None,
    bytes_out: Optional[int] = None,
    cf_ray: Optional[str] = None,
    country: Optional[str] = None,
    source: str = "backend",
    ts: Optional[datetime] = None,
) -> None:
    """request_logs に 1 行追加。例外は飲み込む。

    現状: 同期 INSERT。 1M req/月 (≒ 25 req/min 平均) 程度なら問題なし。
    その上の段階では asyncio.Queue + 背景 flush + COPY に置き換える (Round 2)。

    ts: 省略時は DB 側の server_default (INSERT 時刻) が使われる。
    ログ取り込み系がイベント本来の発生時刻を渡したい場合に使用。"""
    try:
        db: Session = SessionLocal()
        try:
            kwargs = dict(
                method=method[:8],
                path=(path or "")[:512],
                query=(query or "")[:1024] or None,
                status=int(status),
                duration_ms=int(duration_ms),
                user_id=user_id,
                ip_addr=(ip_addr or "")[:64] or None,
                xff=(xff or "")[:255] or None,
                ua=(ua or "")[:255] or None,
                referer=(referer or "")[:255] or None,
                request_id=(request_id or "")[:36] or None,
                bytes_in=bytes_in,
                bytes_out=bytes_out,
                cf_ray=(cf_ray or "")[:32] or None,
                country=(country or "")[:2] or None,
                source=(source or "backend")[:10],
            )
            if ts is not None:
                kwargs["ts"] = ts
            row = RequestLog(**kwargs)
            db.add(row)
            db.commit()
        finally:
            db.close()
    except Exception as exc:
        _log.warning("emit_request_log failed: %s (path=%s)", exc, path)


def emit_audit_event(
    *,
    action: str,
    method: str,
    path: str,
    status: int,
    user_id: Optional[int] = None,
    role: Optional[str] = None,
    ip_addr: Optional[str] = None,
    request_id: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    changed_fields: Optional[list] = None,
    field_count: Optional[int] = None,
    body_hash: Optional[str] = None,
    ts: Optional[datetime] = None,
) -> None:
    """audit_events に 1 行追加。データ変更の主体を追跡する。

    設計上の約束:
      - 本処理(元の作成/更新/削除)とは別セッションで INSERT する。監査の
        書き込み失敗が本来の操作を巻き込んで失敗させてはならない。
      - 例外は握りつぶさず stdlib logger に warning で残す(握りつぶして無言に
        すると「監査が無言で欠落する」事故に気づけない)。
      - 値そのもの(変更後の選手名など)は保存しない。changed_fields は列名の
        一覧のみ、field_count は件数、body_hash は照合用の SHA-256 指紋。
    """
    try:
        cf_str: Optional[str] = None
        if changed_fields is not None:
            # 値は入れない。列名のみを JSON 配列文字列で保存(最大 2KB に抑える)。
            try:
                cf_str = json.dumps(sorted({str(c) for c in changed_fields}), ensure_ascii=False)
            except Exception:
                cf_str = None
            if cf_str is not None and len(cf_str.encode("utf-8")) > 2048:
                cf_str = cf_str.encode("utf-8")[:2048].decode("utf-8", "ignore")
        # テストが conftest で backend.db.database.SessionLocal を差し替えるため、
        # インポート時に束縛したシンボルではなく database モジュール越しに
        # 都度参照する(本番では同一オブジェクトなので挙動は変わらない)。
        from backend.db import database as _dbmod
        db: Session = _dbmod.SessionLocal()
        try:
            kwargs = dict(
                action=(action or "")[:10],
                method=(method or "")[:8],
                path=(path or "")[:512],
                status=int(status),
                user_id=user_id,
                role=(role or "")[:32] or None,
                ip_addr=(ip_addr or "")[:64] or None,
                request_id=(request_id or "")[:36] or None,
                entity_type=(entity_type or "")[:40] or None,
                entity_id=(str(entity_id) if entity_id is not None else "")[:64] or None,
                changed_fields=cf_str,
                field_count=field_count,
                body_hash=(body_hash or "")[:64] or None,
            )
            if ts is not None:
                kwargs["ts"] = ts
            row = AuditEvent(**kwargs)
            db.add(row)
            db.commit()
        finally:
            db.close()
    except Exception as exc:
        _log.warning("emit_audit_event failed: %s (path=%s)", exc, path)


def emit_error_log(
    *,
    exc_type: str,
    message: str,
    traceback_str: Optional[str] = None,
    request_id: Optional[str] = None,
    method: Optional[str] = None,
    path: Optional[str] = None,
    status: Optional[int] = None,
    input_repr: Optional[str] = None,
    internal_code: Optional[str] = None,
    user_id: Optional[int] = None,
    ip_addr: Optional[str] = None,
) -> None:
    """error_logs に未処理例外を 1 行追加。失敗は飲み込む。"""
    try:
        db: Session = SessionLocal()
        try:
            row = ErrorLog(
                request_id=(request_id or "")[:36] or None,
                method=(method or "")[:8] or None,
                path=(path or "")[:512] or None,
                status=status,
                exc_type=(exc_type or "")[:120] or None,
                message=(message or "")[:8000] or None,
                traceback=(traceback_str or "")[:16000] or None,
                input_repr=(input_repr or "")[:4000] or None,
                internal_code=(internal_code or "")[:40] or None,
                user_id=user_id,
                ip_addr=(ip_addr or "")[:64] or None,
            )
            db.add(row)
            db.commit()
        finally:
            db.close()
    except Exception as exc:
        _log.warning("emit_error_log failed: %s (exc_type=%s)", exc, exc_type)
