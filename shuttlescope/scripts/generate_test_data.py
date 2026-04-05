"""テストデータ生成スクリプト
5試合分の完全なアノテーションデータを生成してDBに投入する。

生成内容:
- 3選手: 山田太郎 (解析対象), 佐藤次郎, 鈴木三郎
- 1パートナー: 田中四郎 (ダブルス用)
- 5試合:
  - Match1: 山田 vs 佐藤, シングルス, IC, 勝ち
  - Match2: 山田 vs 佐藤, シングルス, SJL, 負け
  - Match3: 山田 vs 鈴木, シングルス, 国内, 勝ち
  - Match4: 山田/田中 vs 佐藤/鈴木, 混合ダブルス, IC, 勝ち
  - Match5: 山田 vs 鈴木, シングルス, IC, 負け
"""
import sys
import os
import random
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.db.database import SessionLocal, create_tables
from backend.db.models import Player, Match, GameSet, Rally, Stroke

# 乱数シード固定（再現性確保）
random.seed(42)

SHOT_TYPES = [
    "short_service", "long_service", "net_shot", "clear", "push_rush",
    "smash", "defensive", "drive", "lob", "drop", "cross_net", "slice",
    "around_head", "flick", "half_smash", "block", "other",
]

# ショット種別の出現確率分布（リアルに近い分布）
SHOT_WEIGHTS = [
    0.08,  # short_service
    0.03,  # long_service
    0.10,  # net_shot
    0.10,  # clear
    0.05,  # push_rush
    0.12,  # smash
    0.08,  # defensive
    0.08,  # drive
    0.07,  # lob
    0.07,  # drop
    0.04,  # cross_net
    0.03,  # slice
    0.04,  # around_head
    0.02,  # flick
    0.03,  # half_smash
    0.03,  # block
    0.03,  # other
]

# ゾーンリスト
ZONES = ["BL", "BC", "BR", "ML", "MC", "MR", "NL", "NC", "NR"]

def random_shot_type() -> str:
    return random.choices(SHOT_TYPES, weights=SHOT_WEIGHTS, k=1)[0]

def random_zone() -> str | None:
    """80%の確率でゾーンを返す"""
    if random.random() < 0.8:
        return random.choice(ZONES)
    return None

def random_coord() -> tuple[float | None, float | None]:
    """80%の確率で座標を返す"""
    if random.random() < 0.8:
        return round(random.uniform(0.1, 0.9), 3), round(random.uniform(0.1, 0.9), 3)
    return None, None

def random_shot_quality() -> str:
    return random.choices(["excellent", "good", "neutral", "poor"], weights=[0.15, 0.35, 0.35, 0.15])[0]

def generate_rally_strokes(
    db,
    rally_id: int,
    player_a_role: str,
    player_b_role: str,
    rally_length: int,
    player_a_wins: bool,
    is_doubles: bool = False,
    partner_a_role: str = None,
    partner_b_role: str = None,
) -> list[Stroke]:
    """ラリーのストロークリストを生成する"""
    strokes = []
    # 最初のストローク（サーブ）は player_a_role
    # 2打目以降は交互に打つ
    # ダブルスの場合は partner も使用

    for i in range(1, rally_length + 1):
        # ストロークを打つプレイヤーを決定
        if is_doubles:
            if i % 2 == 1:
                # A側: player_a または partner_a
                player = player_a_role if random.random() < 0.55 else (partner_a_role or player_a_role)
            else:
                # B側: player_b または partner_b
                player = player_b_role if random.random() < 0.55 else (partner_b_role or player_b_role)
        else:
            player = player_a_role if i % 2 == 1 else player_b_role

        shot_type = random_shot_type()
        # 最初はサーブ系
        if i == 1:
            shot_type = random.choice(["short_service", "long_service", "short_service"])

        hit_x, hit_y = random_coord()
        land_x, land_y = random_coord()

        stroke = Stroke(
            rally_id=rally_id,
            stroke_num=i,
            player=player,
            shot_type=shot_type,
            shot_quality=random_shot_quality(),
            hit_x=hit_x,
            hit_y=hit_y,
            land_x=land_x,
            land_y=land_y,
            hit_zone=random_zone(),
            land_zone=random_zone(),
            is_backhand=random.random() < 0.25,
            is_around_head=random.random() < 0.05,
            is_cross=random.random() < 0.2,
        )
        strokes.append(stroke)

    return strokes

def generate_set(
    db,
    match_id: int,
    set_num: int,
    player_a_wins_set: bool,
    is_doubles: bool = False,
    partner_a_id: int = None,
    partner_b_id: int = None,
) -> GameSet:
    """1セット分のデータを生成する"""
    # スコア生成
    if player_a_wins_set:
        score_a = 21
        # 15〜20点の間で相手スコアをランダムに決定
        score_b = random.randint(12, 20)
    else:
        score_b = 21
        score_a = random.randint(12, 20)

    # デュース判定
    is_deuce = (score_a >= 20 and score_b >= 20)
    if is_deuce:
        if player_a_wins_set:
            score_a = 22 + random.randint(0, 2)
            score_b = score_a - 2
        else:
            score_b = 22 + random.randint(0, 2)
            score_a = score_b - 2

    game_set = GameSet(
        match_id=match_id,
        set_num=set_num,
        winner="player_a" if player_a_wins_set else "player_b",
        score_a=score_a,
        score_b=score_b,
        is_deuce=is_deuce,
        duration_min=round(random.uniform(20, 40), 1),
    )
    db.add(game_set)
    db.flush()

    # ラリー生成: スコアに対応したラリー数を作成
    total_points = score_a + score_b
    current_a = 0
    current_b = 0
    rally_num = 1

    # ポイントシーケンスを生成
    points = (
        ["a"] * score_a + ["b"] * score_b
    )
    random.shuffle(points)

    server = "player_a"  # 最初はplayer_aがサーブ

    for point_winner_code in points:
        rally_winner = "player_a" if point_winner_code == "a" else "player_b"
        rally_length = random.randint(3, 12)

        rally = Rally(
            set_id=game_set.id,
            rally_num=rally_num,
            server=server,
            winner=rally_winner,
            end_type=random.choices(
                ["ace", "forced_error", "unforced_error", "net_error", "winner"],
                weights=[0.1, 0.35, 0.25, 0.15, 0.15]
            )[0],
            rally_length=rally_length,
            duration_sec=round(rally_length * random.uniform(0.8, 1.5), 1),
            score_a_after=current_a + (1 if rally_winner == "player_a" else 0),
            score_b_after=current_b + (1 if rally_winner == "player_b" else 0),
            is_deuce=(current_a >= 20 and current_b >= 20),
        )
        db.add(rally)
        db.flush()

        if point_winner_code == "a":
            current_a += 1
        else:
            current_b += 1

        # ストローク生成
        strokes = generate_rally_strokes(
            db=db,
            rally_id=rally.id,
            player_a_role="player_a",
            player_b_role="player_b",
            rally_length=rally_length,
            player_a_wins=rally_winner == "player_a",
            is_doubles=is_doubles,
            partner_a_role="partner_a" if is_doubles else None,
            partner_b_role="partner_b" if is_doubles else None,
        )
        for stroke in strokes:
            db.add(stroke)

        # サーブ権の移動（勝者がサーブ）
        server = rally_winner
        rally_num += 1

    return game_set


def generate_match(
    db,
    player_a_id: int,
    player_b_id: int,
    tournament: str,
    tournament_level: str,
    match_date: date,
    result: str,  # win=player_a勝利
    match_format: str = "singles",
    partner_a_id: int = None,
    partner_b_id: int = None,
) -> Match:
    """1試合分のデータを生成する"""
    is_doubles = match_format != "singles"
    player_a_wins_match = result == "win"

    match = Match(
        tournament=tournament,
        tournament_level=tournament_level,
        tournament_grade=None,
        round=random.choice(["1回戦", "2回戦", "準々決勝", "準決勝", "決勝"]),
        date=match_date,
        format=match_format,
        player_a_id=player_a_id,
        player_b_id=player_b_id,
        partner_a_id=partner_a_id,
        partner_b_id=partner_b_id,
        result=result,
        annotation_status="complete",
        annotation_progress=1.0,
    )
    db.add(match)
    db.flush()

    # セット数の決定（2-0または2-1）
    if player_a_wins_match:
        if random.random() < 0.5:
            # 2-0
            set_results = [True, True]
        else:
            # 2-1
            set_results = [True, False, True]
    else:
        if random.random() < 0.5:
            # 0-2
            set_results = [False, False]
        else:
            # 1-2
            set_results = [False, True, False]

    for i, a_wins in enumerate(set_results, 1):
        generate_set(
            db=db,
            match_id=match.id,
            set_num=i,
            player_a_wins_set=a_wins,
            is_doubles=is_doubles,
            partner_a_id=partner_a_id,
            partner_b_id=partner_b_id,
        )

    final_score_parts = []
    sets = db.query(GameSet).filter(GameSet.match_id == match.id).order_by(GameSet.set_num).all()
    for s in sets:
        final_score_parts.append(f"{s.score_a}-{s.score_b}")
    match.final_score = ", ".join(final_score_parts)

    return match


def main():
    """メイン処理: テストデータをDBに投入する"""
    create_tables()
    db = SessionLocal()

    try:
        # 既存の同名選手を確認
        existing = db.query(Player).filter(Player.name.in_(["山田太郎", "佐藤次郎", "鈴木三郎", "田中四郎"])).all()
        if existing:
            print(f"既存データが見つかりました ({len(existing)}件)。スキップします。")
            print("削除して再生成する場合は手動でDBをクリアしてください。")
            return

        print("選手データを生成中...")
        yamada = Player(name="山田太郎", name_en="Taro Yamada", team="テストチーム", nationality="JPN",
                        dominant_hand="R", is_target=True)
        sato = Player(name="佐藤次郎", name_en="Jiro Sato", team="相手チームA", nationality="JPN",
                      dominant_hand="R", is_target=False)
        suzuki = Player(name="鈴木三郎", name_en="Saburo Suzuki", team="相手チームB", nationality="JPN",
                        dominant_hand="R", is_target=False)
        tanaka = Player(name="田中四郎", name_en="Shiro Tanaka", team="テストチーム", nationality="JPN",
                        dominant_hand="L", is_target=False)

        db.add_all([yamada, sato, suzuki, tanaka])
        db.flush()
        print(f"  山田太郎 (ID={yamada.id}), 佐藤次郎 (ID={sato.id}), 鈴木三郎 (ID={suzuki.id}), 田中四郎 (ID={tanaka.id})")

        print("\n試合データを生成中...")

        # Match1: 山田 vs 佐藤, シングルス, IC, 勝ち
        m1 = generate_match(
            db, yamada.id, sato.id,
            "ICテスト大会2025", "IC",
            date(2025, 1, 15), "win", "singles"
        )
        print(f"  Match1 (ID={m1.id}): 山田 vs 佐藤 [IC, 勝ち]")

        # Match2: 山田 vs 佐藤, シングルス, SJL, 負け
        m2 = generate_match(
            db, yamada.id, sato.id,
            "SJLテスト大会2025", "SJL",
            date(2025, 2, 20), "loss", "singles"
        )
        print(f"  Match2 (ID={m2.id}): 山田 vs 佐藤 [SJL, 負け]")

        # Match3: 山田 vs 鈴木, シングルス, 国内, 勝ち
        m3 = generate_match(
            db, yamada.id, suzuki.id,
            "国内テスト選手権2025", "国内",
            date(2025, 3, 10), "win", "singles"
        )
        print(f"  Match3 (ID={m3.id}): 山田 vs 鈴木 [国内, 勝ち]")

        # Match4: 山田/田中 vs 佐藤/鈴木, 混合ダブルス, IC, 勝ち
        m4 = generate_match(
            db, yamada.id, sato.id,
            "ICダブルステスト2025", "IC",
            date(2025, 4, 5), "win", "mixed_doubles",
            partner_a_id=tanaka.id, partner_b_id=suzuki.id
        )
        print(f"  Match4 (ID={m4.id}): 山田/田中 vs 佐藤/鈴木 [IC混合, 勝ち]")

        # Match5: 山田 vs 鈴木, シングルス, IC, 負け
        m5 = generate_match(
            db, yamada.id, suzuki.id,
            "ICテスト大会2026", "IC",
            date(2026, 1, 20), "loss", "singles"
        )
        print(f"  Match5 (ID={m5.id}): 山田 vs 鈴木 [IC, 負け]")

        db.commit()

        # 統計を表示
        total_rallies = db.query(Rally).count()
        total_strokes = db.query(Stroke).count()
        print(f"\n生成完了!")
        print(f"  総ラリー数: {total_rallies}")
        print(f"  総ストローク数: {total_strokes}")
        print(f"  山田太郎のID: {yamada.id}")

    except Exception as e:
        db.rollback()
        print(f"エラーが発生しました: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
