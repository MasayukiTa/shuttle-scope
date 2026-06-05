"""LLM 専用ユーザを作成/更新する admin シードスクリプト (運用者が本番で実行する)。

使い方 (shuttlescope/ で venv python から):
    LLM_USER_PASSWORD='********' backend\\.venv\\Scripts\\python scripts/create_llm_user.py --username LLM

設計:
- role='llm' を付与する。analyst/coach/player ではないため、role でガードされた
  バドミントン系エンドポイントは拒否する (= LLM 専用)。
  ※ ただし「全エンドポイントが role='llm' を確実に弾く」ことは別途検証が必要。
- page_access に 'llm' を付与し、汎用 LLM チャット (/#/llm) のみ利用可にする。
- consent_required=False / awaiting_admin_approval=False (テスト用にゲートを外す)。
- パスワードは **環境変数 LLM_USER_PASSWORD から受け取り**、bcrypt でハッシュ化して保存する
  (引数やソースに平文を残さない)。
- 冪等: 既存ユーザがいれば role / hash / grant を更新する。
"""
import argparse
import os
import sys

# repo/shuttlescope を import path に追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bcrypt  # noqa: E402

from backend.db.database import SessionLocal  # noqa: E402
from backend.db.models import PlayerPageAccess, User  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--username", required=True)
    ap.add_argument("--role", default="llm")
    args = ap.parse_args()

    pw = os.environ.get("LLM_USER_PASSWORD")
    if not pw:
        print("ERROR: set LLM_USER_PASSWORD env (平文をコマンド履歴に残さないこと)")
        return 2
    hashed = bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    with SessionLocal() as db:
        u = db.query(User).filter(User.username == args.username).first()
        if u is None:
            u = User(username=args.username, role=args.role, display_name=args.username,
                     hashed_credential=hashed, consent_required=False,
                     awaiting_admin_approval=False)
            db.add(u); db.flush()
            action = "created"
        else:
            u.role = args.role
            u.hashed_credential = hashed
            u.consent_required = False
            u.awaiting_admin_approval = False
            action = "updated"

        # 'llm' grant を冪等付与。badminton grant は付けない。
        exists = (
            db.query(PlayerPageAccess)
            .filter(PlayerPageAccess.page_key == "llm", PlayerPageAccess.user_id == u.id)
            .first()
        )
        if not exists:
            db.add(PlayerPageAccess(page_key="llm", user_id=u.id))
        db.commit()
        print(f"{action}: id={u.id} username={u.username} role={u.role} grants=[llm] (badminton 無し)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
