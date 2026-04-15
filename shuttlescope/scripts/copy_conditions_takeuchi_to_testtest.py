"""
武内優幸 (player_id=107) の週次コンディションレコードを
testtest ユーザー (name='testtest') の player_id へ丸コピーするスクリプト。

実行方法:
    python -m scripts.copy_conditions_takeuchi_to_testtest

挙動:
- testtest プレイヤーが存在しなければ明示的にエラーで停止（作成はしない）。
- testtest の既存 Condition レコードは件数ログの後に削除してから再投入（冪等）。
- id, created_at, updated_at は新規生成（コピーしない）。
- match_id は NULL のまま（試合未紐付け）。
- 単一トランザクション + try/except + rollback。
"""
from __future__ import annotations

from sqlalchemy import inspect

from backend.db.database import SessionLocal
from backend.db.models import Condition, Player

SOURCE_PLAYER_ID = 107  # 武内優幸
TARGET_PLAYER_NAME = "testtest"

# コピー対象外のカラム（新規生成させる / コピーしない）
EXCLUDED_COLUMNS = {"id", "created_at", "updated_at", "player_id"}


def main() -> None:
    db = SessionLocal()
    try:
        # ターゲットプレイヤー lookup
        target = db.query(Player).filter(Player.name == TARGET_PLAYER_NAME).first()
        if target is None:
            raise SystemExit(
                f"[copy] player name='{TARGET_PLAYER_NAME}' が見つかりません。"
                " 事前に作成してから再実行してください。"
            )
        print(f"[copy] target player: id={target.id}, name={target.name}")

        # ソースレコード取得
        source_rows = (
            db.query(Condition)
            .filter(Condition.player_id == SOURCE_PLAYER_ID)
            .all()
        )
        print(
            f"[copy] source rows (player_id={SOURCE_PLAYER_ID}): {len(source_rows)} 件"
        )
        if not source_rows:
            print("[copy] ソースが 0 件のため何もせず終了します。")
            return

        # 既存ターゲットレコードの件数ログ + 削除（冪等化）
        existing_count = (
            db.query(Condition).filter(Condition.player_id == target.id).count()
        )
        print(
            f"[copy] target player_id={target.id} の既存 Condition 件数: {existing_count}"
        )
        if existing_count > 0:
            deleted = (
                db.query(Condition)
                .filter(Condition.player_id == target.id)
                .delete(synchronize_session=False)
            )
            print(f"[copy] 既存 {deleted} 件を削除しました（重複防止）")

        # Condition のカラム名一覧を取得
        mapper = inspect(Condition)
        column_names = [c.key for c in mapper.columns]

        # コピー生成
        new_rows = []
        for src in source_rows:
            data = {}
            for col in column_names:
                if col in EXCLUDED_COLUMNS:
                    continue
                data[col] = getattr(src, col)
            data["player_id"] = target.id
            # match_id は NULL のまま（試合未紐付け）
            if "match_id" in column_names:
                data["match_id"] = None
            new_rows.append(Condition(**data))

        db.bulk_save_objects(new_rows)
        db.commit()
        print(
            f"[copy] inserted {len(new_rows)} 件 into player_id={target.id}"
            f" (from player_id={SOURCE_PLAYER_ID})"
        )
    except SystemExit:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        print(f"[copy] エラー発生のため rollback しました: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
