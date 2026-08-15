"""users.totp_secret の平文を暗号化する (migration 0048 のあとに実行する)。

なぜ Alembic と分けるか:
  migration は ss_migration ロールで走り、その環境に SS_FIELD_ENCRYPTION_KEY が
  あるとは限らない。鍵の無い環境で暗号化すると field_crypto はフォールバックして
  平文のまま書き戻し、「暗号化済み」と誤認される。アプリと同じ環境・同じ鍵で
  実行する必要がある。

なぜ raw SQL か:
  ORM 経由で読むと EncryptedText が透過的に復号してしまい、DB に入っている実体が
  平文なのか暗号文なのか判別できない。判別が本スクリプトの中心なので raw SQL で扱う。

安全策:
  - 鍵が使えない (未設定 / 不正 / 往復不能) なら何もせず終了
  - "v1:" 前置の有無だけでなく **実際に復号できるか** で判定する
    (別の鍵で暗号化された値も前置は同じなので、前置だけ見ると二重暗号化する)
  - 復号できない "v1:" 値が 1 件でもあれば中断 (鍵の取り違えの可能性)
  - 1 トランザクションで実行し、WHERE に現在値を含めて同時更新を上書きしない
  - --dry-run で件数だけ確認できる

使い方:
    python backend/scripts/encrypt_totp_secrets.py --dry-run
    python backend/scripts/encrypt_totp_secrets.py
    python backend/scripts/encrypt_totp_secrets.py --decrypt   # 復旧用 (要アプリ停止)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import text  # noqa: E402

from backend.db.database import SessionLocal  # noqa: E402
from backend.utils.field_crypto import (  # noqa: E402
    FieldKeyError,
    _KEY_VERSION_PREFIX,
    can_decrypt,
    decrypt_field,
    encrypt_field,
    verify_key_matches_stored_data,
)


def _classify(rows):
    """(暗号化済み, 平文, 復号不能) に分ける。"""
    encrypted, plaintext, undecryptable = [], [], []
    for uid, value in rows:
        if value is None or value == "":
            continue
        if value.startswith(_KEY_VERSION_PREFIX):
            (encrypted if can_decrypt(value) else undecryptable).append((uid, value))
        else:
            plaintext.append((uid, value))
    return encrypted, plaintext, undecryptable


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="変更せず件数だけ表示")
    ap.add_argument("--decrypt", action="store_true",
                    help="暗号文を平文に戻す (ダウングレード用。アプリを止めてから)")
    args = ap.parse_args()

    session = SessionLocal()
    try:
        # 「鍵が読める」だけでは不十分。別の鍵でも往復は成功するため、DB の
        # カナリアで *この DB の鍵か* を確認してから書き込む。これを飛ばすと
        # 平文を別鍵で暗号化し、鍵が混在した復旧困難な状態を作る。
        try:
            verify_key_matches_stored_data(session)
        except FieldKeyError as exc:
            print(f"[encrypt_totp_secrets] 中断: {exc}")
            print("  鍵を復元してから再実行してください。新しい鍵を生成してはいけません。")
            return 2

        rows = session.execute(text(
            "SELECT id, totp_secret FROM users WHERE totp_secret IS NOT NULL"
        )).fetchall()
        encrypted, plaintext, undecryptable = _classify([(r[0], r[1]) for r in rows])

        print(f"[encrypt_totp_secrets] 非NULL {len(rows)} 件: "
              f"暗号化済み {len(encrypted)} / 平文 {len(plaintext)} / "
              f"復号不能 {len(undecryptable)}")

        if undecryptable:
            print("  中断: 現在の鍵で復号できない 'v1:' 値があります "
                  f"(user_id={[u for u, _ in undecryptable]})。"
                  "鍵の取り違えの可能性があるため、何も変更しません。")
            return 3

        targets = encrypted if args.decrypt else plaintext
        verb = "復号" if args.decrypt else "暗号化"
        if not targets:
            print(f"  {verb}対象なし。何もしません。")
            return 0
        if args.dry_run:
            print(f"  dry-run: {len(targets)} 件が{verb}対象 (user_id="
                  f"{[u for u, _ in targets]})")
            return 0

        # ── 書く前に全件を変換して検証する ──────────────────────────────
        # commit 後に検証しても、壊れた値を書いた事実は取り消せない。
        # 特に --decrypt では、復号失敗のセンチネルで復旧可能な暗号文を
        # 上書きしてしまうと元に戻せない。
        planned: list[tuple[int, str, str]] = []
        for uid, current in targets:
            new_value = decrypt_field(current) if args.decrypt else encrypt_field(current)
            if not new_value or new_value == current:
                print(f"  中断: user_id={uid} の値が変換されませんでした "
                      "(鍵のフォールバックの可能性)。何も変更していません。")
                return 4
            if args.decrypt:
                if new_value.startswith("[ENCRYPTED:") or new_value.startswith(
                        _KEY_VERSION_PREFIX):
                    print(f"  中断: user_id={uid} の復号に失敗しました。"
                          "何も変更していません。")
                    return 4
            else:
                # 暗号化した結果が復号できることまで確認してから書く
                if not can_decrypt(new_value):
                    print(f"  中断: user_id={uid} の暗号文を復号できません。"
                          "何も変更していません。")
                    return 4
            planned.append((uid, current, new_value))

        changed = 0
        for uid, current, new_value in planned:
            # 現在値を条件に含め、実行中に MFA 設定が変わった行は触らない
            res = session.execute(
                text("UPDATE users SET totp_secret = :new "
                     "WHERE id = :uid AND totp_secret = :cur"),
                {"new": new_value, "uid": uid, "cur": current},
            )
            if res.rowcount != 1:
                print(f"  中断: user_id={uid} が実行中に変更されました。")
                session.rollback()
                return 5
            changed += 1
        session.commit()
        print(f"  {verb}完了: {changed} 件")

        # 事後検証 (診断用): 書く前に検証済みだが、実際の DB 状態も読み直す
        rows2 = session.execute(text(
            "SELECT id, totp_secret FROM users WHERE totp_secret IS NOT NULL"
        )).fetchall()
        enc2, plain2, bad2 = _classify([(r[0], r[1]) for r in rows2])
        print(f"  検証: 暗号化済み {len(enc2)} / 平文 {len(plain2)} / 復号不能 {len(bad2)}")
        if args.decrypt:
            ok = not enc2 and not bad2
        else:
            ok = not plain2 and not bad2
        if not ok:
            print("  警告: 期待した状態になっていません。上の内訳を確認してください。")
            return 6
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
