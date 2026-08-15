"""MFA リカバリコードを再発行して控えを保存する。

なぜ必要か:
  リカバリコードは平文を DB に持たない (SHA-256 のみ)。発行時に控えなければ
  二度と取得できず、残数 0 のまま TOTP が使えなくなると復旧手段が無くなる。
  totp_secret の暗号化バックフィルなど、MFA に触れる作業の前には必ず
  未使用コードがあることを確認すること。

前提:
  TOTP が **今通る** こと。このスクリプトは現在の TOTP コードで認証する。
  (TOTP が通らなくなってからでは再発行できない = 事前にやる意味がここにある)

使い方 (アプリと同じホストで実行):
    python backend/scripts/issue_recovery_codes.py --username adminTakeuchi_ --code 123456

  --code は認証アプリに表示されている 6 桁。
  発行された 10 本は画面に出さず、指定ファイル (既定: ./recovery_codes.txt) へ
  所有者のみ読める形で書き出す。中身を安全な場所へ移したらファイルを削除すること。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.db.database import SessionLocal  # noqa: E402
from backend.db.models import User  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--username", required=True, help="対象ユーザー名")
    ap.add_argument("--code", required=True, help="認証アプリの現在の6桁コード")
    ap.add_argument("--out", default="recovery_codes.txt", help="控えの保存先")
    args = ap.parse_args()

    # ルータ側と同じ実装を使う (発行ロジックを二重に持たない)
    from backend.routers.auth import (
        _issue_recovery_codes,
        _totp_secret_usable,
        _verify_totp,
    )

    session = SessionLocal()
    try:
        user = session.query(User).filter(User.username == args.username).one_or_none()
        if user is None:
            print(f"中断: ユーザー {args.username!r} が見つかりません")
            return 2
        if not user.totp_enabled or not user.totp_secret:
            print("中断: このユーザーは MFA が有効化されていません")
            return 3
        if not _totp_secret_usable(user.totp_secret):
            print("中断: 保存されている TOTP secret を復号できません "
                  "(鍵の問題)。SS_FIELD_ENCRYPTION_KEY を確認してください。")
            return 4
        if not _verify_totp(user.totp_secret, args.code):
            print("中断: コードが一致しません。認証アプリの表示を確認して、"
                  "30 秒の切り替わり直後にもう一度実行してください。")
            return 5

        codes = _issue_recovery_codes(session, user.id)

        out = Path(args.out).resolve()
        out.write_text(
            f"ShuttleScope MFA リカバリコード\n"
            f"user: {args.username}\n"
            f"発行: {datetime.now():%Y-%m-%d %H:%M}\n\n"
            + "\n".join(codes)
            + "\n\n"
            "・1 本につき 1 回だけ使えます。\n"
            "・認証アプリが使えないとき、ログイン画面の\n"
            "  「認証アプリが使えない場合」からこのコードを入力します。\n"
            "・再発行すると以前のコードは全て無効になります。\n"
            "・安全な場所へ移したら、このファイルは削除してください。\n",
            encoding="utf-8",
        )
        # 所有者のみ読める ACL にする
        subprocess.run(["icacls", str(out), "/inheritance:r"],
                       capture_output=True, text=True)
        who = os.environ.get("USERNAME", "")
        if who:
            subprocess.run(["icacls", str(out), "/grant:r", f"{who}:F"],
                           capture_output=True, text=True)

        print(f"発行しました: {len(codes)} 本")
        print(f"控え: {out}")
        print("  ※ コードは画面に出していません。上記ファイルを開いて保管してください。")
        print("  ※ 保管後、このファイルは削除してください。")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
