"""既存の全 player に対して body_disclose_to_{analyst,coach} を default ON で
seed し、同時に全 user の consent_required=True にして次回ログインで onboarding
popup を強制再表示するための 1 回限り seed スクリプト。

背景 / 2 つの操作:

(A) body_disclose_to_analyst / body_disclose_to_coach の opt-in seed
    β期間中の運用判断で、player の体組成データを analyst / coach にも
    default で見られる状態にしておく (= opt-out モデル)。
    各 player は ConditionPage の「体組成データの開示設定」セクションから
    いつでも toggle で OFF にできる。withdraw 履歴は UserConsent.withdrawn_at
    に残るので audit trail も維持される。

(B) consent_required = True を全 user に re-set
    TERMS v1.3 で SLA disclaimer / 体組成開示 / minor 等の重要追記を
    行ったため、既存ユーザにも明示再同意を求める。次回ログイン時に
    OnboardingConsentPage の popup が出る。必須項目に同意するまでログイン
    完了しない (= GDPR Art 7 material change 準拠)。

冪等性:
  - 既に最新が consent_given=True のユーザはスキップ (重複行を増やさない)。
  - スキップ件数と insert 件数をログ出力。

実行 (本番):
  ssh shuttle-scope "C:\\Users\\kiyus\\Desktop\\github\\shuttle-scope\\shuttlescope\\backend\\.venv\\Scripts\\python.exe \
    C:\\Users\\kiyus\\Desktop\\github\\shuttle-scope\\shuttlescope\\scripts\\seed_body_disclose_consents.py"
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

# repo の shuttlescope/ を sys.path に追加 (backend.* import 用)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.db.database import SessionLocal  # noqa: E402
from backend.db.models import User, UserConsent  # noqa: E402
from backend.routers.auth import (  # noqa: E402
    CURRENT_PRIVACY_VERSION,
    CURRENT_TERMS_VERSION,
)

OPT_IN_TYPES = ("body_disclose_to_analyst", "body_disclose_to_coach")


def main() -> int:
    db = SessionLocal()
    try:
        # (A) body_disclose seed: player_id を持つ user 対象
        player_users = db.query(User).filter(User.player_id.isnot(None)).all()
        print(f"[seed] (A) body_disclose target users: {len(player_users)}")

        now = datetime.utcnow()
        inserted = 0
        skipped = 0

        for user in player_users:
            for ctype in OPT_IN_TYPES:
                latest = (
                    db.query(UserConsent)
                    .filter(
                        UserConsent.user_id == user.id,
                        UserConsent.consent_type == ctype,
                    )
                    .order_by(UserConsent.given_at.desc())
                    .first()
                )
                already_on = (
                    latest is not None
                    and bool(latest.consent_given)
                    and latest.withdrawn_at is None
                )
                if already_on:
                    skipped += 1
                    continue
                rec = UserConsent(
                    user_id=user.id,
                    consent_type=ctype,
                    consent_given=True,
                    privacy_policy_version=CURRENT_PRIVACY_VERSION,
                    terms_version=CURRENT_TERMS_VERSION,
                    given_at=now,
                    withdrawn_at=None,
                    ip_address=None,
                    user_agent_hash="seed_script:body_disclose_default_opt_in",
                )
                db.add(rec)
                inserted += 1

        print(f"[seed] (A) inserted: {inserted}, skipped (already on): {skipped}")

        # (B) consent_required = True を全 user に再 set (次回ログイン popup 強制)
        all_users = db.query(User).all()
        re_consent = 0
        for u in all_users:
            if not getattr(u, "consent_required", False):
                u.consent_required = True
                re_consent += 1
        print(f"[seed] (B) consent_required flipped to True: {re_consent} (of {len(all_users)})")

        db.commit()
        print("[seed] done.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
