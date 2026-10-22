"""問い合わせ（PublicInquiry）と承認待ちユーザを同じメールで結び付ける。

問い合わせの `contact_reference` は自由入力だが、メールアドレスが書かれていれば
承認待ちユーザの `email` と正規化して突き合わせられる。結び付きは管理者に
候補として見せるだけで、ロールの自動付与はしない。
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.db.models import PublicInquiry, User


def normalize_email(value: Optional[str]) -> Optional[str]:
    """前後の空白を除き小文字にする。メールの形でなければ None。"""
    v = (value or "").strip().lower()
    if not v or "@" not in v or " " in v:
        return None
    return v


def requested_role_from_text(text: Optional[str]) -> Optional[str]:
    """問い合わせの「立場」から player / coach / analyst のどれを希望したかを読む。

    読み取れないときは None。複数に当たるときは曖昧なので None にする。
    """
    v = (text or "").strip().lower()
    if not v:
        return None
    found = set()
    if "analyst" in v or "アナリスト" in v:
        found.add("analyst")
    if "coach" in v or "コーチ" in v or "監督" in v:
        found.add("coach")
    if "player" in v or "選手" in v:
        found.add("player")
    if len(found) == 1:
        return next(iter(found))
    return None


def inquiries_by_email(db: Session, emails: list[str]) -> dict[str, list[PublicInquiry]]:
    """正規化済みメールごとに、同じメールを連絡先にした問い合わせ（新しい順）を返す。"""
    wanted = {e for e in emails if e}
    if not wanted:
        return {}
    rows = (
        db.query(PublicInquiry)
        .filter(func.lower(func.trim(PublicInquiry.contact_reference)).in_(wanted))
        .order_by(PublicInquiry.created_at.desc(), PublicInquiry.id.desc())
        .all()
    )
    out: dict[str, list[PublicInquiry]] = {}
    for row in rows:
        key = normalize_email(row.contact_reference)
        if key in wanted:
            out.setdefault(key, []).append(row)
    return out


def pending_users_by_email(db: Session, emails: list[str]) -> dict[str, User]:
    """正規化済みメールごとの承認待ちユーザ。"""
    wanted = {e for e in emails if e}
    if not wanted:
        return {}
    rows = (
        db.query(User)
        .filter(
            User.awaiting_admin_approval.is_(True),
            func.lower(func.trim(User.email)).in_(wanted),
        )
        .all()
    )
    out: dict[str, User] = {}
    for u in rows:
        key = normalize_email(u.email)
        if key:
            out[key] = u
    return out
