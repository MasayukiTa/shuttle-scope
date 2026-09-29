"""山田太郎のファーストリターン解析用テストデータ生成スクリプト

generate_test_data.py の既存データに追加で、
多様な試合結果・大会レベルを持つシングルス試合を追加する。

目的:
  - FirstReturnAnalysis (stroke_num=2) に十分なサンプルを確保
  - 大会レベル: IC, IS, SJL, 全日本, 国内 すべてを含む
  - 試合結果: 勝ち/負けバランス良く
  - ファーストリターン（レシーブ時 stroke_num=2）ゾーン着地に
    偏りをつけて分析が意味を持つようにする
"""
import sys
import os
import random
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.db.database import SessionLocal, create_tables
from backend.db.models import Player, Match, GameSet, Rally, Stroke

random.seed(2026)

SHOT_TYPES = [
    "short_service", "long_service", "net_shot", "clear", "push_rush",
    "smash", "defensive", "drive", "lob", "drop", "cross_net", "slice",
    "around_head", "flick", "half_smash", "block", "other",
]
SHOT_WEIGHTS = [0.09, 0.03, 0.11, 0.10, 0.06, 0.11, 0.07, 0.08, 0.07, 0.07,
                0.04, 0.03, 0.04, 0.02, 0.03, 0.02, 0.03]

ZONES = ["BL", "BC", "BR", "ML", "MC", "MR", "NL", "NC", "NR"]

# ファーストリターン着地ゾーン: BL/ML/NL 方向に偏らせる（分析で差が出るように）
RETURN_ZONE_WEIGHTS = {
    "BL": 0.18, "BC": 0.08, "BR": 0.06,
    "ML": 0.16, "MC": 0.12, "MR": 0.10,
    "NL": 0.14, "NC": 0.10, "NR": 0.06,
}

def rnd_shot():
    return random.choices(SHOT_TYPES, weights=SHOT_WEIGHTS, k=1)[0]

def rnd_zone():
    return random.choice(ZONES) if random.random() < 0.82 else None

def rnd_return_zone():
    """ファーストリターン用: 偏りを持つゾーン選択"""
    zones = list(RETURN_ZONE_WEIGHTS.keys())
    weights = list(RETURN_ZONE_WEIGHTS.values())
    return random.choices(zones, weights=weights, k=1)[0]

def rnd_coord():
    if random.random() < 0.82:
        return round(random.uniform(0.05, 0.95), 3), round(random.uniform(0.05, 0.95), 3)
    return None, None

def rnd_quality():
    return random.choices(
        ["excellent", "good", "neutral", "poor"],
        weights=[0.12, 0.38, 0.35, 0.15]
    )[0]


def generate_strokes(db, rally_id: int, rally_length: int,
                     player_role: str, is_receiver: bool):
    """ストローク生成。is_receiver=True の場合、stroke_num=2 にファーストリターン着地ゾーンを設定"""
    for i in range(1, rally_length + 1):
        # is_receiver=True → 偶数打（2,4,6...）が自分、i%2==0
        # is_receiver=False → 奇数打（1,3,5...）が自分、i%2==1
        is_player_stroke = (i % 2 == (0 if is_receiver else 1))
        player = player_role if is_player_stroke else (
            "player_b" if player_role == "player_a" else "player_a"
        )

        shot_type = rnd_shot()
        if i == 1:
            shot_type = random.choice(["short_service", "short_service", "long_service"])
        elif i == 2 and is_receiver:
            # ファーストリターンのショット種別に偏りをつける
            shot_type = random.choices(
                ["net_shot", "clear", "drive", "push_rush", "lob", "drop"],
                weights=[0.22, 0.20, 0.18, 0.15, 0.14, 0.11],
                k=1
            )[0]

        hx, hy = rnd_coord()
        lx, ly = rnd_coord()

        # ファーストリターン (stroke_num=2, receiver) の着地ゾーンに偏り
        if i == 2 and is_receiver:
            land_zone = rnd_return_zone()
        else:
            land_zone = rnd_zone()

        stroke = Stroke(
            rally_id=rally_id,
            stroke_num=i,
            player=player,
            shot_type=shot_type,
            shot_quality=rnd_quality(),
            hit_x=hx, hit_y=hy,
            land_x=lx, land_y=ly,
            hit_zone=rnd_zone(),
            land_zone=land_zone,
            is_backhand=random.random() < 0.22,
            is_around_head=random.random() < 0.06,
            is_cross=random.random() < 0.22,
        )
        db.add(stroke)


def generate_set(db, match_id: int, set_num: int, player_role: str, a_wins: bool):
    score_a = 21 if a_wins else random.randint(10, 20)
    score_b = random.randint(10, 20) if a_wins else 21
    # デュース
    if score_a >= 20 and score_b >= 20:
        if a_wins:
            score_a = 22 + random.randint(0, 2); score_b = score_a - 2
        else:
            score_b = 22 + random.randint(0, 2); score_a = score_b - 2

    game_set = GameSet(
        match_id=match_id, set_num=set_num,
        winner="player_a" if a_wins else "player_b",
        score_a=score_a, score_b=score_b,
        is_deuce=(score_a >= 20 and score_b >= 20),
        duration_min=round(random.uniform(18, 38), 1),
    )
    db.add(game_set); db.flush()

    points = ["a"] * score_a + ["b"] * score_b
    random.shuffle(points)
    current_a = current_b = 0
    server = "player_a"

    for idx, pw in enumerate(points):
        rally_winner = "player_a" if pw == "a" else "player_b"
        rally_length = random.randint(3, 16)
        is_receiver = (server != player_role)

        rally = Rally(
            set_id=game_set.id,
            rally_num=idx + 1,
            server=server,
            winner=rally_winner,
            end_type=random.choices(
                ["ace", "forced_error", "unforced_error", "net", "out"],
                weights=[0.07, 0.33, 0.30, 0.18, 0.12]
            )[0],
            rally_length=rally_length,
            duration_sec=round(rally_length * random.uniform(0.8, 1.9), 1),
            score_a_after=current_a + (1 if pw == "a" else 0),
            score_b_after=current_b + (1 if pw == "b" else 0),
            is_deuce=(current_a >= 20 and current_b >= 20),
        )
        db.add(rally); db.flush()

        if pw == "a": current_a += 1
        else: current_b += 1

        generate_strokes(db, rally.id, rally_length, player_role, is_receiver)
        server = rally_winner

    return game_set


def generate_match(db, yamada_id: int, opponent_id: int,
                   tournament: str, level: str, match_date: date,
                   result: str):
    a_wins = result == "win"
    match = Match(
        tournament=tournament,
        tournament_level=level,
        tournament_grade=None,
        round=random.choice(["1回戦", "2回戦", "準々決勝", "準決勝", "決勝"]),
        date=match_date,
        format="singles",
        player_a_id=yamada_id,
        player_b_id=opponent_id,
        result=result,
        annotation_status="complete",
        annotation_progress=1.0,
    )
    db.add(match); db.flush()

    if a_wins:
        set_results = [True, True] if random.random() < 0.55 else [True, False, True]
    else:
        set_results = [False, False] if random.random() < 0.55 else [False, True, False]

    for i, aw in enumerate(set_results, 1):
        generate_set(db, match.id, i, "player_a", aw)

    sets = db.query(GameSet).filter(GameSet.match_id == match.id).order_by(GameSet.set_num).all()
    match.final_score = ", ".join(f"{s.score_a}-{s.score_b}" for s in sets)
    return match


# 追加する試合定義: (大会名, レベル, 日付オフセット, 結果)
MATCH_PLAN = [
    # IC (国際)
    ("全英オープン2025",         "IC",    date(2025, 3, 10), "win"),
    ("全英オープン2025",         "IC",    date(2025, 3, 11), "loss"),
    ("バルセロナ国際2025",       "IC",    date(2025, 5, 15), "win"),
    # IS
    ("韓国オープン2025",         "IS",    date(2025, 4, 20), "win"),
    ("タイオープン2025",         "IS",    date(2025, 7, 8),  "loss"),
    ("インドオープン2025",       "IS",    date(2025, 9, 3),  "win"),
    # SJL
    ("スーパージャパンリーグ春", "SJL",   date(2025, 4, 5),  "win"),
    ("スーパージャパンリーグ秋", "SJL",   date(2025, 9, 20), "loss"),
    # 全日本
    ("全日本総合選手権2025",     "全日本", date(2025, 11, 15), "win"),
    ("全日本総合選手権2025",     "全日本", date(2025, 11, 16), "loss"),
    # 国内
    ("関東オープン2025",         "国内",  date(2025, 6, 1),  "win"),
    ("東日本選手権2025",         "国内",  date(2025, 8, 10), "win"),
    ("地域リーグA",              "国内",  date(2025, 10, 1), "loss"),
]


def main():
    create_tables()
    db = SessionLocal()
    try:
        yamada = db.query(Player).filter(Player.name == "山田太郎").first()
        sato   = db.query(Player).filter(Player.name == "佐藤次郎").first()
        suzuki = db.query(Player).filter(Player.name == "鈴木三郎").first()

        if not all([yamada, sato, suzuki]):
            print("既存の選手データが見つかりません。先に generate_test_data.py を実行してください。")
            return

        # 追加の対戦相手
        hayashi = db.query(Player).filter(Player.name == "林六郎").first()
        if not hayashi:
            print("林六郎が見つかりません。先に generate_doubles_data.py を実行してください。")
            return

        opponents = [sato, suzuki, hayashi]
        print(f"ファーストリターン解析用データを追加中（{len(MATCH_PLAN)}試合）...")

        for i, (tournament, level, match_date, result) in enumerate(MATCH_PLAN):
            opponent = opponents[i % len(opponents)]
            m = generate_match(db, yamada.id, opponent.id, tournament, level, match_date, result)
            print(f"  [{level}] {tournament} vs {opponent.name}: {result} (ID={m.id})")

        db.commit()

        total_rallies = db.query(Rally).count()
        total_strokes = db.query(Stroke).count()
        print(f"\n完了!")
        print(f"  総ラリー数:    {total_rallies}")
        print(f"  総ストローク数: {total_strokes}")

    except Exception as e:
        db.rollback()
        print(f"エラー: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
