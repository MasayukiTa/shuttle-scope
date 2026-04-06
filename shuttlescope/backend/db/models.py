"""SQLAlchemy ORMモデル定義"""
from datetime import datetime, date
from typing import Optional
from sqlalchemy import (
    Integer, String, Float, Boolean, DateTime, Date,
    ForeignKey, Text, UniqueConstraint
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.db.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="analyst")  # analyst/coach/player
    player_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("players.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)           # 選手名（日本語対応）
    name_en: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)  # 英語名（BWF検索用）
    team: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    nationality: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    dominant_hand: Mapped[Optional[str]] = mapped_column(String(10), nullable=True, default=None)  # R / L / unknown / null
    birth_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    world_ranking: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 記録時点
    is_target: Mapped[bool] = mapped_column(Boolean, default=False)           # 解析対象フラグ
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # V4: プロフィール確定度・暫定作成管理
    profile_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, default="verified")  # provisional/partial/verified
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    created_via_quick_start: Mapped[bool] = mapped_column(Boolean, default=False)
    # V4: 所属・表記揺れ・別名
    organization: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    aliases: Mapped[Optional[str]] = mapped_column(Text, nullable=True)       # JSON文字列 ["alias1","alias2"]
    name_normalized: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)  # 正規化名（検索用）
    scouting_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # リレーション
    matches_as_a: Mapped[list["Match"]] = relationship(
        "Match", foreign_keys="Match.player_a_id", back_populates="player_a"
    )
    matches_as_b: Mapped[list["Match"]] = relationship(
        "Match", foreign_keys="Match.player_b_id", back_populates="player_b"
    )


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tournament: Mapped[str] = mapped_column(String(200), nullable=False)
    tournament_level: Mapped[str] = mapped_column(String(20), nullable=False)  # IC/IS/SJL/全日本/国内/その他
    tournament_grade: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # Super1000/500...
    round: Mapped[str] = mapped_column(String(50), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    venue: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    format: Mapped[str] = mapped_column(String(30), nullable=False)  # singles/womens_doubles/mixed_doubles
    player_a_id: Mapped[int] = mapped_column(Integer, ForeignKey("players.id"), nullable=False)
    player_b_id: Mapped[int] = mapped_column(Integer, ForeignKey("players.id"), nullable=False)
    partner_a_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("players.id"), nullable=True)
    partner_b_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("players.id"), nullable=True)
    result: Mapped[str] = mapped_column(String(20), nullable=False)  # win/loss/walkover/unfinished
    final_score: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)  # "21-15, 18-21, 21-19"
    video_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    video_local_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    video_quality: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # 720p/1080p/4k/other
    camera_angle: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    annotator_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    annotation_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending/in_progress/complete/reviewed
    annotation_progress: Mapped[float] = mapped_column(Float, default=0.0)  # 0.0-1.0
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    # V4: クイックスタート・試合メタデータ
    initial_server: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)     # player_a / player_b
    competition_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True, default="unknown")  # official/practice_match/open_practice/unknown
    created_via_quick_start: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, default="minimal")  # minimal/partial/verified
    # 途中終了: retired_a（自棄権）/ retired_b（相手棄権）/ abandoned（外的中断）
    exception_reason: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)

    # リレーション
    player_a: Mapped["Player"] = relationship("Player", foreign_keys=[player_a_id], back_populates="matches_as_a")
    player_b: Mapped["Player"] = relationship("Player", foreign_keys=[player_b_id], back_populates="matches_as_b")
    sets: Mapped[list["GameSet"]] = relationship("GameSet", back_populates="match", cascade="all, delete-orphan")


class GameSet(Base):
    __tablename__ = "sets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[int] = mapped_column(Integer, ForeignKey("matches.id"), nullable=False)
    set_num: Mapped[int] = mapped_column(Integer, nullable=False)  # 1/2/3
    winner: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # player_a/player_b
    score_a: Mapped[int] = mapped_column(Integer, default=0)
    score_b: Mapped[int] = mapped_column(Integer, default=0)
    duration_min: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_deuce: Mapped[bool] = mapped_column(Boolean, default=False)

    # リレーション
    match: Mapped["Match"] = relationship("Match", back_populates="sets")
    rallies: Mapped[list["Rally"]] = relationship("Rally", back_populates="game_set", cascade="all, delete-orphan")


class Rally(Base):
    __tablename__ = "rallies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    set_id: Mapped[int] = mapped_column(Integer, ForeignKey("sets.id"), nullable=False)
    rally_num: Mapped[int] = mapped_column(Integer, nullable=False)  # セット内ラリー番号（1始まり）
    server: Mapped[str] = mapped_column(String(20), nullable=False)  # player_a/player_b
    winner: Mapped[str] = mapped_column(String(20), nullable=False)  # player_a/player_b
    end_type: Mapped[str] = mapped_column(String(30), nullable=False)  # ace/forced_error/...
    rally_length: Mapped[int] = mapped_column(Integer, nullable=False)  # 総ストローク数
    duration_sec: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    score_a_after: Mapped[int] = mapped_column(Integer, default=0)  # 得点後のスコア
    score_b_after: Mapped[int] = mapped_column(Integer, default=0)
    is_deuce: Mapped[bool] = mapped_column(Boolean, default=False)
    video_timestamp_start: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    video_timestamp_end: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # 見逃しラリー（ストロークなしで得点だけ記録）
    is_skipped: Mapped[bool] = mapped_column(Boolean, default=False)

    # リレーション
    game_set: Mapped["GameSet"] = relationship("GameSet", back_populates="rallies")
    strokes: Mapped[list["Stroke"]] = relationship("Stroke", back_populates="rally", cascade="all, delete-orphan", order_by="Stroke.stroke_num")


class Stroke(Base):
    __tablename__ = "strokes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rally_id: Mapped[int] = mapped_column(Integer, ForeignKey("rallies.id"), nullable=False)
    stroke_num: Mapped[int] = mapped_column(Integer, nullable=False)  # ラリー内順番（1始まり）
    player: Mapped[str] = mapped_column(String(20), nullable=False)   # player_a/player_b/partner_a/partner_b

    # ショット情報
    shot_type: Mapped[str] = mapped_column(String(30), nullable=False)  # 18分類
    shot_quality: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # excellent/good/neutral/poor

    # 正規化座標（0.0-1.0）
    hit_x: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    hit_y: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    land_x: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    land_y: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    player_x: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    player_y: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    opponent_x: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    opponent_y: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # N-002: 空間座標拡張（相手打点・自分打点・返球目標）
    opponent_contact_x: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    opponent_contact_y: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    player_contact_x:   Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    player_contact_y:   Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    return_target_x:    Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    return_target_y:    Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # ゾーン（集計・フィルタ用）
    hit_zone: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)   # BL/BC/BR/ML/MC/MR/NL/NC/NR
    land_zone: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)  # 同上

    # 打球属性
    is_backhand: Mapped[bool] = mapped_column(Boolean, default=False)
    is_around_head: Mapped[bool] = mapped_column(Boolean, default=False)
    above_net: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)  # True=ネット上 False=ネット下
    is_cross: Mapped[bool] = mapped_column(Boolean, default=False)

    # タイミング
    timestamp_sec: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # 算出値（解析後にバッチ更新）
    epv: Mapped[Optional[float]] = mapped_column(Float, nullable=True)           # Expected Pattern Value
    shot_influence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # ショット影響度スコア

    # リレーション
    rally: Mapped["Rally"] = relationship("Rally", back_populates="strokes")


class AnalysisCache(Base):
    __tablename__ = "analysis_cache"
    __table_args__ = (UniqueConstraint("cache_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cache_key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    player_id: Mapped[int] = mapped_column(Integer, nullable=False)
    analysis_type: Mapped[str] = mapped_column(String(50), nullable=False)
    filters_json: Mapped[str] = mapped_column(Text, nullable=False)   # フィルタ条件JSON
    result_json: Mapped[str] = mapped_column(Text, nullable=False)    # 解析結果JSON
    sample_size: Mapped[int] = mapped_column(Integer, default=0)
    confidence_level: Mapped[float] = mapped_column(Float, default=0.0)  # 0.0-1.0
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
