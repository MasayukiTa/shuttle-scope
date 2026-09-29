"""
重複選手をDBから削除するスクリプト。
同じ名前の選手が複数存在する場合、最も小さいIDを残してその他を削除する。
削除前に孤立する試合・セット・ラリーも合わせて削除する。

使い方:
  python scripts/dedup_players.py
  python scripts/dedup_players.py --dry-run  # 実際には削除しない
"""
import sys
import argparse
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from backend.db.database import engine
from backend.db.models import Player, Match


def main(dry_run: bool = False):
    with Session(engine) as db:
        # 全選手を名前でグループ化
        players = db.query(Player).order_by(Player.id).all()
        by_name: dict[str, list[Player]] = {}
        for p in players:
            by_name.setdefault(p.name, []).append(p)

        duplicates = {name: ps for name, ps in by_name.items() if len(ps) > 1}

        if not duplicates:
            print("重複なし。クリーンアップ不要です。")
            return

        print(f"重複選手 {len(duplicates)} 名を検出:")
        for name, ps in duplicates.items():
            ids = [p.id for p in ps]
            keep_id = min(ids)
            remove_ids = [i for i in ids if i != keep_id]
            print(f"  {name}: ID={ids} → ID={keep_id} を保持, {remove_ids} を削除")

            if dry_run:
                continue

            # 削除対象IDを参照している試合を保持IDに差し替えまたは削除
            for dup_id in remove_ids:
                matches_a = db.query(Match).filter(Match.player_a_id == dup_id).all()
                matches_b = db.query(Match).filter(Match.player_b_id == dup_id).all()

                for m in matches_a:
                    # 同一組み合わせが既に存在するなら削除、なければ差し替え
                    existing = db.query(Match).filter(
                        Match.player_a_id == keep_id,
                        Match.player_b_id == m.player_b_id,
                        Match.tournament == m.tournament,
                    ).first()
                    if existing:
                        print(f"    試合ID={m.id} は重複試合のため削除")
                        db.delete(m)
                    else:
                        m.player_a_id = keep_id
                        print(f"    試合ID={m.id}: player_a_id {dup_id} → {keep_id}")

                for m in matches_b:
                    existing = db.query(Match).filter(
                        Match.player_a_id == m.player_a_id,
                        Match.player_b_id == keep_id,
                        Match.tournament == m.tournament,
                    ).first()
                    if existing:
                        print(f"    試合ID={m.id} は重複試合のため削除")
                        db.delete(m)
                    else:
                        m.player_b_id = keep_id
                        print(f"    試合ID={m.id}: player_b_id {dup_id} → {keep_id}")

                db.flush()

                # 重複プレイヤー削除
                dup_player = db.get(Player, dup_id)
                if dup_player:
                    db.delete(dup_player)
                    print(f"    選手ID={dup_id} ({name}) を削除")

        if not dry_run:
            db.commit()
            print("\nクリーンアップ完了。")
        else:
            print("\n[DRY RUN] 変更は適用されていません。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
