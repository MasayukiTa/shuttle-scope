"""分析の「視点 (role)」まわりの、依存のない小さな道具。

分析コードの `role` は、チーム側 ('player_a' | 'player_b') を表す文字列で、
`rally.winner == role` のように使う。一方 Stroke.player は個人の枠
(player_a / partner_a / player_b / partner_b) なので、打球を選ぶ時は
チーム側ではなく個人の枠と比べなければならない。シングルスと player_a / player_b の
選手では両者が同じ値になるが、ダブルスの相方 (partner_a / partner_b) だけは違う。

DB のモデルを読み込まないので、純粋な計算モジュールからも使える。
"""
from __future__ import annotations

from typing import Optional


class TeamSide(str):
    """分析の「視点 (role)」。値はチーム側 ('player_a' | 'player_b') の文字列で、
    `rally.winner == role` や `rally.server == role` にそのまま使える。
    加えて、その選手個人の枠 (player_a / partner_a / player_b / partner_b) を `.slot` に持つ。

    Stroke.player は個人の枠なので、打球を選ぶ時は `own_slot(role)` と比べる。
    player_a / player_b の選手では slot == 値なので、従来の比較と同じになる。
    ダブルスの相方 (partner_a / partner_b) だけが、チーム側と個人の枠で値が違う。
    """

    slot: str

    def __new__(cls, side: str, slot: str) -> "TeamSide":
        obj = super().__new__(cls, side)
        obj.slot = slot
        return obj


def own_slot(role: Optional[str]) -> Optional[str]:
    """視点 (role) から、その選手個人の枠を返す。TeamSide でない素の文字列は、そのまま枠とみなす。"""
    if role is None:
        return None
    return getattr(role, "slot", role)


_TEAMMATE_SLOT = {
    "player_a": "partner_a", "partner_a": "player_a",
    "player_b": "partner_b", "partner_b": "player_b",
}


def teammate_slot(role: Optional[str]) -> Optional[str]:
    """視点 (role) の選手と同じチームの、もう一人の個人の枠。"""
    return _TEAMMATE_SLOT.get(own_slot(role) or "")


def perspective(match, player_id: int) -> Optional[TeamSide]:
    """試合での player_id の視点。選手 (player_a/player_b) もダブルスの相方 (partner_a/partner_b) も
    解決する。試合に出ていなければ None。"""
    if match.player_a_id == player_id:
        return TeamSide("player_a", "player_a")
    if match.player_b_id == player_id:
        return TeamSide("player_b", "player_b")
    if getattr(match, "partner_a_id", None) == player_id:
        return TeamSide("player_a", "partner_a")
    if getattr(match, "partner_b_id", None) == player_id:
        return TeamSide("player_b", "partner_b")
    return None


# Stroke.player は個人の枠 (player_a / partner_a / player_b / partner_b)。
# ダブルスではチームが 2 人なので、「相手の打球」を `stroke.player != role` で
# 判定すると、自分の相方 (partner_a / partner_b) の打球まで相手扱いになる。
_STROKE_SLOT_SIDE = {
    "player_a": "player_a",
    "partner_a": "player_a",
    "player_b": "player_b",
    "partner_b": "player_b",
}


def team_side(match, player_id: int, default: str = "player_b") -> str:
    """player_id のチーム側 ('player_a' | 'player_b')。ダブルスの相方も同じチームの側を返す。
    試合に出ていない時は default (従来の `"player_a" if match.player_a_id == pid else "player_b"` と同じ)。"""
    view = perspective(match, player_id)
    return str(view) if view is not None else default


def match_ids_by_slot(matches, player_id: int) -> dict:
    """試合を、player_id の個人の枠 (player_a / partner_a / player_b / partner_b) ごとに分ける。
    枠ごとに Stroke.player の絞り込みが変わる集計で使う。出ていない試合は入れない。"""
    out: dict = {}
    for m in matches:
        view = perspective(m, player_id)
        if view is not None:
            out.setdefault(view.slot, []).append(m.id)
    return out


def stroke_side(stroke_player: Optional[str]) -> Optional[str]:
    """打球の個人の枠 → チーム側 ('player_a' | 'player_b')。未知の値は None。"""
    return _STROKE_SLOT_SIDE.get(stroke_player or "")


def is_opponent_stroke(stroke_player: Optional[str], team_side: Optional[str]) -> bool:
    """その打球が、team_side のチームから見て相手側のものか。
    team_side はチーム側 ('player_a' | 'player_b')。相方の打球は相手ではない。
    枠が未知の打球は、相手とも味方とも言えないので False。"""
    if team_side not in ("player_a", "player_b"):
        return False
    side = _STROKE_SLOT_SIDE.get(stroke_player or "")
    return side is not None and side != team_side
