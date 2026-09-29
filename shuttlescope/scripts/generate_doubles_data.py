"""追加ダブルステストデータ生成スクリプト
既存DBに山田太郎のダブルス試合を3試合追加する。

生成内容:
- ダブルス試合3試合（パートナー: 田中四郎）
  - Match A: 山田/田中 vs 佐藤/鈴木, 混合ダブルス, IC, 勝ち
  - Match B: 山田/田中 vs 別ペア, 男子ダブルス, SJL, 負け
  - Match C: 山田/田中 vs 佐藤/鈴木, 混合ダブルス, 国内, 勝ち
"""
import sys
import os
import random
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.db.database import SessionLocal, create_tables
from backend.db.models import Player, Match, GameSet, Rally, Stroke

random.seed(99)

SHOT_TYPES = [
    "short_service", "long_service", "net_shot", "clear", "push_rush",
    "smash", "defensive", "drive", "lob", "drop", "cross_net", "slice",
    "around_head", "flick", "half_smash", "block", "other",
]
SHOT_WEIGHTS = [0.08, 0.03, 0.10, 0.10, 0.05, 0.12, 0.08, 0.08, 0.07, 0.07, 0.04, 0.03, 0.04, 0.02, 0.03, 0.03, 0.03]
ZONES = ["BL", "BC", "BR", "ML", "MC", "MR", "NL", "NC", "NR"]


def rnd_shot(): return random.choices(SHOT_TYPES, weights=SHOT_WEIGHTS, k=1)[0]
def rnd_zone(): return random.choice(ZONES) if random.random() < 0.8 else None
def rnd_coord(): return (round(random.uniform(0.1, 0.9), 3), round(random.uniform(0.1, 0.9), 3)) if random.random() < 0.8 else (None, None)
def rnd_quality(): return random.choices(["excellent", "good", "neutral", "poor"], weights=[0.15, 0.35, 0.35, 0.15])[0]


def generate_doubles_strokes(db, rally_id: int, rally_length: int, roles: list[str]):
    """ダブルスのストロークを生成する（4人のロールから選択）"""
    strokes = []
    for i in range(1, rally_length + 1):
        # 奇数ストローク: A側ペア（roles[0], roles[2]）/ 偶数: B側ペア（roles[1], roles[3]）
        if i % 2 == 1:
            player = roles[0] if random.random() < 0.55 else roles[2]
        else:
            player = roles[1] if random.random() < 0.55 else roles[3]

        shot_type = rnd_shot()
        if i == 1:
            shot_type = random.choice(["short_service", "short_service", "long_service"])

        hx, hy = rnd_coord()
        lx, ly = rnd_coord()

        stroke = Stroke(
            rally_id=rally_id,
            stroke_num=i,
            player=player,
            shot_type=shot_type,
            shot_quality=rnd_quality(),
            hit_x=hx, hit_y=hy,
            land_x=lx, land_y=ly,
            hit_zone=rnd_zone(),
            land_zone=rnd_zone(),
            is_backhand=random.random() < 0.25,
            is_around_head=random.random() < 0.05,
            is_cross=random.random() < 0.2,
        )
        strokes.append(stroke)
    return strokes


def generate_doubles_set(db, match_id: int, set_num: int, a_wins: bool):
    score_a = 21 if a_wins else random.randint(12, 20)
    score_b = random.randint(12, 20) if a_wins else 21

    is_deuce = score_a >= 20 and score_b >= 20
    if is_deuce:
        if a_wins:
            score_a = 22 + random.randint(0, 2); score_b = score_a - 2
        else:
            score_b = 22 + random.randint(0, 2); score_a = score_b - 2

    game_set = GameSet(
        match_id=match_id, set_num=set_num,
        winner="player_a" if a_wins else "player_b",
        score_a=score_a, score_b=score_b,
        is_deuce=is_deuce,
        duration_min=round(random.uniform(20, 40), 1),
    )
    db.add(game_set); db.flush()

    points = ["a"] * score_a + ["b"] * score_b
    random.shuffle(points)
    current_a = current_b = 0
    server = "player_a"
    roles = ["player_a", "player_b", "partner_a", "partner_b"]

    for idx, pw in enumerate(points):
        rally_winner = "player_a" if pw == "a" else "player_b"
        rally_length = random.randint(4, 14)

        rally = Rally(
            set_id=game_set.id,
            rally_num=idx + 1,
            server=server,
            winner=rally_winner,
            end_type=random.choices(
                ["ace", "forced_error", "unforced_error", "net_error", "winner"],
                weights=[0.08, 0.35, 0.27, 0.15, 0.15]
            )[0],
            rally_length=rally_length,
            duration_sec=round(rally_length * random.uniform(0.9, 1.8), 1),
            score_a_after=current_a + (1 if pw == "a" else 0),
            score_b_after=current_b + (1 if pw == "b" else 0),
            is_deuce=(current_a >= 20 and current_b >= 20),
        )
        db.add(rally); db.flush()

        if pw == "a": current_a += 1
        else: current_b += 1

        for stroke in generate_doubles_strokes(db, rally.id, rally_length, roles):
            db.add(stroke)

        server = rally_winner

    return game_set


def generate_doubles_match(db, player_a_id, player_b_id, partner_a_id, partner_b_id,
                            tournament, level, match_date, result, fmt="mixed_doubles"):
    a_wins = result == "win"
    match = Match(
        tournament=tournament, tournament_level=level,
        tournament_grade=None,
        round=random.choice(["1回戦", "2回戦", "準々決勝", "準決勝"]),
        date=match_date, format=fmt,
        player_a_id=player_a_id, player_b_id=player_b_id,
        partner_a_id=partner_a_id, partner_b_id=partner_b_id,
        result=result,
        annotation_status="complete", annotation_progress=1.0,
    )
    db.add(match); db.flush()

    if a_wins:
        set_results = [True, True] if random.random() < 0.5 else [True, False, True]
    else:
        set_results = [False, False] if random.random() < 0.5 else [False, True, False]

    for i, aw in enumerate(set_results, 1):
        generate_doubles_set(db, match.id, i, aw)

    sets = db.query(GameSet).filter(GameSet.match_id == match.id).order_by(GameSet.set_num).all()
    match.final_score = ", ".join(f"{s.score_a}-{s.score_b}" for s in sets)
    return match


def main():
    create_tables()
    db = SessionLocal()
    try:
        # 既存選手を取得
        yamada = db.query(Player).filter(Player.name == "山田太郎").first()
        sato   = db.query(Player).filter(Player.name == "佐藤次郎").first()
        suzuki = db.query(Player).filter(Player.name == "鈴木三郎").first()
        tanaka = db.query(Player).filter(Player.name == "田中四郎").first()

        if not all([yamada, sato, suzuki, tanaka]):
            print("既存の選手データが見つかりません。先に generate_test_data.py を実行してください。")
            return

        # 新しい対戦相手2人（ダブルス専用）
        goto = db.query(Player).filter(Player.name == "後藤五郎").first()
        if not goto:
            goto = Player(name="後藤五郎", name_en="Goro Goto", team="相手チームC",
                          nationality="JPN", dominant_hand="R", is_target=False)
            hayashi = Player(name="林六郎", name_en="Rokuro Hayashi", team="相手チームC",
                             nationality="JPN", dominant_hand="L", is_target=False)
            db.add_all([goto, hayashi]); db.flush()
        else:
            hayashi = db.query(Player).filter(Player.name == "林六郎").first()

        print("ダブルス試合データを追加中...")

        # Match A: 山田/田中 vs 佐藤/鈴木, 混合ダブルス, IC, 勝ち
        ma = generate_doubles_match(
            db, yamada.id, sato.id, tanaka.id, suzuki.id,
            "ICダブルス追加2025A", "IC", date(2025, 6, 10), "win", "mixed_doubles"
        )
        print(f"  Match A (ID={ma.id}): 山田/田中 vs 佐藤/鈴木 [IC, 勝ち]")

        # Match B: 山田/田中 vs 後藤/林, 男子ダブルス, SJL, 負け
        mb = generate_doubles_match(
            db, yamada.id, goto.id, tanaka.id, hayashi.id,
            "SJLダブルス追加2025B", "SJL", date(2025, 8, 20), "loss", "mens_doubles"
        )
        print(f"  Match B (ID={mb.id}): 山田/田中 vs 後藤/林 [SJL, 負け]")

        # Match C: 山田/田中 vs 佐藤/鈴木, 混合ダブルス, 国内, 勝ち
        mc = generate_doubles_match(
            db, yamada.id, sato.id, tanaka.id, suzuki.id,
            "国内ダブルス追加2025C", "国内", date(2025, 10, 5), "win", "mixed_doubles"
        )
        print(f"  Match C (ID={mc.id}): 山田/田中 vs 佐藤/鈴木 [国内, 勝ち]")

        db.commit()

        total_rallies = db.query(Rally).count()
        total_strokes = db.query(Stroke).count()
        print(f"\n追加完了!")
        print(f"  総ラリー数: {total_rallies}")
        print(f"  総ストローク数: {total_strokes}")

    except Exception as e:
        db.rollback()
        print(f"エラー: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
