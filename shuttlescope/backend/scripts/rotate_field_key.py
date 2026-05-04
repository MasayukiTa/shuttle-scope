"""SS_FIELD_ENCRYPTION_KEY のローテーションスクリプト (Phase A1 関連)。

使い方:
  1. backend を停止する
  2. 旧鍵を SS_FIELD_ENCRYPTION_KEY_OLD 環境変数に保管する
  3. 新鍵を SS_FIELD_ENCRYPTION_KEY 環境変数に設定する
  4. このスクリプトを実行する:
       python -m backend.scripts.rotate_field_key
  5. backend を起動する

動作:
  - DB 内の暗号化フィールド (Condition.injury_notes, general_comment) を
    旧鍵で復号 → 新鍵で再暗号化して保存し直す
  - "v1:" プレフィックスのない平文レコードはそのまま残す (新規暗号化はしない;
    そのレコードは次回更新時に新鍵で書かれる)

セキュリティ:
  - 必ず DB バックアップを取ってから実行すること
  - dry-run モード (--dry-run) で件数のみ確認可能
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# 暗号化対象テーブルとフィールドの宣言
TARGETS = [
    ("conditions", "injury_notes"),
    ("conditions", "general_comment"),
]

KEY_VERSION_PREFIX = "v1:"


def _decrypt_with(value: str, fernet: Fernet) -> Optional[str]:
    """Fernet で復号する。失敗時は None。"""
    if not value or not value.startswith(KEY_VERSION_PREFIX):
        return None  # 平文レコードはスキップ
    body = value[len(KEY_VERSION_PREFIX):]
    try:
        return fernet.decrypt(body.encode("ascii")).decode("utf-8")
    except (InvalidToken, Exception) as exc:
        logger.error("decrypt failed: %s", exc)
        return None


def _encrypt_with(value: str, fernet: Fernet) -> str:
    return KEY_VERSION_PREFIX + fernet.encrypt(value.encode("utf-8")).decode("ascii")


def main() -> int:
    parser = argparse.ArgumentParser(description="Field encryption key rotation")
    parser.add_argument("--dry-run", action="store_true",
                        help="件数のみ確認し、DB は変更しない")
    parser.add_argument("--old-key-env", default="SS_FIELD_ENCRYPTION_KEY_OLD",
                        help="旧鍵が入っている環境変数名")
    parser.add_argument("--new-key-env", default="SS_FIELD_ENCRYPTION_KEY",
                        help="新鍵が入っている環境変数名")
    args = parser.parse_args()

    old_key = os.environ.get(args.old_key_env, "").strip()
    new_key = os.environ.get(args.new_key_env, "").strip()
    if not old_key or not new_key:
        print(f"ERROR: 旧鍵 ({args.old_key_env}) と新鍵 ({args.new_key_env}) を両方設定してください")
        return 1
    if old_key == new_key:
        print("ERROR: 旧鍵と新鍵が同じです")
        return 1

    try:
        old_f = Fernet(old_key.encode("utf-8"))
        new_f = Fernet(new_key.encode("utf-8"))
    except Exception as exc:
        print(f"ERROR: 鍵の形式が不正です: {exc}")
        return 1

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))))
    from backend.db.database import SessionLocal
    from sqlalchemy import text

    total_rows = 0
    rotated = 0
    skipped_plain = 0
    failed = 0

    with SessionLocal() as db:
        for table, column in TARGETS:
            logger.info("Processing %s.%s ...", table, column)
            # nosec B608: table/column come from TARGETS constant (allow-list), not user input.
            rows = db.execute(text(f"SELECT id, {column} FROM {table} WHERE {column} IS NOT NULL")).fetchall()  # noqa: S608
            for r in rows:
                total_rows += 1
                rid = r[0]
                v = r[1]
                if not isinstance(v, str) or not v.startswith(KEY_VERSION_PREFIX):
                    skipped_plain += 1
                    continue
                plaintext = _decrypt_with(v, old_f)
                if plaintext is None:
                    failed += 1
                    continue
                new_ct = _encrypt_with(plaintext, new_f)
                if not args.dry_run:
                    # nosec B608: identifiers come from TARGETS allow-list; values are bound parameters.
                    db.execute(  # noqa: S608
                        text(f"UPDATE {table} SET {column} = :v WHERE id = :id"),
                        {"v": new_ct, "id": rid},
                    )
                rotated += 1
            if not args.dry_run:
                db.commit()

    print(f"\n=== ローテ結果 ===")
    print(f"  total_rows:     {total_rows}")
    print(f"  rotated:        {rotated}")
    print(f"  skipped_plain:  {skipped_plain} (まだ暗号化されていないレコード)")
    print(f"  failed:         {failed} (旧鍵で復号失敗)")
    if args.dry_run:
        print("\n  (dry-run モード: DB は変更されていません)")
    else:
        print("\n  ✅ ローテ完了。backend を再起動してください。")

    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
