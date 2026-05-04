"""
state_spec.py — 共有ゲーム状態表現 (Research Spine RS-1)

目的:
  - research モジュール間で状態定義がバラバラになることを防ぐ
  - EPV / Q値 / 反事実 / ハザードが同一の状態エンコードを使えるようにする

状態次元:
  1. score_phase   : early / mid / deuce / endgame
  2. set_phase     : first / second / third
  3. rally_bucket  : short / medium / long
  4. shot_bucket   : early / mid / late (ラリー内打球番号)
  5. player_role   : server / receiver

設計原則:
  - 純粋関数のみ（DB アクセスなし）
  - 既存の epv_engine / counterfactual_engine との互換を維持
  - state_key は文字列またはタプルで表現（ハッシュ可能）
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

ScorePhase = Literal["early", "mid", "deuce", "endgame"]
SetPhase = Literal["first", "second", "third"]
RallyBucket = Literal["short", "medium", "long"]
ShotBucket = Literal["early", "mid", "late"]
PlayerRole = Literal["server", "receiver"]


# ── 状態分類関数 ─────────────────────────────────────────────────────────────

def classify_score_phase(my_score: int, opp_score: int) -> ScorePhase:
    """
    スコアからゲームフェーズを返す。

    early:   両者10点未満
    mid:     どちらかが10点以上かつ終盤でない
    deuce:   18-18以上（デュース圏）
    endgame: どちらかが18点以上（終盤局面）
    """
    max_score = max(my_score, opp_score)
    if my_score >= 18 and opp_score >= 18:
        return "deuce"
    if max_score >= 18:
        return "endgame"
    if max_score >= 10:
        return "mid"
    return "early"


def classify_set_phase(set_num: int) -> SetPhase:
    """セット番号からセットフェーズを返す。"""
    if set_num <= 1:
        return "first"
    if set_num == 2:
        return "second"
    return "third"


def classify_rally_bucket(rally_length: int) -> RallyBucket:
    """
    ラリー長からバケットを返す。

    short:  1〜4打
    medium: 5〜9打
    long:   10打以上
    """
    if rally_length <= 4:
        return "short"
    if rally_length <= 9:
        return "medium"
    return "long"


def classify_shot_bucket(stroke_num: int) -> ShotBucket:
    """ラリー内打球番号からバケットを返す（epv_engine.classify_rally_phase と対応）。"""
    if stroke_num <= 3:
        return "early"
    if stroke_num <= 7:
        return "mid"
    return "late"


def classify_player_role(server: str, player_role: str) -> PlayerRole:
    """サーバー情報とプレイヤーロールからサーブ/レシーブを返す。"""
    return "server" if server == player_role else "receiver"


# ── State データクラス ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class GameState:
    score_phase: ScorePhase
    set_phase: SetPhase
    rally_bucket: RallyBucket
    shot_bucket: ShotBucket
    player_role: PlayerRole

    def to_key(self) -> str:
        """ハッシュ可能な文字列キーを返す。"""
        return f"{self.score_phase}|{self.set_phase}|{self.rally_bucket}|{self.shot_bucket}|{self.player_role}"

    def to_tuple(self) -> tuple:
        """タプルキーを返す。"""
        return (self.score_phase, self.set_phase, self.rally_bucket, self.shot_bucket, self.player_role)

    def to_dict(self) -> dict:
        return {
            "score_phase": self.score_phase,
            "set_phase": self.set_phase,
            "rally_bucket": self.rally_bucket,
            "shot_bucket": self.shot_bucket,
            "player_role": self.player_role,
        }


def build_game_state(
    my_score: int,
    opp_score: int,
    set_num: int,
    rally_length: int,
    stroke_num: int,
    server: str,
    player_role: str,
) -> GameState:
    """全引数から GameState を構築する。"""
    return GameState(
        score_phase=classify_score_phase(my_score, opp_score),
        set_phase=classify_set_phase(set_num),
        rally_bucket=classify_rally_bucket(rally_length),
        shot_bucket=classify_shot_bucket(stroke_num),
        player_role=classify_player_role(server, player_role),
    )


# ── Compact 状態（shot_bucket なし、ラリー全体単位） ──────────────────────────

@dataclass(frozen=True)
class RallyState:
    """ショット単位ではなくラリー全体単位の状態（EPV計算等で使用）。"""
    score_phase: ScorePhase
    set_phase: SetPhase
    rally_bucket: RallyBucket
    player_role: PlayerRole

    def to_key(self) -> str:
        return f"{self.score_phase}|{self.set_phase}|{self.rally_bucket}|{self.player_role}"

    def to_dict(self) -> dict:
        return {
            "score_phase": self.score_phase,
            "set_phase": self.set_phase,
            "rally_bucket": self.rally_bucket,
            "player_role": self.player_role,
        }


def build_rally_state(
    my_score: int,
    opp_score: int,
    set_num: int,
    rally_length: int,
    server: str,
    player_role: str,
) -> RallyState:
    """ラリー全体単位の状態を構築する。"""
    return RallyState(
        score_phase=classify_score_phase(my_score, opp_score),
        set_phase=classify_set_phase(set_num),
        rally_bucket=classify_rally_bucket(rally_length),
        player_role=classify_player_role(server, player_role),
    )


# ── 全状態列挙（CI計算・テーブル生成で使用） ────────────────────────────────

ALL_SCORE_PHASES: list[ScorePhase] = ["early", "mid", "deuce", "endgame"]
ALL_SET_PHASES: list[SetPhase] = ["first", "second", "third"]
ALL_RALLY_BUCKETS: list[RallyBucket] = ["short", "medium", "long"]
ALL_SHOT_BUCKETS: list[ShotBucket] = ["early", "mid", "late"]
ALL_PLAYER_ROLES: list[PlayerRole] = ["server", "receiver"]
