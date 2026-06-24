"""SQLAlchemy ORMモデル定義"""
from datetime import datetime, date
from typing import Optional
from uuid import uuid4
from sqlalchemy import (
    Integer, String, Float, Boolean, DateTime, Date,
    ForeignKey, Text, UniqueConstraint, Index, LargeBinary, func, JSON
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.db.database import Base
# Phase A1: 機密フィールドの透過暗号化型
from backend.utils.field_crypto import EncryptedText as _EncryptedText  # noqa: F401


def _new_uuid() -> str:
    return str(uuid4())


class Team(Base):
    """チーム（試合所有・データ境界）。

    display_id は表示用の任意識別子（admin/coach が任意文字列を設定）、
    UI では name を表示するが、内部参照は id（int）/ uuid を使う。
    is_independent=True のチームは個人ユーザの「無所属」用。
    """
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(String(36), nullable=False, unique=True, index=True, default=_new_uuid)
    display_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    short_name: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    is_independent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="false")
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="analyst")  # analyst/coach/player/demo
    player_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("players.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    hashed_credential: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # 旧: 表示名ベース。Phase B-1 以降は team_id を正とする（移行期間中のみ併存）
    team_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    team_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("teams.id"), nullable=True, index=True
    )
    # セキュリティ強化カラム
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default="0")
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    totp_secret: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="0")
    # M-A2: メールアドレス（任意、ユニーク）。register / password reset / invite で使用。
    # 既存 username ログインとの併用 (username または email でログイン可能)。
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, unique=True, index=True)
    email_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # M-A 公開 register 経由の自己作成ユーザは admin 承認まで全 API 403。
    # admin が「保留中ユーザー一覧」から承認 → role/team_id を割り当て + フラグを False に。
    awaiting_admin_approval: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="0"
    )
    # 0045: 検証用に作成したユーザを実ユーザと区別するフラグ。
    # False = 実ユーザ (= 保護対象)。公開 register 経由の新規は default False = 保護。
    # True = 検証用 (削除可)。承認済みの実ユーザ (is_test=False かつ
    # awaiting_admin_approval=False) は DB トリガで誤削除を防止する
    # (override 時のみ削除可。migration 0045 参照)。
    is_test: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="0"
    )
    # GDPR Article 7 / APPI 第18条 準拠の同意取得 flag。
    # True なら未同意 = 必須同意 endpoint (`/api/auth/consents`) を経由しないと
    # 保護対象 API を呼べない。新規ユーザは default True、初回ログインで同意画面誘導。
    # 0024 migration 時に既存ユーザは False に設定済 (運用断絶を避けるため)。
    consent_required: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default="1"
    )
    # 0031: AI 学習データ抽出の default 除外判定 + 同意 UI 分岐の根拠。
    # NULL = 未提供 (大人として扱われる、ただし captured_minor_flag は別途 NULL)。
    date_of_birth: Mapped[Optional[date]] = mapped_column(Date, nullable=True)


class UserConsent(Base):
    """GDPR Article 7(1) (demonstrate consent) / APPI 第18条 準拠の同意取得記録。

    consent_type ごとに 1 行 1 件、時系列で give/withdraw を追跡する。
    privacy_policy_version / terms_version は文書改定時にユーザ再同意を判定する根拠。
    ip_address / user_agent_hash は GDPR Article 32 (security of processing) に基づく
    evidentiary 補強 (raw UA は記録せず SHA256 hash のみ保存し PII 縮減)。
    """
    __tablename__ = "user_consents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # 'service_delivery' | 'ai_training' | 'research_participation'
    # | 'cross_border_transfer' | 'beta_agreement'
    consent_type: Mapped[str] = mapped_column(String(50), nullable=False)
    consent_given: Mapped[bool] = mapped_column(Boolean, nullable=False)
    privacy_policy_version: Mapped[str] = mapped_column(String(20), nullable=False)
    terms_version: Mapped[str] = mapped_column(String(20), nullable=False)
    given_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    withdrawn_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    user_agent_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)


class ContentReport(Base):
    """CONTENT_POLICY.md / NOTICE_AND_TAKEDOWN_PROCEDURE.md に基づく違反通報。

    DMCA 17 USC § 512 / EU eCommerce Directive 14 / DSA / 著作権法第30条 等の
    safe harbor を構成する notice-and-takedown 経路の永続化。匿名通報も
    受け付け、SLA に従った triage / action を残す。
    """
    __tablename__ = "content_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subject_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    subject_match_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    complainant_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    complainant_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    statement_text: Mapped[str] = mapped_column(Text, nullable=False)
    legal_basis: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    source_ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # triage
    triage_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    triaged_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    triaged_by_user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    triage_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # action
    action_taken: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    action_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # counter-notice
    counter_notice_received_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    counter_notice_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    restored_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class TrainingDatasetRecord(Base):
    """LEARNING_DATA_PROVENANCE.md に基づく学習データ provenance。

    license_type で著作権法第30条の4 / 第47条の5、明示許諾、β-legacy 想定等を
    区別する。raw URL は保存せず source_url_hash (SHA256) で参照する。
    """
    __tablename__ = "training_dataset_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(String(100), nullable=False)
    source_url_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    acquisition_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    license_type: Mapped[str] = mapped_column(String(50), nullable=False)
    licensor_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    licensor_contact: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    scope_description: Mapped[str] = mapped_column(String(500), nullable=False)
    verification_artefacts: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True
    )
    beta_legacy_flag: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    recorded_by_user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class RevokedToken(Base):
    """ログアウト済みJWTのブラックリスト。expires_at 以降は自動的に参照不要になる。"""
    __tablename__ = "revoked_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    jti: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class RefreshToken(Base):
    """Refresh token の永続化テーブル。平文ではなく SHA256 ハッシュを保存する。

    rotation 方式: 使用するたびに新発行 + 使用済み側を revoke。
    reuse detection: revoked_at 有り行を再提示された場合、同 user の全 chain を revoke する。
    """
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    jti: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    replaced_by_jti: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)


class PlayerPageAccess(Base):
    """選手ユーザーへのページアクセス付与。
    user_id が設定されていれば個人付与、team_name のみなら同チーム全選手への付与。
    page_key: "prediction" | "expert_labeler"
    """
    __tablename__ = "player_page_access"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    page_key: Mapped[str] = mapped_column(String(50), nullable=False)
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    team_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    granted_by_user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 同期メタデータ
    uuid: Mapped[str] = mapped_column(String(36), nullable=False, unique=True, index=True, default=_new_uuid)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    source_device_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)           # 選手名（日本語対応）
    name_en: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)  # 英語名（BWF検索用）
    # Phase B-15+: team 文字列カラムは削除済み (migration 0014)。
    # 後方互換のため @property として team_id 経由で teams.name を返す shim を提供。
    # Phase B-4: 所属チーム（正規化）。team_id を SoT とする。
    team_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("teams.id"), nullable=True, index=True
    )

    @property
    def team(self) -> Optional[str]:
        """後方互換: team 文字列を team_id から動的に解決する。
        N+1 を避けたい場合は呼び出し側で eager load (joinedload) すること。
        """
        from backend.db.models import Team  # 自己参照回避
        if self.team_id is None:
            return None
        try:
            from sqlalchemy.orm import object_session
            sess = object_session(self)
            if sess is None:
                return None
            t = sess.get(Team, self.team_id)
            return t.name if t and t.deleted_at is None else None
        except Exception:
            return None
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
    # 所属履歴: JSON文字列 [{"team":"ACT SAIKYO","until":"2025-03","note":""}]
    team_history: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # リレーション
    matches_as_a: Mapped[list["Match"]] = relationship(
        "Match", foreign_keys="Match.player_a_id", back_populates="player_a"
    )
    matches_as_b: Mapped[list["Match"]] = relationship(
        "Match", foreign_keys="Match.player_b_id", back_populates="player_b"
    )
    conditions: Mapped[list["Condition"]] = relationship(
        "Condition", back_populates="player", cascade="all, delete-orphan"
    )
    condition_tags: Mapped[list["ConditionTag"]] = relationship(
        "ConditionTag", back_populates="player", cascade="all, delete-orphan"
    )


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (
        Index("ix_matches_player_a_id",      "player_a_id"),
        Index("ix_matches_player_b_id",      "player_b_id"),
        Index("ix_matches_date",             "date"),
        Index("ix_matches_tournament_level", "tournament_level"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 同期メタデータ
    uuid: Mapped[str] = mapped_column(String(36), nullable=False, unique=True, index=True, default=_new_uuid)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    source_device_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
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
    # video_local_path: 内部利用のみ。フロント / API レスポンスには露出させないこと。
    # ユーザーへ動画を提供するには video_token を使い /api/videos/{video_token}/stream 経由で配信する。
    video_local_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    # video_token: 不透明トークン。ストリーミング API のキー。生パスを露出せず動画にアクセスする手段。
    video_token: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, unique=True, index=True)
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
    # 0031: 撮影時点で参加選手のいずれかが未成年だったかを示すフラグ。
    # True = 未成年期撮影、False = 全員大人、NULL = 判定不能 (dob 未提供等)。
    # AI 学習データ抽出は default で True を除外する。
    captured_minor_flag: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    # ── Phase B-3: チーム境界 ────────────────────────────────────────────────
    # owner_team_id: 試合を登録したチーム（データ所有・閲覧主体）
    # is_public_pool: True で全チーム参照可能（admin による BWF 等の登録）
    # home_team_id / away_team_id: 試合参加チーム（owner とは独立）
    # Phase B-3: チーム所有。production の admin オペで全試合に owner 割当が
    # 完了した後、migration 0013 を opt-in で適用すれば NOT NULL になる。
    # それまではアプリ層（resolve_owner_team_for_match_create）で必須化を担保する。
    owner_team_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("teams.id"), nullable=True, index=True
    )
    is_public_pool: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false", index=True
    )
    home_team_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("teams.id"), nullable=True)
    away_team_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("teams.id"), nullable=True)

    # リレーション
    player_a: Mapped["Player"] = relationship("Player", foreign_keys=[player_a_id], back_populates="matches_as_a")
    player_b: Mapped["Player"] = relationship("Player", foreign_keys=[player_b_id], back_populates="matches_as_b")
    sets: Mapped[list["GameSet"]] = relationship("GameSet", back_populates="match", cascade="all, delete-orphan")
    cv_artifacts: Mapped[list["MatchCVArtifact"]] = relationship(
        "MatchCVArtifact", back_populates="match", cascade="all, delete-orphan"
    )


class GameSet(Base):
    __tablename__ = "sets"
    __table_args__ = (
        Index("ix_sets_match_id_set_num", "match_id", "set_num"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 同期メタデータ
    uuid: Mapped[str] = mapped_column(String(36), nullable=False, unique=True, index=True, default=_new_uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    source_device_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
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
    __table_args__ = (
        Index("ix_rallies_set_id_rally_num", "set_id", "rally_num"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 同期メタデータ
    uuid: Mapped[str] = mapped_column(String(36), nullable=False, unique=True, index=True, default=_new_uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    source_device_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    set_id: Mapped[int] = mapped_column(Integer, ForeignKey("sets.id"), nullable=False)
    rally_num: Mapped[int] = mapped_column(Integer, nullable=False)  # セット内ラリー番号（1始まり）
    server: Mapped[str] = mapped_column(String(20), nullable=False)  # player_a/player_b
    winner: Mapped[str] = mapped_column(String(20), nullable=False)  # player_a/player_b
    end_type: Mapped[str] = mapped_column(String(30), nullable=False)  # ace/forced_error/...
    rally_length: Mapped[int] = mapped_column(Integer, nullable=False)  # 総ストローク数
    duration_sec: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    score_a_before: Mapped[int] = mapped_column(Integer, default=0)  # ラリー開始直前のスコア
    score_b_before: Mapped[int] = mapped_column(Integer, default=0)
    score_a_after: Mapped[int] = mapped_column(Integer, default=0)  # 得点後のスコア
    score_b_after: Mapped[int] = mapped_column(Integer, default=0)
    is_deuce: Mapped[bool] = mapped_column(Boolean, default=False)
    video_timestamp_start: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    video_timestamp_end: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # 見逃しラリー（ストロークなしで得点だけ記録）
    is_skipped: Mapped[bool] = mapped_column(Boolean, default=False)
    # アノテーション記録方式 (manual_record / assisted_record)
    annotation_mode: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    # レビューステータス (pending / completed)
    review_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # リレーション
    game_set: Mapped["GameSet"] = relationship("GameSet", back_populates="rallies")
    strokes: Mapped[list["Stroke"]] = relationship("Stroke", back_populates="rally", cascade="all, delete-orphan", order_by="Stroke.stroke_num")


class Stroke(Base):
    __tablename__ = "strokes"
    __table_args__ = (
        Index("ix_strokes_rally_id_stroke_num", "rally_id", "stroke_num"),
        Index("ix_strokes_player",              "player"),
        Index("ix_strokes_shot_type",           "shot_type"),
        Index("ix_strokes_hit_zone",            "hit_zone"),
        Index("ix_strokes_land_zone",           "land_zone"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 同期メタデータ
    uuid: Mapped[str] = mapped_column(String(36), nullable=False, unique=True, index=True, default=_new_uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    source_device_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
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
    # Phase A: 打点ソース ('cv' = CV 自動値そのまま / 'manual' = 人間 override)
    hit_zone_source: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    # Phase A: CV 元推定値 (override 後も保持してデータ品質計測)
    hit_zone_cv_original: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    land_zone: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)  # 同上

    # 打球属性
    is_backhand: Mapped[bool] = mapped_column(Boolean, default=False)
    is_around_head: Mapped[bool] = mapped_column(Boolean, default=False)
    above_net: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)  # True=ネット上 False=ネット下
    is_cross: Mapped[bool] = mapped_column(Boolean, default=False)

    # タイミング
    timestamp_sec: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # G2: 返球品質・打点高さ（ストローク確定後オプション入力）
    return_quality: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)   # attack/neutral/defensive/emergency
    contact_height: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)   # overhead/side/underhand/scoop
    # 移動系コンテキスト（4.1 Movement Features）
    contact_zone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)      # front/mid/rear（打点コート位置）
    movement_burden: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)   # low/medium/high（移動負荷粗見積もり）
    movement_direction: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # forward/backward/lateral（移動方向）

    # 算出値（解析後にバッチ更新）
    epv: Mapped[Optional[float]] = mapped_column(Float, nullable=True)           # Expected Pattern Value
    shot_influence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # ショット影響度スコア

    # 入力ソース (manual / assisted / corrected)
    source_method: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

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


# ─── R-001: 共有セッション ───────────────────────────────────────────────────

class SharedSession(Base):
    """1試合に紐づく共有運用セッション（複数viewer/coach/analystが同時参加可能）"""
    __tablename__ = "shared_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[int] = mapped_column(Integer, ForeignKey("matches.id"), nullable=False)
    session_code: Mapped[str] = mapped_column(String(10), unique=True, nullable=False)  # 参加コード（6文字英数字）
    created_by_role: Mapped[str] = mapped_column(String(20), default="analyst")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_broadcast_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # LAN セッション認証（migration 0003）
    password_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    match: Mapped["Match"] = relationship("Match")
    participants: Mapped[list["SessionParticipant"]] = relationship(
        "SessionParticipant", back_populates="session", cascade="all, delete-orphan"
    )
    comments: Mapped[list["Comment"]] = relationship(
        "Comment", back_populates="session", cascade="all, delete-orphan"
    )


class SessionParticipant(Base):
    """セッション参加者（ロール別・デバイス別）"""
    __tablename__ = "session_participants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("shared_sessions.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # analyst/coach/viewer
    device_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    is_connected: Mapped[bool] = mapped_column(Boolean, default=False)
    # LAN デバイス制御（migration 0003）
    device_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)        # iphone/ipad/pc/usb_camera/builtin_camera
    connection_role: Mapped[str] = mapped_column(String(30), default="viewer")           # viewer/coach/analyst/camera_candidate/active_camera
    source_capability: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # camera/viewer/none
    video_receive_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    authenticated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    connection_state: Mapped[str] = mapped_column(String(20), default="idle")            # idle/receiving_video/sending_video
    # デバイスライフサイクル（migration 0004）
    device_uid: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)         # デバイス固有 ID（再接続認識）
    approval_status: Mapped[str] = mapped_column(String(20), default="pending")          # pending/approved/rejected
    last_heartbeat: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    viewer_permission: Mapped[str] = mapped_column(String(20), default="default")        # allowed/blocked/default
    device_class: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)       # phone/tablet/pc/camera
    display_size_class: Mapped[str] = mapped_column(String(20), default="standard")      # standard/large_tablet

    session: Mapped["SharedSession"] = relationship("SharedSession", back_populates="participants")
    live_sources: Mapped[list["LiveSource"]] = relationship(
        "LiveSource", back_populates="participant", cascade="all, delete-orphan"
    )


class LiveSource(Base):
    """セッション内カメラソース（種別・優先度・解像度・稼働状態を管理）"""
    __tablename__ = "live_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("shared_sessions.id"), nullable=False)
    participant_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("session_participants.id"), nullable=True)
    source_kind: Mapped[str] = mapped_column(String(20), nullable=False)    # iphone_webrtc/usb_camera/builtin_camera/pc_local
    source_priority: Mapped[int] = mapped_column(Integer, default=4)         # 1=最優先
    source_resolution: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # "1280x720"
    source_fps: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source_status: Mapped[str] = mapped_column(String(20), default="inactive")  # inactive/candidate/active
    suitability: Mapped[str] = mapped_column(String(20), default="usable")       # high/usable/fallback
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    participant: Mapped[Optional["SessionParticipant"]] = relationship(
        "SessionParticipant", back_populates="live_sources"
    )


class Recording(Base):
    """試合(match)に紐づく動画。

    設計意図: 試合枠を先に作成 → match_id が確定 → その match の **枝番(branch_no)** に
    複数の動画(upload / live)が結びつく。1 match → N recordings。
    live は録画ファイルが GPU 機(Z8) の HDD に落ちる想定。
    動画パスは生で露出せず video_token 経由で配信する (Match と同方針)。
    """
    __tablename__ = "recordings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("matches.id"), nullable=False, index=True
    )
    # 枝番: match 内の連番 (1 始まり)。(match_id, branch_no) で一意。
    branch_no: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="upload")  # upload/live
    # iphone_webrtc/usb_camera/builtin_camera/pc_local/rtmp (live 時)
    source_kind: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")  # pending/recording/ready/failed
    # 内部パスは露出させない。配信は video_token 経由。
    video_local_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    video_token: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, unique=True, index=True)
    resolution: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # "1280x720"
    fps: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    label: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        UniqueConstraint("match_id", "branch_no", name="uq_recording_match_branch"),
    )


class MaintenanceWindow(Base):
    """予定メンテナンス告知 (トップページ/ステータスページに掲示)。"""
    __tablename__ = "maintenance_windows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scheduled_start: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    scheduled_end: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # scheduled / in_progress / completed / canceled
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="scheduled")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class StatusIncident(Base):
    """障害インシデント記録 (いつ落ち/復旧したか + 理由)。

    「死活時刻」は began_at/resolved_at、「理由」は reason に運用者が記す。
    """
    __tablename__ = "status_incidents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # minor / major / critical
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="minor")
    component: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # tunnel/backend/gpu 等
    # investigating / identified / monitoring / resolved
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="investigating")
    began_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # manual = 運用者が記録 / auto = status_monitor が自動記録
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual", server_default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class HealthSample(Base):
    """コンポーネント別ヘルスサンプル。status_monitor が定期的に記録し、
    稼働状況ページの「現在状態・負荷メトリクス・稼働率(uptime)」の集計元になる。

    component: api/database/tunnel/gpu/worker。status: operational/degraded/down。
    metric: 主要負荷指標 (例: GPU util%, CPU%, DB 応答ms)。detail: 表示用短文。
    """
    __tablename__ = "health_samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    component: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    metric: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # 連続グラデーション用の深刻度 [0,1] (0=正常→緑, 1=最悪→赤)。生メトリクスから
    # チェック時に算出して記録する。None の旧行は status から離散フォールバックする。
    severity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    detail: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    sampled_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, index=True)


class Announcement(Base):
    """公開更新情報 / お知らせ (トップページ・ステータスページに掲示)。

    運用者がキュレーションした「公開して良い」更新のみを掲載する公開フィード。
    内部の dev CHANGELOG (security/attack/CV 詳細を含む) は公開しない方針のため、
    本テーブルに運用者が手動で公開可の項目だけを登録する。
    """
    __tablename__ = "announcements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 英語版 (任意)。/en/status で title_en/body_en があれば優先、無ければ JA に
    # フォールバックする。
    title_en: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    body_en: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # published / draft (draft は公開フィードに出さない)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="published")
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="0")
    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class LlmConversation(Base):
    """汎用 LLM チャット (/#/llm) の会話。バドミントン特化 insights chat とは別系統。
    所有者 (user_id) のみ閲覧可。provider/model は会話ごとに固定し再現性を持たせる。"""
    __tablename__ = "llm_conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="新しいチャット")
    provider: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    system_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    last_used_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class LlmTurn(Base):
    """LLM 会話の 1 ターン (メッセージ)。role = user|assistant|system|tool。"""
    __tablename__ = "llm_turns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(Integer, ForeignKey("llm_conversations.id"), nullable=False, index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tool_calls: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


# ─── S-003: コメント・タグ ────────────────────────────────────────────────────

class Comment(Base):
    """試合 / セット / ラリー / ストロークへのコメント（セッション内外問わず付与可能）"""
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 同期メタデータ
    uuid: Mapped[str] = mapped_column(String(36), nullable=False, unique=True, index=True, default=_new_uuid)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    source_device_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    session_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("shared_sessions.id"), nullable=True)
    match_id: Mapped[int] = mapped_column(Integer, ForeignKey("matches.id"), nullable=False)
    set_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("sets.id"), nullable=True)
    rally_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("rallies.id"), nullable=True)
    stroke_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("strokes.id"), nullable=True)
    author_role: Mapped[str] = mapped_column(String(20), nullable=False, default="analyst")
    # Round 258 R40-6: 自由記述 → DB ファイル / WAL / backup 漏洩経路で平文露出を防ぐ
    # ため EncryptedText で透過暗号化する。鍵 (`SS_FIELD_ENCRYPTION_KEY`) は backend
    # process の env にのみ存在し、DB host 単体侵害 / backup file 漏洩のシナリオで PII
    # が読めなくなる。既存平文 row は decrypt_field の "v1:" prefix check で互換維持。
    text: Mapped[str] = mapped_column(_EncryptedText, nullable=False)
    is_flagged: Mapped[bool] = mapped_column(Boolean, default=False)  # 重要フラグ
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # Phase B-7: 書き込みチーム
    team_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("teams.id"), nullable=True, index=True)

    session: Mapped[Optional["SharedSession"]] = relationship("SharedSession", back_populates="comments")


# ─── U-001: イベントブックマーク / クリップ要求 ────────────────────────────────

class EventBookmark(Base):
    """試合中・試合後のブックマーク（手動 / コーチ要求 / 統計自動）"""
    __tablename__ = "event_bookmarks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 同期メタデータ
    uuid: Mapped[str] = mapped_column(String(36), nullable=False, unique=True, index=True, default=_new_uuid)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    source_device_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    match_id: Mapped[int] = mapped_column(Integer, ForeignKey("matches.id"), nullable=False)
    rally_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("rallies.id"), nullable=True)
    stroke_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("strokes.id"), nullable=True)
    # manual / coach_request / auto_stat / clip_request
    bookmark_type: Mapped[str] = mapped_column(String(30), default="manual")
    video_timestamp_sec: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Round 258 R40-6: EncryptedText (Condition / Comment と同設計)
    note: Mapped[Optional[str]] = mapped_column(_EncryptedText, nullable=True)
    is_reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # Phase B-7: 書き込みチーム
    team_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("teams.id"), nullable=True, index=True)


# ─── G3: 試合前ウォームアップ観察 ────────────────────────────────────────────

class PreMatchObservation(Base):
    """Set 1 前の公開練習・ウォームアップ中に収集した選手観察データ。
    ラリーアノテーションとは独立して保存し、stroke-level モデルの汚染を防ぐ。
    """
    __tablename__ = "pre_match_observations"
    __table_args__ = (
        Index("ix_pmo_match_player_type", "match_id", "player_id", "observation_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 同期メタデータ
    uuid: Mapped[str] = mapped_column(String(36), nullable=False, unique=True, index=True, default=_new_uuid)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    source_device_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    match_id: Mapped[int] = mapped_column(Integer, ForeignKey("matches.id"), nullable=False)
    player_id: Mapped[int] = mapped_column(Integer, ForeignKey("players.id"), nullable=False)
    # observation_type: handedness / physical_caution / tactical_style / court_preference
    observation_type: Mapped[str] = mapped_column(String(50), nullable=False)
    observation_value: Mapped[str] = mapped_column(String(100), nullable=False)
    # confidence_level: unknown / tentative / likely / confirmed
    confidence_level: Mapped[str] = mapped_column(String(20), nullable=False, default="tentative")
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="warmup")
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_by: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # analyst role identifier
    # Phase B-7: 書き込みチーム
    team_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("teams.id"), nullable=True, index=True)


class HumanForecast(Base):
    """Phase S2: コーチ / アナリストによる試合前予測。
    モデル予測との比較ベンチマークに使用する。
    """
    __tablename__ = "human_forecasts"
    __table_args__ = (
        Index("ix_hf_match_player", "match_id", "player_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 同期メタデータ
    uuid: Mapped[str] = mapped_column(String(36), nullable=False, unique=True, index=True, default=_new_uuid)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    source_device_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # 対象試合と対象選手（誰について予測しているか）
    match_id: Mapped[int] = mapped_column(Integer, ForeignKey("matches.id"), nullable=False)
    player_id: Mapped[int] = mapped_column(Integer, ForeignKey("players.id"), nullable=False)
    # 予測者情報
    forecaster_role: Mapped[str] = mapped_column(String(20), nullable=False)  # 'coach' | 'analyst'
    forecaster_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # 予測内容
    predicted_outcome: Mapped[str] = mapped_column(String(10), nullable=False)  # 'win' | 'loss'
    predicted_set_path: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # '2-0'|'2-1'|'1-2'|'0-2'
    predicted_win_probability: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 0-100
    confidence_level: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # 'high'|'medium'|'low'
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # Phase B-7: 書き込みチーム
    team_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("teams.id"), nullable=True, index=True)



# ─── Phase S3: 同期競合ログ ──────────────────────────────────────────────────

class SyncConflict(Base):
    """インポート時に検出された競合レコードの記録。
    Phase 2 以降の競合 UI で per-record 採用選択に使用する。
    """
    __tablename__ = "sync_conflicts"
    __table_args__ = (
        Index("ix_sc_record_uuid", "record_uuid"),
        Index("ix_sc_resolution",  "resolution"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    record_table: Mapped[str] = mapped_column(String(50), nullable=False)
    record_uuid: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    import_device: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    import_updated_at: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    local_updated_at: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    incoming_snapshot: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reason: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    resolution: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ─── CV 解析アーティファクト ──────────────────────────────────────────────────


class MatchCVArtifact(Base):
    """YOLO / TrackNet / アライメント解析の結果を試合単位で保存するアーティファクト。

    annotation truth への直接書き込みは行わず、recoverable な JSON として保持する。
    artifact_type:
      'yolo_player_detections'   — YOLO バッチ検出結果（フレーム別）
      'tracknet_shuttle_track'   — TrackNet バッチのシャトル軌跡（フレーム別）
      'cv_alignment'             — YOLO + TrackNet 統合アライメント結果
    """
    __tablename__ = "match_cv_artifacts"
    __table_args__ = (
        Index("ix_cv_match_type", "match_id", "artifact_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("matches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    artifact_type: Mapped[str] = mapped_column(String(50), nullable=False)
    frame_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    backend_used: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    # summary: コート位置サマリーなど（軽量、常時読み込み）
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)   # JSON
    # data: フレーム別生データ（大容量、オンデマンド読み込み）
    data: Mapped[Optional[str]] = mapped_column(Text, nullable=True)       # JSON
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    match: Mapped["Match"] = relationship("Match", back_populates="cv_artifacts")


# ─── 試合前統計予測スナップショット ──────────────────────────────────────────────

class PrematchPrediction(Base):
    """試合前統計予測のスナップショット。

    対象試合の日付より前のデータのみで算出し保存する。
    一度保存したら再計算しない（スナップショット）。
    force=true パラメータで上書き再計算可能。

    match_id + player_id の組み合わせはユニーク。
    """
    __tablename__ = "prematch_predictions"
    __table_args__ = (
        Index("ix_pp_match_player", "match_id", "player_id", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[int] = mapped_column(Integer, ForeignKey("matches.id"), nullable=False)
    player_id: Mapped[int] = mapped_column(Integer, ForeignKey("players.id"), nullable=False)
    opponent_id: Mapped[int] = mapped_column(Integer, ForeignKey("players.id"), nullable=False)
    cutoff_date: Mapped[date] = mapped_column(Date, nullable=False)
    tournament_level: Mapped[str] = mapped_column(String(20), nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    h2h_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    win_probability: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    set_distribution: Mapped[Optional[str]] = mapped_column(Text, nullable=True)   # JSON
    most_likely_scorelines: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON
    score_volatility: Mapped[Optional[str]] = mapped_column(Text, nullable=True)    # JSON
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    match_narrative: Mapped[Optional[str]] = mapped_column(Text, nullable=True)     # JSON
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # Phase B-7: 書き込みチーム
    team_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("teams.id"), nullable=True, index=True)


# ─── コンディション（体調）Phase 1 ──────────────────────────────────────────────

class Condition(Base):
    """選手のコンディション記録（InBody / Hooper / RPE / 自由記述）。

    Phase 1: InBody, Hooper Index, RPE, 自由記述のみ運用。
    質問票・採点・妥当性・本人内変動関連カラムは Phase 2 用プレースホルダ（全 NULL 許容）。
    """
    __tablename__ = "conditions"
    __table_args__ = (
        Index("ix_conditions_player_id", "player_id"),
        Index("ix_conditions_measured_at", "measured_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(Integer, ForeignKey("players.id"), nullable=False)
    measured_at: Mapped[date] = mapped_column(Date, nullable=False)
    condition_type: Mapped[str] = mapped_column(String(20), nullable=False, default="weekly")  # weekly / pre_match
    # pre_match 時に紐付く試合（weekly は NULL）
    match_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("matches.id"), nullable=True, index=True
    )

    # InBody
    weight_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    muscle_mass_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    body_fat_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    body_fat_mass_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lean_mass_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ecw_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    arm_l_muscle_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    arm_r_muscle_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    leg_l_muscle_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    leg_r_muscle_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    trunk_muscle_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bmr_kcal: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Hooper Index（1〜7 のスケール想定、nullable）
    hooper_sleep: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    hooper_soreness: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    hooper_stress: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    hooper_fatigue: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    hooper_index: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # RPE（session-RPE 法）
    session_rpe: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    session_duration_min: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    session_load: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # 質問票 / 採点 / 妥当性 / 本人内変動（Phase 2 用プレースホルダ）
    questionnaire_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    f1_physical: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    f2_stress: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    f3_mood: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    f4_motivation: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    f5_sleep_life: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    total_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ccs_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    delta_prev: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    delta_3ma: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    delta_28ma: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    z_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    validity_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    validity_flag: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    validity_flags_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 補助
    sleep_hours: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Phase A1: 要配慮個人情報の自由記述フィールドは Fernet 透過暗号化
    # DB ファイル奪取時に平文露出しないよう EncryptedText 型を使用する
    injury_notes: Mapped[Optional[str]] = mapped_column(_EncryptedText, nullable=True)
    general_comment: Mapped[Optional[str]] = mapped_column(_EncryptedText, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    player: Mapped["Player"] = relationship("Player", back_populates="conditions")


# ─── コンディション期間タグ ──────────────────────────────────────────────────

class ConditionTag(Base):
    """選手ごとの任意期間ラベル（合宿 / 大会前 / ストレス期など）。

    end_date=NULL の場合は単発イベント（当日のみ）扱い。
    期間内外でコンディション指標の差分比較を行うためのメタデータ。
    """
    __tablename__ = "condition_tags"
    __table_args__ = (
        Index("ix_condition_tags_player_id", "player_id"),
        Index("ix_condition_tags_start_date", "start_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(Integer, ForeignKey("players.id"), nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    color: Mapped[str] = mapped_column(String(7), nullable=False, default="#3b82f6")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    player: Mapped["Player"] = relationship("Player", back_populates="condition_tags")


# ─── Expert Labeler Phase 1 ─────────────────────────────────────────────────

class ExpertLabel(Base):
    """コーチ・アナリスト向け専門家アノテーション（体勢/重心/タイミング）。

    同一ストローク × 同一ロールで 1 件のみ（UPSERT 対象）。
    """
    __tablename__ = "expert_labels"
    __table_args__ = (
        UniqueConstraint("stroke_id", "annotator_role", name="uq_expert_labels_stroke_role"),
        Index("ix_expert_labels_match_id", "match_id"),
        Index("ix_expert_labels_stroke_id", "stroke_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[int] = mapped_column(Integer, ForeignKey("matches.id"), nullable=False)
    stroke_id: Mapped[int] = mapped_column(Integer, ForeignKey("strokes.id"), nullable=False)
    annotator_role: Mapped[str] = mapped_column(String(20), nullable=False)  # coach/analyst
    posture_collapse: Mapped[str] = mapped_column(String(20), nullable=False)  # none/minor/major
    weight_distribution: Mapped[str] = mapped_column(String(20), nullable=False)  # left/right/center/floating
    shot_timing: Mapped[str] = mapped_column(String(20), nullable=False)  # early/optimal/late
    confidence: Mapped[int] = mapped_column(Integer, default=2)  # 1-3
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    # Phase B-7: 書き込みチーム
    team_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("teams.id"), nullable=True, index=True)


class ShotTypeAnnotation(Base):
    """管理者によるショット種別アノテーション（AI学習データ収集用）。

    admin 権限者のみが書き込み可能。stroke_id ごとに1件（UPSERT対象）。
    """
    __tablename__ = "shot_type_annotations"
    __table_args__ = (
        UniqueConstraint("stroke_id", name="uq_shot_type_annotation_stroke"),
        Index("ix_shot_type_annotations_match_id", "match_id"),
        Index("ix_shot_type_annotations_stroke_id", "stroke_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[int] = mapped_column(Integer, ForeignKey("matches.id"), nullable=False)
    stroke_id: Mapped[int] = mapped_column(Integer, ForeignKey("strokes.id"), nullable=False)
    shot_type: Mapped[str] = mapped_column(String(30), nullable=False)   # canonical shot type
    confidence: Mapped[int] = mapped_column(Integer, default=2)          # 1-3
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default="")
    annotator_user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ClipCache(Base):
    """ミスストロークのクリップ切り出しキャッシュ。"""
    __tablename__ = "clip_cache"
    __table_args__ = (
        UniqueConstraint("stroke_id", name="uq_clip_cache_stroke"),
        Index("ix_clip_cache_match_id", "match_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[int] = mapped_column(Integer, ForeignKey("matches.id"), nullable=False)
    stroke_id: Mapped[int] = mapped_column(Integer, ForeignKey("strokes.id"), nullable=False)
    clip_path: Mapped[str] = mapped_column(String(500), nullable=False)
    start_frame: Mapped[int] = mapped_column(Integer, nullable=False)
    end_frame: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # Phase B-7: 書き込みチーム
    team_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("teams.id"), nullable=True, index=True)


# ─── INFRA Phase B: 解析パイプライン ────────────────────────────────────────

class AnalysisJob(Base):
    """解析ジョブ（パイプライン実行単位）。GPU 競合回避のためシリアル実行。"""
    __tablename__ = "analysis_jobs"
    __table_args__ = (
        Index("ix_analysis_jobs_match_id", "match_id"),
        Index("ix_analysis_jobs_status",   "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[int] = mapped_column(Integer, ForeignKey("matches.id"), nullable=False)
    job_type: Mapped[str] = mapped_column(String(40), nullable=False, default="full_pipeline")
    # queued / running / done / failed
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    progress: Mapped[float] = mapped_column(Float, default=0.0)  # 0.0-1.0
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    enqueued_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    worker_host: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)


class ShuttleTrack(Base):
    """TrackNet 由来のシャトル軌跡（フレーム単位）。"""
    __tablename__ = "shuttle_tracks"
    __table_args__ = (
        Index("ix_shuttle_tracks_match_frame", "match_id", "frame_index"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[int] = mapped_column(Integer, ForeignKey("matches.id"), nullable=False)
    frame_index: Mapped[int] = mapped_column(Integer, nullable=False)
    ts_sec: Mapped[float] = mapped_column(Float, nullable=False)
    x: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    y: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)


class PoseFrame(Base):
    """Pose 推定結果（side: player_a/player_b）。landmarks_json は JSON 文字列。"""
    __tablename__ = "pose_frames"
    __table_args__ = (
        Index("ix_pose_frames_match_frame", "match_id", "frame_index"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[int] = mapped_column(Integer, ForeignKey("matches.id"), nullable=False)
    frame_index: Mapped[int] = mapped_column(Integer, nullable=False)
    ts_sec: Mapped[float] = mapped_column(Float, nullable=False)
    side: Mapped[str] = mapped_column(String(20), nullable=False)  # player_a/player_b
    landmarks_json: Mapped[str] = mapped_column(Text, nullable=False)


class CenterOfGravity(Base):
    """重心・バランス指標（Pose 由来の派生値）。"""
    __tablename__ = "center_of_gravity"
    __table_args__ = (
        Index("ix_cog_match_frame", "match_id", "frame_index"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[int] = mapped_column(Integer, ForeignKey("matches.id"), nullable=False)
    frame_index: Mapped[int] = mapped_column(Integer, nullable=False)
    side: Mapped[str] = mapped_column(String(20), nullable=False)
    left_pct: Mapped[float] = mapped_column(Float, default=0.5)
    right_pct: Mapped[float] = mapped_column(Float, default=0.5)
    forward_lean: Mapped[float] = mapped_column(Float, default=0.0)
    stability_score: Mapped[float] = mapped_column(Float, default=0.0)


class ShotInference(Base):
    """ショット分類器の推論結果（stroke 単位）。"""
    __tablename__ = "shot_inferences"
    __table_args__ = (
        Index("ix_shot_inferences_stroke", "stroke_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stroke_id: Mapped[int] = mapped_column(Integer, ForeignKey("strokes.id"), nullable=False)
    shot_type: Mapped[str] = mapped_column(String(30), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    model_version: Mapped[str] = mapped_column(String(40), default="mock-v0")


class PublicInquiry(Base):
    """Public website inquiry submitted through the top-domain contact form."""

    __tablename__ = "public_inquiries"
    __table_args__ = (
        Index("ix_public_inquiries_status", "status"),
        Index("ix_public_inquiries_created_at", "created_at"),
        Index("ix_public_inquiries_category", "category"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    organization: Mapped[Optional[str]] = mapped_column(String(160), nullable=True)
    role: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    contact_reference: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="new")
    # R42: 問い合わせ種別 ("general" / "ban_appeal" 等)。ban_appeal は WAF 誤 ban
    # 申し立てチャネルからの投稿で、admin 画面で目立つタグ付け表示の対象。
    category: Mapped[str] = mapped_column(String(40), nullable=False, default="general")
    admin_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(400), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ─── A Phase 1: ダブルス4人+シャトル時系列位置データ ─────────────────────────

class PlayerPositionFrame(Base):
    """ダブルス4人+シャトルの時系列位置データ (A Phase 1)。

    frame_num はマッチ内の通し連番（カメラ fps × 経過秒）。
    player_a/b はメインの2プレイヤー（シングルス・ダブルス共通）。
    partner_a/b はダブルスのみ使用（シングルスは NULL）。
    source: yolo_tracked / manual / interpolated
    """
    __tablename__ = "player_position_frames"
    __table_args__ = (
        Index("ix_ppf_match_frame", "match_id", "frame_num"),
        Index("ix_ppf_rally", "rally_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[int] = mapped_column(Integer, ForeignKey("matches.id"), nullable=False)
    set_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("sets.id"), nullable=True)
    rally_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("rallies.id"), nullable=True)
    frame_num: Mapped[int] = mapped_column(Integer, nullable=False)

    # プレイヤーA（サイドA）の正規化コート座標 (0.0〜1.0)
    player_a_x: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    player_a_y: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # プレイヤーB（サイドB）の正規化コート座標
    player_b_x: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    player_b_y: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # ダブルスパートナーA（シングルスは NULL）
    partner_a_x: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    partner_a_y: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # ダブルスパートナーB（シングルスは NULL）
    partner_b_x: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    partner_b_y: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # シャトル座標（検出できない場合は NULL）
    shuttle_x: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    shuttle_y: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # データソース種別
    source: Mapped[str] = mapped_column(String(20), default="yolo_tracked")  # yolo_tracked/manual/interpolated

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ─── Phase A: アクセスログ ────────────────────────────────────────────────────

class AccessLog(Base):
    """ログイン・エクスポート・アクセス拒否の記録。"""
    __tablename__ = "access_logs"
    __table_args__ = (
        Index("ix_access_logs_user_id",    "user_id"),
        Index("ix_access_logs_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Round 233 R233-A: audit log は append-only であり、user 削除時に FK 制約で
    # access_logs.user_id を NULL 化すると HMAC chain (row_hash) が破損する。
    # migration 0026 で FK を drop 済 (orphan integer reference を許容)。
    # ORM 側でも ForeignKey を外し、INSERT 時の参照整合性チェックを発生させない。
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False)            # login/logout/export/deny
    resource_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    resource_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)        # JSON
    ip_addr: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # 改ざん検知用ハッシュチェーン。row_hash = HMAC(secret, prev_hash || canonical(row))
    prev_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    row_hash:  Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


class UploadSession(Base):
    """ブラウザからの分割動画アップロード状態。

    chunk は {upload_id}.part ファイルに pwrite（絶対オフセット書き込み）で配置するため
    到着順不同でも安全。受信管理は received_bitmap（bytes, 1bit/chunk）で行う。
    """
    __tablename__ = "upload_sessions"
    __table_args__ = (
        Index("ix_upload_sessions_status",  "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # UUID = upload_id
    user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    match_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("matches.id"), nullable=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    total_size: Mapped[int] = mapped_column(Integer, nullable=False)   # bytes
    chunk_size: Mapped[int] = mapped_column(Integer, nullable=False)
    total_chunks: Mapped[int] = mapped_column(Integer, nullable=False)
    # bitmap。1bit/chunk で受領状態を保持。ceil(total_chunks/8) bytes。
    received_bitmap: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, default=b"")
    received_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="uploading")  # uploading/completed/aborted/expired
    final_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # R-1: MediaRecorder 等で事前に total_size が確定しない経路向け。
    # True の場合、chunk を append し finalize 時にファイルサイズを確定する。
    streaming: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


# ─── Phase A3: Export パッケージ nonce 重複排除テーブル ─────────────────────
class ConsumedExportNonce(Base):
    """Export パッケージの nonce を消費済みとして記録し、二重インポートを防ぐ。

    1 つの export パッケージは 1 回のみ import 可能。
    定期的に古いレコード (> 30 日) はクリーンアップする。
    """
    __tablename__ = "consumed_export_nonces"
    __table_args__ = (
        Index("ix_consumed_export_nonces_consumed_at", "consumed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nonce: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    consumed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)



# ─── M-A2: メール認証 / パスワードリセット / 招待トークン ────────────────────
# 設計:
#   - トークン本体は DB に保存しない。HMAC ハッシュのみ保存 (DB 漏洩時の悪用防止)。
#   - 1 回利用 (consumed_at) + 期限 (expires_at) + スコープ別テーブル
#   - 同一ユーザーの複数発行は許容するが、verify 時は最新の未消費を使用


class EmailVerificationToken(Base):
    """メールアドレス検証トークン (新規登録 / メール変更時)。"""
    __tablename__ = "email_verification_tokens"
    __table_args__ = (
        Index("ix_evt_user_id", "user_id"),
        Index("ix_evt_expires_at", "expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # トークンの HMAC-SHA256 ハッシュ (hex 64 文字)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)  # 検証対象メール
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    consumed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class PasswordResetToken(Base):
    """パスワードリセットトークン。"""
    __tablename__ = "password_reset_tokens"
    __table_args__ = (
        Index("ix_prt_user_id", "user_id"),
        Index("ix_prt_expires_at", "expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    consumed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    requested_ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class InvitationToken(Base):
    """招待トークン (admin/coach がメール経由でユーザーを招待)。"""
    __tablename__ = "invitation_tokens"
    __table_args__ = (
        Index("ix_invt_email", "email"),
        Index("ix_invt_expires_at", "expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="analyst")
    team_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("teams.id"), nullable=True)
    inviter_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    consumed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    consumed_by_user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


# ─── Phase Pay-1: 課金 / 決済 (billing) ─────────────────────────────────────
# フロント完全非公開。表に出すのは Phase Pay-2 (有償切替時)。
# 3 プロバイダ並列: Stripe (カード/Apple Pay/Google Pay) + KOMOJU (PayPay/メルペイ等)
# + Univapay (d払い/au PAY、Phase Pay-3 で本実装)


class BillingProduct(Base):
    """課金可能な商品マスタ。code は不変識別子 (例: "report_full")。"""
    __tablename__ = "billing_products"
    __table_args__ = (
        Index("ix_billing_products_code", "code", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 税込価格を整数円で保持 (浮動小数誤差回避)
    price_jpy: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, server_default="1")
    extra_metadata: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class BillingOrder(Base):
    """個別注文。public_id (UUID) のみ外部露出する。"""
    __tablename__ = "billing_orders"
    __table_args__ = (
        Index("ix_billing_orders_user_id", "user_id"),
        Index("ix_billing_orders_status", "status"),
        Index("ix_billing_orders_public_id", "public_id", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True, default=_new_uuid)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey("billing_products.id"), nullable=False)
    # 注文時点の価格 (商品マスタが後で値上げされても履歴を保持)
    amount_jpy: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="JPY", server_default="JPY")
    # pending / authorized / paid / failed / refunded / canceled / expired
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    # credit_card / apple_pay / google_pay / paypay / merpay / rakuten_pay / linepay / konbini / bank_transfer / d_barai / au_pay
    payment_method: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    provider: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # stripe / komoju / univapay
    provider_session_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    provider_payment_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    # 注文紐付けの match_id 等の追加情報
    extra_metadata: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    return_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    cancel_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    refunded_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class BillingWebhookEvent(Base):
    """Webhook イベントの監査ログ + 二重処理防止。

    event_id は各プロバイダ固有 ID で UNIQUE。
    """
    __tablename__ = "billing_webhook_events"
    __table_args__ = (
        Index("ix_billing_webhook_events_provider_event", "provider", "event_id", unique=True),
        Index("ix_billing_webhook_events_processed_at", "processed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    event_id: Mapped[str] = mapped_column(String(200), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    raw_payload: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    signature_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="0")
    related_order_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("billing_orders.id"), nullable=True)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class BillingEntitlement(Base):
    """購入により得た権利 (レポート閲覧 / ダウンロード 等)。"""
    __tablename__ = "billing_entitlements"
    __table_args__ = (
        Index("ix_billing_entitlements_user_id", "user_id"),
        Index("ix_billing_entitlements_resource", "resource_type", "resource_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    order_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("billing_orders.id"), nullable=True)
    # "report_view" / "report_download" / "subscription_team" 等
    entitlement_type: Mapped[str] = mapped_column(String(50), nullable=False)
    resource_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    resource_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    valid_to: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)  # NULL = 無期限
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    granted_by_user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


# ─── R-1: サーバ集約録画アーティファクト ──────────────────────────────────
# Sender (iOS/Android) → サーバ自動録画。
# UploadSession 完了で生成され、Match.video_local_path に紐付く。
class ServerVideoArtifact(Base):
    """Sender からの自動録画ストリームのサーバ側成果物。"""
    __tablename__ = "server_video_artifacts"
    __table_args__ = (
        Index("ix_sva_match_id", "match_id"),
        Index("ix_sva_started_at", "started_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("matches.id"), nullable=True)
    upload_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    sender_user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    mime_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    finalized_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # CV/Worker 解析向け同期状態 (R-3 連携)
    worker_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


# ─── 0031: 製品テレメトリ ─────────────────────────────────────────────────
class ProductEvent(Base):
    """高密度イベントログ。プロダクト改善目的の仮名化テレメトリ。

    GDPR Art 6(1)(f) legitimate interest / APPI 第18条但書 を法的根拠とし、
    Privacy Notice §テレメトリで開示。同意 popup での opt-in は取らず、
    Art 21 objection 受付窓口で停止対応する設計。

    PostgreSQL では server_ts で月次パーティション (migration 0031)。
    user_id / team_id は HMAC で hash 化し、DB ダンプから逆引き不可とする。
    """
    __tablename__ = "product_events"
    __table_args__ = (
        Index("ix_pe_type_ts_app", "event_type", "server_ts"),
    )

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    team_id_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    role: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    # JSONB (PG) / TEXT (SQLite). アクセスは backend.utils.telemetry helpers 経由で。
    props: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    client_ts: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    server_ts: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    app_version: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    platform: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # desktop/mobile_web/mobile_pwa


class TutorialCompletion(Base):
    """ユーザー × チュートリアル ID ごとの進行状態。

    Settings > ヘルプ > チュートリアル から replay 可能。
    status: 'in_progress' | 'completed' | 'skipped'
    """
    __tablename__ = "tutorial_completion"
    __table_args__ = (
        UniqueConstraint("user_id", "tutorial_id", name="uq_tutorial_user_tut"),
        Index("ix_tutorial_completion_user", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    tutorial_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="in_progress")
    last_step: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    replay_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


# ─── 0031: captured_minor_flag 自動計算 (SQLAlchemy event) ───────────────
def _compute_captured_minor_flag(session, match_obj):
    """Match.date 時点で player_a / player_b のいずれかが未成年だったか判定。

    判定基準: その match の date (撮影日) において、参加選手の date_of_birth
    が分かる範囲で <18 歳の者が 1 人でもいれば True。全員 dob 不明なら NULL。
    """
    from backend.db.models import Player  # 局所 import (循環回避)
    if match_obj.date is None:
        return
    pids = [match_obj.player_a_id, match_obj.player_b_id,
            match_obj.partner_a_id, match_obj.partner_b_id]
    pids = [p for p in pids if p is not None]
    if not pids:
        match_obj.captured_minor_flag = None
        return
    players = session.query(Player).filter(Player.id.in_(pids)).all()
    has_any_age_info = False
    any_minor = False
    capture_year = match_obj.date.year
    for p in players:
        by = getattr(p, "birth_year", None)
        if by is None:
            continue
        has_any_age_info = True
        # 撮影年時点の年齢 (year 粒度なので保守側に倒し最大年齢で判定: 18 未満=未成年)
        try:
            age = capture_year - int(by)
            if age < 18:
                any_minor = True
                break
        except (TypeError, ValueError):
            continue
    if not has_any_age_info:
        match_obj.captured_minor_flag = None
    else:
        match_obj.captured_minor_flag = any_minor


from sqlalchemy import event as _sa_event  # noqa: E402

@_sa_event.listens_for(Match, "before_insert")
def _match_before_insert(_mapper, conn, target):
    # Session 取得 (event 内では非標準だが連携用)
    from sqlalchemy.orm import Session as _Session
    sess = _Session.object_session(target)
    if sess is None:
        return
    try:
        _compute_captured_minor_flag(sess, target)
    except Exception:
        # 例外で insert を止めない
        pass

@_sa_event.listens_for(Match, "before_update")
def _match_before_update(_mapper, conn, target):
    from sqlalchemy.orm import Session as _Session
    sess = _Session.object_session(target)
    if sess is None:
        return
    try:
        _compute_captured_minor_flag(sess, target)
    except Exception:
        pass


# ─── 0032: request_logs / security_events (外部攻撃可視化) ─────────────────
class RequestLog(Base):
    """HTTP リクエスト単位の生ログ。攻撃判定 / フォレンジック用一次ソース。
    HMAC chain は付けない (高頻度書き込みで lock 競合するため)。
    PostgreSQL では月次 RANGE partition (migration 0032 で構築)。"""
    __tablename__ = "request_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    method: Mapped[str] = mapped_column(String(8), nullable=False)
    path: Mapped[str] = mapped_column(String(512), nullable=False)
    query: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    status: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ip_addr: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    xff: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    ua: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    referer: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    request_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    bytes_in: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    bytes_out: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cf_ray: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    # 0034: 'backend' (FastAPI 到達) / 'nginx' (エッジ access ログ取り込み)
    source: Mapped[str] = mapped_column(String(10), nullable=False, default="backend")


class SecurityEvent(Base):
    """攻撃検知イベント (rate_limit_hit, probe_attempt, honeytoken_hit,
    path_normalization_block 等)。重要度別 severity を持つ。"""
    __tablename__ = "security_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False, default="info")
    ip_addr: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    method: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    ua: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    request_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    # PostgreSQL では JSONB、SQLite では TEXT として保存される (SA の JSON 型が
    # dialect ごとに切替える)。emit_security_event() からは dict を渡す。
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


# ─── 0033: error_logs (未処理例外のスタックトレース捕捉) ───────────────────
class ErrorLog(Base):
    """グローバル例外ハンドラが拾った unhandled exception を記録。
    request_id で request_logs と相関できる。"""
    __tablename__ = "error_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.current_timestamp())
    request_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    method: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    exc_type: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    traceback: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    input_repr: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    internal_code: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ip_addr: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


# ─── 0035: chat_sessions / chat_messages (Growth Advisor chat) ────────────
class ChatSession(Base):
    """Growth Advisor chat セッション。coach/analyst/admin のみ作成可能。
    player には公開しない (player 安全 UX 上、対話的 LLM チャットは coach/analyst
    の補助ツールとして提供)。"""
    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    role_at_creation: Mapped[str] = mapped_column(String(32), nullable=False)
    lang: Mapped[str] = mapped_column(String(8), nullable=False, default="ja")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    last_used_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # 会話駆動スコープ (period / shot_type / zone …)。Migration 0037 で追加。
    current_scope: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)


class ChatMessage(Base):
    """Chat 1 発話。author='user'|'ai'|'system'。LLM 出力時は validation_reason /
    is_fallback / confidence / evidence_path / generator を必ず付与する。"""
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("chat_sessions.id"), nullable=False, index=True)
    turn: Mapped[int] = mapped_column(Integer, nullable=False)
    author: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    generator: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    is_fallback: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    validation_reason: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    evidence_path: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    # ユーザがメッセージに添付した分析対象期間 (parsePeriod 抽出, YYYY-MM-DD)
    date_from: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    date_to: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
