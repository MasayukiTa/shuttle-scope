"""Match ロスター解決: 役割 (player_key) → 登録 Player.uuid。

役割語彙 player_a / player_b / partner_a / partner_b は Stroke.player および
identity_graph の player_key と同一。Match の *_id 外部キーから Player.uuid を引く。
'other' / None / 未登録役割 (singles の partner 等) は None を返す。

設計意図 (backlog #2): identity_graph がアナリスト確定した player_key、または
PersonTracker が court_id から導いた役割を、**一意に決まる**登録選手 uuid へ解決する。
court_id → 役割 の対応自体 (PersonTracker 側) はヒューリスティックで曖昧さを含むが、
役割 → uuid の解決はロスターから一意で安全。
"""
from __future__ import annotations

from typing import Mapping, Optional

# Stroke.player / identity_graph player_key と同じ語彙
ROLE_KEYS = ("player_a", "player_b", "partner_a", "partner_b")


def match_role_to_player_id(match, role: str) -> Optional[int]:
    """Match オブジェクトの役割 → players.id (FK)。未該当は None。"""
    return {
        "player_a": getattr(match, "player_a_id", None),
        "player_b": getattr(match, "player_b_id", None),
        "partner_a": getattr(match, "partner_a_id", None),
        "partner_b": getattr(match, "partner_b_id", None),
    }.get(role)


def load_match_roster_uuids(db, match_id: int) -> dict[str, str]:
    """{役割: Player.uuid} を返す。欠落役割 (singles の partner 等) は含めない。

    db は SQLAlchemy Session 互換 (`.get(Model, pk)`)。失敗時は空 dict。
    """
    from backend.db.models import Match, Player  # 遅延 import (CI 軽量 venv 対策)

    out: dict[str, str] = {}
    try:
        m = db.get(Match, match_id)
    except Exception:
        m = None
    if m is None:
        return out
    for role in ROLE_KEYS:
        pid = match_role_to_player_id(m, role)
        if pid is None:
            continue
        try:
            p = db.get(Player, pid)
        except Exception:
            p = None
        uuid = getattr(p, "uuid", None) if p is not None else None
        if uuid:
            out[role] = uuid
    return out


def load_match_roster_uuids_standalone(match_id: int) -> dict[str, str]:
    """独自セッションで {役割: Player.uuid} を取得 (CV レイヤから DB を引く用)。

    court_calibration.load_calibration_standalone と同じく自前セッションを開く。
    DB 不在/失敗時は空 dict (= 全 uuid None にフォールバック)。
    """
    try:
        from backend.db.database import SessionLocal
        with SessionLocal() as db:
            return load_match_roster_uuids(db, match_id)
    except Exception:
        return {}


def resolve_player_uuid(roster: Mapping[str, str], player_key: Optional[str]) -> Optional[str]:
    """役割 (player_key) → Player.uuid。'other' / None / 未登録は None。"""
    if not player_key:
        return None
    return roster.get(player_key)
