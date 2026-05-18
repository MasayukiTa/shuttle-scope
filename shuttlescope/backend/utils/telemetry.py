"""製品テレメトリのヘルパー。

- user_id / team_id → HMAC-SHA256 hex digest (64 chars)。
- ProductEvent insert / 集計用クエリ helpers。

法的根拠は PRIVACY.md §テレメトリ章に記載。本ファイル単体では PII を扱わない
(hash 化済みのみ受領)。raw user_id は呼び出し側で hash 化してから渡すこと。
"""
from __future__ import annotations

import hmac
import json
import uuid
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.config import settings
from backend.db.models import ProductEvent


# 強型のイベント名 (typo 防止)。escape hatch は 'ui_event'。
ALLOWED_EVENT_TYPES = frozenset([
    "session_start",
    "session_end",
    "page_view",
    "pass_started",
    "pass_completed",
    "pass_abandoned",
    "input_event",
    "analysis_view",
    "analysis_dwell",
    "analysis_interaction",
    "condition_input",
    "tutorial_step",
    "error_event",
    "network_slow",
    "ui_event",
])

# 1 batch の上限 (DoS 対策)
MAX_EVENTS_PER_BATCH = 200
# props JSON 1 件の上限バイト数 (DoS 対策)
MAX_PROPS_BYTES = 4096


def hash_id(raw: Any) -> Optional[str]:
    """user_id / team_id を HMAC-SHA256(SECRET_KEY, str(raw)) で hash 化。

    DB ダンプから raw を逆引きできないようにする。同一 secret 下では再現性あり
    なので、同一ユーザーのイベント追跡は維持される。
    """
    if raw is None:
        return None
    secret = (settings.SECRET_KEY or "").encode("utf-8")
    msg = str(raw).encode("utf-8")
    return hmac.new(secret, msg, sha256).hexdigest()


def insert_events(
    db: Session,
    events: list[dict],
    user_id: Optional[int],
    team_id: Optional[int],
    role: Optional[str],
    platform: Optional[str],
    app_version: Optional[str],
) -> int:
    """イベントバッチを ProductEvent に挿入。dedup / バリデーション込み。

    Returns: 実際に挿入された件数。
    """
    if not events:
        return 0
    if len(events) > MAX_EVENTS_PER_BATCH:
        events = events[:MAX_EVENTS_PER_BATCH]

    uid_h = hash_id(user_id)
    tid_h = hash_id(team_id)
    inserted = 0
    seen_ids: set[str] = set()

    for e in events:
        et = e.get("event_type")
        if not et or et not in ALLOWED_EVENT_TYPES:
            continue
        eid_raw = e.get("event_id")
        try:
            eid = str(uuid.UUID(str(eid_raw))) if eid_raw else str(uuid.uuid4())
        except (ValueError, TypeError):
            eid = str(uuid.uuid4())
        if eid in seen_ids:
            continue
        seen_ids.add(eid)

        props = e.get("props") or {}
        if not isinstance(props, dict):
            props = {}
        try:
            props_json = json.dumps(props, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError):
            continue
        if len(props_json.encode("utf-8")) > MAX_PROPS_BYTES:
            # 静かに drop (telemetry が止めない原則)
            continue

        client_ts_raw = e.get("client_ts")
        try:
            if isinstance(client_ts_raw, (int, float)):
                client_ts = datetime.utcfromtimestamp(float(client_ts_raw) / 1000.0)
            elif isinstance(client_ts_raw, str):
                # ISO 8601
                s = client_ts_raw.replace("Z", "+00:00")
                client_ts = datetime.fromisoformat(s)
                if client_ts.tzinfo is not None:
                    client_ts = client_ts.astimezone(tz=None).replace(tzinfo=None)
            else:
                client_ts = datetime.utcnow()
        except (ValueError, TypeError):
            client_ts = datetime.utcnow()

        # 過去 / 未来の極端値は弾く (clock skew 対策)
        now = datetime.utcnow()
        if client_ts < now - timedelta(days=7) or client_ts > now + timedelta(days=1):
            client_ts = now

        # 既に同 event_id が存在する場合は無視 (dedup)
        exists = db.query(ProductEvent.event_id).filter(ProductEvent.event_id == eid).first()
        if exists:
            continue

        ev = ProductEvent(
            event_id=eid,
            user_id_hash=uid_h,
            team_id_hash=tid_h,
            role=role,
            event_type=et,
            props=props_json,
            client_ts=client_ts,
            server_ts=now,
            app_version=app_version,
            platform=platform,
        )
        db.add(ev)
        inserted += 1

    if inserted > 0:
        db.commit()
    return inserted


def ensure_next_partition(db: Session) -> None:
    """PostgreSQL 限定: 翌々月のパーティションを idempotent に作成。

    Worker から日次で呼ぶ想定。SQLite 環境では no-op。
    """
    bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        return
    from sqlalchemy import text
    sql = text(
        """
        DO $$
        DECLARE
          nxt2 DATE := (date_trunc('month', now()) + interval '2 months')::date;
          nxt3 DATE := (date_trunc('month', now()) + interval '3 months')::date;
          pname TEXT := 'product_events_' || to_char(nxt2, 'YYYY_MM');
        BEGIN
          EXECUTE format(
            'CREATE TABLE IF NOT EXISTS %I PARTITION OF product_events FOR VALUES FROM (%L) TO (%L)',
            pname, nxt2, nxt3
          );
        END $$;
        """
    )
    db.execute(sql)
    db.commit()
