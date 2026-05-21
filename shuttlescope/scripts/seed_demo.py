r"""
demo ロール用デモデータ投入スクリプト（seed_demo.py）

設計: private_docs/TUTORIAL_REVAMP_2026-05-21.md

目的:
  - チュートリアル中に player / coach / analyst へ read-only で見せる
    「デモデータ」を投入する。
  - **データは完全ランダム生成（実在人物なし）**。氏名・チーム名・コンディションは
    全てダミー。ロール越え閲覧でも個人情報漏洩が起きないことを担保する。
  - role=`demo` の testtest ユーザ + 専用 DEMO チームを作成し、
    全デモ選手/試合をこのチームに紐付ける（owner_team_id / team_id = demo team）。

実行方法:
  cd shuttlescope
  .\backend\.venv\Scripts\python scripts/seed_demo.py
  # 既存デモデータを作り直す場合
  .\backend\.venv\Scripts\python scripts/seed_demo.py --reset

注意:
  - 直接 DB に書き込む（SessionLocal）。バックエンド稼働の有無に依存しない。
  - 本スクリプトは DEMO チームに属するレコードのみを対象とし、実データには触れない。
"""
from __future__ import annotations

import argparse
import random
import sys
from datetime import date, datetime, timedelta

# backend パッケージ import パスを確保
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.db.database import SessionLocal  # noqa: E402
from backend.db.models import (  # noqa: E402
    Team, User, Player, Match, GameSet, Rally, Stroke, Condition,
)
from backend.routers.auth import _hash_password  # noqa: E402

DEMO_TEAM_NAME = "DEMO（チュートリアル用）"
DEMO_TEAM_DISPLAY_ID = "__demo__"
DEMO_USERNAME = "testtest"
DEMO_PASSWORD = "DemoTutorial!2026"  # 既知パスワード（攻撃テスト/検証用）

# ── ランダム生成プール（すべてダミー・実在人物なし） ───────────────────────────
FAKE_FIRST = ["太郎", "次郎", "三郎", "花子", "桃子", "海斗", "蓮", "陽菜", "結衣", "颯太"]
FAKE_LAST = ["デモ", "見本", "仮", "サンプル", "テスト", "例示", "架空", "標本"]
SHOT_TYPES = [
    "short_service", "long_service", "net_shot", "clear", "push_rush",
    "smash", "defensive", "drive", "lob", "drop", "cross_net", "slice",
    "flick", "half_smash", "block", "around_head",
]
ZONES = ["BL", "BC", "BR", "ML", "MC", "MR", "NL", "NC", "NR"]
END_TYPES = ["ace", "forced_error", "unforced_error", "net", "out", "winner"]


def _rand_name(rng: random.Random) -> str:
    return f"{rng.choice(FAKE_LAST)} {rng.choice(FAKE_FIRST)}"


def _ensure_demo_team(db) -> Team:
    t = db.query(Team).filter(Team.display_id == DEMO_TEAM_DISPLAY_ID).first()
    if t is None:
        t = Team(
            name=DEMO_TEAM_NAME,
            display_id=DEMO_TEAM_DISPLAY_ID,
            short_name="DEMO",
            is_independent=False,
            notes="チュートリアル用デモデータ（全件ランダム生成・実在人物なし）",
        )
        db.add(t)
        db.flush()
        print(f"  [+] DEMO チーム作成 id={t.id}")
    else:
        print(f"  [=] DEMO チーム既存 id={t.id}")
    return t


def _reset_demo_data(db, team_id: int) -> None:
    """DEMO チームに紐付くデータのみを削除（実データには触れない）。"""
    pids = [p.id for p in db.query(Player.id).filter(Player.team_id == team_id).all()]
    pid_set = set(pids)
    mids = [
        m.id for m in db.query(Match.id).filter(Match.owner_team_id == team_id).all()
    ]
    # 子から順に削除
    if mids:
        set_ids = [s.id for s in db.query(GameSet.id).filter(GameSet.match_id.in_(mids)).all()]
        if set_ids:
            rally_ids = [r.id for r in db.query(Rally.id).filter(Rally.set_id.in_(set_ids)).all()]
            if rally_ids:
                db.query(Stroke).filter(Stroke.rally_id.in_(rally_ids)).delete(synchronize_session=False)
                db.query(Rally).filter(Rally.id.in_(rally_ids)).delete(synchronize_session=False)
            db.query(GameSet).filter(GameSet.id.in_(set_ids)).delete(synchronize_session=False)
        db.query(Match).filter(Match.id.in_(mids)).delete(synchronize_session=False)
    if pid_set:
        db.query(Condition).filter(Condition.player_id.in_(pid_set)).delete(synchronize_session=False)
        # demo user の player_id 参照を外してから選手削除
        for u in db.query(User).filter(User.player_id.in_(pid_set)).all():
            u.player_id = None
        db.query(Player).filter(Player.id.in_(pid_set)).delete(synchronize_session=False)
    db.flush()
    print(f"  [-] 旧デモデータ削除: players={len(pid_set)} matches={len(mids)}")


def _make_players(db, team_id: int, rng: random.Random, n: int) -> list[Player]:
    players = []
    for i in range(n):
        p = Player(
            name=_rand_name(rng),
            name_en=f"Demo Player {i + 1}",
            team_id=team_id,
            dominant_hand=rng.choice(["R", "L"]),
            birth_year=rng.randint(1998, 2006),
            is_target=(i == 0),
            profile_status="verified",
            notes="デモデータ（ランダム生成・実在人物なし）",
        )
        db.add(p)
        players.append(p)
    db.flush()
    print(f"  [+] デモ選手 {len(players)} 名作成")
    return players


def _make_strokes(rng: random.Random, rally: Rally, length: int) -> list[Stroke]:
    strokes = []
    for n in range(length):
        who = "player_a" if n % 2 == 0 else "player_b"
        st = "short_service" if n == 0 else rng.choice(SHOT_TYPES[2:])
        strokes.append(Stroke(
            rally_id=rally.id,
            stroke_num=n + 1,
            player=who,
            shot_type=st,
            hit_zone=rng.choice(ZONES),
            land_zone=rng.choice(ZONES),
            hit_x=round(rng.random(), 3),
            hit_y=round(rng.random(), 3),
            land_x=round(rng.random(), 3),
            land_y=round(rng.random(), 3),
            is_backhand=rng.random() < 0.3,
            is_around_head=rng.random() < 0.15,
            is_cross=rng.random() < 0.4,
            timestamp_sec=float((n + 1) * 3),
        ))
    return strokes


def _make_match(db, team_id: int, rng: random.Random, pa: Player, pb: Player,
                idx: int) -> Match:
    d = date(2025, 1, 1) + timedelta(days=rng.randint(0, 300))
    m = Match(
        tournament=f"デモ大会 {idx + 1}",
        tournament_level=rng.choice(["IC", "IS", "国内", "その他"]),
        round=rng.choice(["R32", "R16", "QF", "SF", "F"]),
        date=d,
        venue="デモ体育館",
        format="singles",
        player_a_id=pa.id,
        player_b_id=pb.id,
        result=rng.choice(["win", "loss"]),
        annotation_status="complete",
        annotation_progress=1.0,
        owner_team_id=team_id,
        is_public_pool=False,
        competition_type="practice_match",
        notes="デモデータ（ランダム生成）",
    )
    db.add(m)
    db.flush()

    n_sets = rng.choice([2, 3])
    for s_num in range(1, n_sets + 1):
        gs = GameSet(match_id=m.id, set_num=s_num)
        db.add(gs)
        db.flush()
        score_a = score_b = 0
        n_rallies = rng.randint(12, 24)
        for r_num in range(1, n_rallies + 1):
            winner = rng.choice(["player_a", "player_b"])
            if winner == "player_a":
                score_a += 1
            else:
                score_b += 1
            length = rng.randint(2, 12)
            rally = Rally(
                set_id=gs.id,
                rally_num=r_num,
                server="player_a" if r_num % 2 else "player_b",
                winner=winner,
                end_type=rng.choice(END_TYPES),
                rally_length=length,
                score_a_after=score_a,
                score_b_after=score_b,
                is_deuce=(score_a >= 20 and score_b >= 20),
                video_timestamp_start=float(r_num * 30),
            )
            db.add(rally)
            db.flush()
            for stk in _make_strokes(rng, rally, length):
                db.add(stk)
        gs.winner = "player_a" if score_a > score_b else "player_b"
        gs.score_a = score_a
        gs.score_b = score_b
    return m


def _make_conditions(db, rng: random.Random, player: Player, n: int) -> None:
    base = date(2025, 1, 6)
    for i in range(n):
        db.add(Condition(
            player_id=player.id,
            measured_at=base + timedelta(weeks=i),
            condition_type="weekly",
            weight_kg=round(rng.uniform(60, 75), 1),
            muscle_mass_kg=round(rng.uniform(30, 40), 1),
            body_fat_pct=round(rng.uniform(8, 18), 1),
            hooper_sleep=rng.randint(1, 7),
            hooper_soreness=rng.randint(1, 7),
            hooper_stress=rng.randint(1, 7),
            hooper_fatigue=rng.randint(1, 7),
            session_rpe=rng.randint(3, 9),
            session_duration_min=rng.randint(60, 150),
            sleep_hours=round(rng.uniform(5.5, 9.0), 1),
        ))


def _ensure_demo_user(db, team: Team, demo_player: Player) -> User:
    u = db.query(User).filter(User.username == DEMO_USERNAME).first()
    if u is None:
        u = User(
            username=DEMO_USERNAME,
            role="demo",
            display_name="デモ ユーザ",
            team_id=team.id,
            player_id=demo_player.id,
            hashed_credential=_hash_password(DEMO_PASSWORD),
        )
        db.add(u)
        print(f"  [+] demo ユーザ作成 username={DEMO_USERNAME} role=demo")
    else:
        u.role = "demo"
        u.team_id = team.id
        u.player_id = demo_player.id
        u.hashed_credential = _hash_password(DEMO_PASSWORD)
        u.awaiting_admin_approval = False
        u.locked_until = None
        u.failed_attempts = 0
        print(f"  [=] demo ユーザ更新 username={DEMO_USERNAME} role=demo id={u.id}")
    db.flush()
    return u


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="既存デモデータを削除して作り直す")
    ap.add_argument("--seed", type=int, default=20260521, help="乱数シード")
    ap.add_argument("--players", type=int, default=6)
    ap.add_argument("--matches", type=int, default=8)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    print("=" * 60)
    print("  ShuttleScope demo ロール用データ投入")
    print("=" * 60)

    db = SessionLocal()
    try:
        team = _ensure_demo_team(db)

        if args.reset:
            _reset_demo_data(db, team.id)

        existing = db.query(Player).filter(Player.team_id == team.id).count()
        if existing and not args.reset:
            print(f"  [!] DEMO チームに既に {existing} 名の選手が存在します。")
            print("      作り直すには --reset を付けて再実行してください。")
            # demo ユーザだけは確実に整える
            dp = db.query(Player).filter(Player.team_id == team.id).first()
            _ensure_demo_user(db, team, dp)
            db.commit()
            print("  [=] demo ユーザのみ整合化して終了")
            return

        players = _make_players(db, team.id, rng, args.players)

        for idx in range(args.matches):
            pa = players[0]  # 解析対象は常に demo player A
            pb = rng.choice(players[1:])
            _make_match(db, team.id, rng, pa, pb, idx)
        print(f"  [+] デモ試合 {args.matches} 件作成")

        # コンディションは解析対象選手中心に
        _make_conditions(db, rng, players[0], 16)
        for p in players[1:]:
            _make_conditions(db, rng, p, rng.randint(3, 8))
        print("  [+] デモコンディション作成")

        _ensure_demo_user(db, team, players[0])

        db.commit()
        print("\n" + "=" * 60)
        print(f"  完了: team_id={team.id} demo_player_id={players[0].id}")
        print(f"  demo ログイン: {DEMO_USERNAME} / {DEMO_PASSWORD}")
        print("=" * 60)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
