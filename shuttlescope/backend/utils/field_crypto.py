"""フィールドレベル透過暗号化 (Fernet / AES-128-CBC + HMAC-SHA256)。

対象: 要配慮個人情報の自由記述フィールド。
  - Condition.injury_notes
  - Condition.general_comment
  - ConditionTag.label (機密ラベル運用時)
  - Comment.body
  - Bookmark.note

設計:
  - SQLAlchemy TypeDecorator で透過化 (アプリ層は平文を読み書き、DB は暗号文)
  - 鍵バージョン埋め込み: "v1:base64ciphertext" 形式 → 将来の鍵ローテで旧鍵復号維持
  - 鍵: 環境変数 SS_FIELD_ENCRYPTION_KEY (Fernet key, 32 bytes base64)
  - 起動時に未設定なら警告（本番モードでは強制 error）

セキュリティ:
  - Fernet は AES-128-CBC + HMAC-SHA256 で改ざん検知込み
  - DB ファイル奪取 → 暗号文のみ取得 → 鍵がなければ復号不可
  - 鍵は SECRET_KEY とは分離 (1 つ漏洩しても他は維持)
"""
from __future__ import annotations

import base64
import logging
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import String, Text
from sqlalchemy.types import TypeDecorator

logger = logging.getLogger(__name__)

_KEY_VERSION_PREFIX = "v1:"  # ローテ時に v2: 等を追加し、複数鍵を保持する設計

_fernet_cache: Optional[Fernet] = None
_warned_no_key = False


def _get_fernet() -> Optional[Fernet]:
    """SS_FIELD_ENCRYPTION_KEY から Fernet インスタンスを取得する。

    未設定時は None を返す（暗号化スキップ → 平文保存にフォールバック）。
    本番運用では必ず設定すること。
    """
    global _fernet_cache, _warned_no_key
    if _fernet_cache is not None:
        return _fernet_cache

    try:
        from backend.config import settings
        key = (getattr(settings, "ss_field_encryption_key", "") or "").strip()
    except Exception:
        key = (os.environ.get("SS_FIELD_ENCRYPTION_KEY", "") or "").strip()

    if not key:
        if not _warned_no_key:
            logger.warning(
                "[field_crypto] SS_FIELD_ENCRYPTION_KEY 未設定。機密フィールドは平文で保存されます。"
                " 本番運用前に必ず設定してください: "
                "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )
            _warned_no_key = True
        return None

    try:
        _fernet_cache = Fernet(key.encode("utf-8") if isinstance(key, str) else key)
    except Exception as exc:
        logger.error("[field_crypto] Fernet 鍵が不正です: %s", exc)
        return None
    return _fernet_cache


def encrypt_field(plaintext: Optional[str]) -> Optional[str]:
    """平文を暗号化して "v1:<base64>" 形式で返す。鍵未設定時は平文をそのまま返す。"""
    if plaintext is None or plaintext == "":
        return plaintext
    f = _get_fernet()
    if f is None:
        return plaintext  # フォールバック (起動時警告済み)
    try:
        token = f.encrypt(plaintext.encode("utf-8"))
        return _KEY_VERSION_PREFIX + token.decode("ascii")
    except Exception as exc:
        logger.error("[field_crypto] encrypt failed: %s", exc)
        return plaintext


def decrypt_field(ciphertext: Optional[str]) -> Optional[str]:
    """"v1:<base64>" 形式の暗号文を復号する。

    - "v1:" プレフィックスがない値は平文として扱う（移行期間中の互換性）
    - 鍵未設定時は文字列をそのまま返す
    - 復号失敗時は元の文字列を返し WARNING ログ
    """
    if ciphertext is None or ciphertext == "":
        return ciphertext
    if not isinstance(ciphertext, str):
        return ciphertext
    if not ciphertext.startswith(_KEY_VERSION_PREFIX):
        return ciphertext  # 平文 (移行期間 or 未暗号化レコード)
    f = _get_fernet()
    if f is None:
        # 鍵が消えた状態で暗号文を読もうとした → 復号不可
        logger.error("[field_crypto] 暗号文があるのに鍵がありません。鍵紛失の可能性。")
        return "[ENCRYPTED:KEY_MISSING]"
    body = ciphertext[len(_KEY_VERSION_PREFIX):]
    try:
        return f.decrypt(body.encode("ascii")).decode("utf-8")
    except InvalidToken:
        logger.error("[field_crypto] decrypt failed: 改ざんまたは鍵不一致")
        return "[ENCRYPTED:INVALID]"
    except Exception as exc:
        logger.error("[field_crypto] decrypt error: %s", exc)
        return "[ENCRYPTED:ERROR]"


class EncryptedText(TypeDecorator):
    """SQLAlchemy 型: アプリ層は平文 str を扱い、DB には Fernet 暗号文を保存する。

    使い方:
        memo: Mapped[Optional[str]] = mapped_column(EncryptedText, nullable=True)
    """
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return encrypt_field(value)

    def process_result_value(self, value, dialect):
        return decrypt_field(value)


class EncryptedString(TypeDecorator):
    """String カラム用の暗号化型。長さは暗号文も収まるよう余裕を持って指定すること。

    Fernet 暗号文サイズ ≈ ceil((plaintext_len + 73) / 64) * 88
    例: plaintext 100 文字 → 暗号文 ≈ 248 文字 + "v1:" 3 文字 = 251 文字
    """
    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return encrypt_field(value)

    def process_result_value(self, value, dialect):
        return decrypt_field(value)


def is_encryption_active() -> bool:
    """暗号化が有効になっているか（鍵が読めるか）を返す。テスト・診断用。"""
    return _get_fernet() is not None


# 鍵が「読める」ことと「正しい鍵である」ことは別。Fernet 鍵は 32 byte base64 で
# あれば構文上は妥当なので、別の鍵に差し替わっていても _get_fernet() は成功する。
# 実際に往復させて初めて、その鍵で保存済みデータを扱えると言える。
class FieldKeyError(RuntimeError):
    """フィールド暗号鍵が無い / 壊れている / 既存データを復号できない。"""


CANARY_PLAINTEXT = "shuttlescope-field-key-canary-v1"


def verify_key_roundtrip() -> None:
    """鍵が「使える」ことだけを確認する。失敗なら FieldKeyError。

    注意: これは **鍵が正しいことを保証しない**。その場で暗号化して同じ鍵で復号する
    だけなので、新しく生成した別の鍵でも通る。保存済みデータをその鍵で扱えるかは
    verify_key_matches_stored_data() で確認すること。
    """
    f = _get_fernet()
    if f is None:
        raise FieldKeyError(
            "SS_FIELD_ENCRYPTION_KEY が未設定または不正です。"
            "暗号化フィールドは復号できず、新規保存は平文になります。"
        )
    token = encrypt_field(CANARY_PLAINTEXT)
    if not token or not token.startswith(_KEY_VERSION_PREFIX):
        raise FieldKeyError("暗号化に失敗しました (鍵は読めるが encrypt が機能していません)。")
    if decrypt_field(token) != CANARY_PLAINTEXT:
        raise FieldKeyError("復号結果が一致しません (鍵が壊れています)。")


def verify_key_matches_stored_data(session) -> None:
    """DB に永続化したカナリアで「この鍵が今のデータの鍵か」を確認する。

    その場限りの往復では、正しい鍵と *新しく生成した別の鍵* を区別できない。
    別鍵で起動すると:
      - 既存の暗号文が全て復号不能になる
      - バックフィルが平文を **別鍵で** 暗号化し、鍵が混在した DB になる
    これを防ぐため、初回に暗号化したカナリアを DB へ保存し、以降は毎回それを
    復号して一致を確認する。

    カナリアが未登録なら作成する (初回起動 / 新規環境)。既存の暗号化データが
    無い環境でも成立するよう、既存列ではなく専用の 1 行を使う。
    """
    from sqlalchemy import text as _text

    verify_key_roundtrip()

    row = session.execute(
        _text("SELECT value FROM field_key_canary WHERE id = 1")
    ).scalar()

    if row is None:
        session.execute(
            _text("INSERT INTO field_key_canary (id, value) VALUES (1, :v)"),
            {"v": encrypt_field(CANARY_PLAINTEXT)},
        )
        session.commit()
        logger.info("[field_crypto] 鍵カナリアを新規登録しました。")
        return

    if not can_decrypt(row):
        raise FieldKeyError(
            "保存済みカナリアを現在の鍵で復号できません。"
            "別の鍵が設定されている可能性が高く、このまま起動すると既存の暗号文が"
            "全て読めず、新規保存は別鍵で暗号化されて鍵が混在します。"
            "退避した正しい鍵を復元してください (新しい鍵を生成してはいけません)。"
        )
    if decrypt_field(row) != CANARY_PLAINTEXT:
        raise FieldKeyError("カナリアの内容が一致しません (データ破損の可能性)。")


def can_decrypt(ciphertext: Optional[str]) -> bool:
    """その暗号文を現在の鍵で実際に復号できるかを返す。

    `v1:` 前置の有無だけでは「暗号化済みか」の判定にならない (別の鍵で暗号化
    された値も前置は同じ)。バックフィルの二重暗号化防止と、起動時に既存データを
    本当に読めるかの確認に使う。
    """
    if ciphertext is None or not isinstance(ciphertext, str):
        return False
    if not ciphertext.startswith(_KEY_VERSION_PREFIX):
        return False
    f = _get_fernet()
    if f is None:
        return False
    try:
        f.decrypt(ciphertext[len(_KEY_VERSION_PREFIX):].encode("ascii"))
        return True
    except Exception:
        return False


def generate_key() -> str:
    """新規 Fernet 鍵を生成する（CLI / 鍵ローテ用）。

    Returns: base64 エンコード済み 32 バイト文字列
    """
    return Fernet.generate_key().decode("ascii")
