"""
PoC デモ用サンプルデータ投入スクリプト（seed_sample_data.py）

目的:
  - GrowthTimeline の年区切り表示を確認できるよう複数年・複数試合を作成
  - OpponentTypeAffinity / observation_analytics 解析に使えるデータを生成
  - 試合前観察（warmup observations: handedness, physical_caution, self_condition 等）も投入

実行方法:
  # バックエンドを起動した状態で
  cd shuttlescope
  .\\backend\\.venv\\Scripts\\python scripts/seed_sample_data.py
  # または
  python scripts/seed_sample_data.py
"""

import json
import sys
import urllib.error
import urllib.request
from typing import Optional

BASE_URL = "http://localhost:8765/api"


# ---------------------------------------------------------------------------
# HTTP ヘルパー
# ---------------------------------------------------------------------------

def _req(method: str, path: str, body: Optional[dict] = None) -> dict:
    url = BASE_URL + path
    data = json.dumps(body).encode("utf-8") if body else None
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(request) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8")
        print(f"[ERROR] {method} {path} → HTTP {e.code}: {detail}")
        sys.exit(1)


def get(path: str) -> dict:
    return _req("GET", path)


def post(path: str, body: dict) -> dict:
    return _req("POST", path, body)


def put(path: str, body: dict) -> dict:
    return _req("PUT", path, body)


# ---------------------------------------------------------------------------
# ラリー定義ヘルパー
# ---------------------------------------------------------------------------

def make_strokes(raw: list[tuple]) -> list[dict]:
    """(player, shot_type, hit_zone, land_zone, is_backhand, is_around_head) タプルリストから
    stroke dict リストを生成する"""
    return [
        {
            "stroke_num": i + 1,
            "player": p,
            "shot_type": st,
            "hit_zone": hz,
            "land_zone": lz,
            "is_backhand": bh,
            "is_around_head": ah,
            "above_net": None,
            "is_cross": False,
            "timestamp_sec": float((i + 1) * 3),
        }
        for i, (p, st, hz, lz, bh, ah) in enumerate(raw)
    ]


def save_rallies(set_id: int, rallies: list[tuple]) -> tuple[int, int]:
    """
    rallies: [(winner, end_type, strokes_raw), ...]
    Returns: (score_a, score_b) after last rally
    """
    score_a, score_b = 0, 0
    for rally_num, (winner, end_type, strokes_raw) in enumerate(rallies, start=1):
        score_a += 1 if winner == "player_a" else 0
        score_b += 1 if winner == "player_b" else 0
        strokes = make_strokes(strokes_raw)
        post("/strokes/batch", {
            "rally": {
                "set_id": set_id,
                "rally_num": rally_num,
                "server": "player_a",
                "winner": winner,
                "end_type": end_type,
                "rally_length": len(strokes),
                "score_a_after": score_a,
                "score_b_after": score_b,
                "is_deuce": score_a >= 20 and score_b >= 20,
                "video_timestamp_start": float(rally_num * 30),
            },
            "strokes": strokes,
        })
        print(f"    Rally {rally_num:2d}: {winner} 得点 ({end_type}) → {score_a}-{score_b}")
    return score_a, score_b


def create_set(match_id: int, set_num: int, rallies: list[tuple]) -> tuple[int, int, int]:
    """セット作成 → ラリー保存 → セット終了。Returns (set_id, score_a, score_b)"""
    set_res = post("/sets", {"match_id": match_id, "set_num": set_num})
    set_id = set_res["data"]["id"]
    score_a, score_b = save_rallies(set_id, rallies)
    winner = "player_a" if score_a > score_b else "player_b"
    put(f"/sets/{set_id}/end", {"winner": winner, "score_a": score_a, "score_b": score_b})
    print(f"  → Set{set_num} 終了: {winner} 勝利 ({score_a}-{score_b})")
    return set_id, score_a, score_b


# ---------------------------------------------------------------------------
# ラリーテンプレート（再利用可能な定型パターン）
# ---------------------------------------------------------------------------

# smash_win: player_a スマッシュ決め
SMASH_WIN = ("player_a", "forced_error", [
    ("player_a", "short_service", None, "NC", False, False),
    ("player_b", "clear", "NC", "BC", False, False),
    ("player_a", "smash", "BC", "ML", False, False),
    ("player_b", "cant_reach", None, None, False, False),
])

# net_win_a: player_a ネット際勝ち
NET_WIN_A = ("player_a", "net", [
    ("player_a", "short_service", None, "NL", False, False),
    ("player_b", "net_shot", "NL", "NC", False, False),
    ("player_a", "push_rush", "NC", "NR", False, False),
])

# out_b: player_b アウト
OUT_B = ("player_a", "out", [
    ("player_a", "long_service", None, "BC", False, False),
    ("player_b", "smash", "BC", "ML", False, False),
    ("player_a", "lob", "ML", "BL", False, False),
    ("player_b", "smash", "BL", "MR", False, False),
])

# b_win: player_b 勝ち
B_WIN = ("player_b", "forced_error", [
    ("player_a", "short_service", None, "NC", False, False),
    ("player_b", "push_rush", "NC", "NR", False, False),
    ("player_a", "cross_net", "NR", "NL", False, False),
    ("player_b", "smash", "NL", "MC", False, False),
])

# long_b_win: 長いラリーでBが勝つ
LONG_B_WIN = ("player_b", "unforced_error", [
    ("player_a", "short_service", None, "NC", False, False),
    ("player_b", "lob", "NC", "BL", True, False),
    ("player_a", "clear", "BL", "BR", False, False),
    ("player_b", "drop", "BR", "NR", False, False),
    ("player_a", "net_shot", "NR", "NC", False, False),
    ("player_b", "push_rush", "NC", "NL", False, False),
    ("player_a", "drive", "NL", "MC", False, False),
    ("player_b", "smash", "MC", "MR", False, False),
])


# ---------------------------------------------------------------------------
# メイン処理
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("  ShuttleScope PoC サンプルデータ投入スクリプト")
    print("=" * 60)

    # ------------------------------------------------------------------
    # 1. 選手作成
    # ------------------------------------------------------------------
    print("\n[1] 選手作成...")

    pa = post("/players", {
        "name": "佐藤 健太",
        "name_en": "Kenta Sato",
        "team": "早稲田BC",
        "dominant_hand": "R",
        "birth_year": 2001,
        "is_target": True,
        "notes": "PoC サンプル: 主対象選手（右利き・アタッカー型）",
    })
    pid_a = pa["data"]["id"]
    print(f"  A: {pa['data']['name']} (id={pid_a})")

    pb = post("/players", {
        "name": "鈴木 翔",
        "name_en": "Sho Suzuki",
        "team": "慶應BC",
        "dominant_hand": "R",
        "birth_year": 2000,
        "is_target": False,
        "notes": "PoC サンプル: 相手選手1（右利き・守備型）",
    })
    pid_b = pb["data"]["id"]
    print(f"  B: {pb['data']['name']} (id={pid_b})")

    pc = post("/players", {
        "name": "高橋 涼",
        "name_en": "Ryo Takahashi",
        "team": "明治BC",
        "dominant_hand": "L",
        "birth_year": 2002,
        "is_target": False,
        "notes": "PoC サンプル: 相手選手2（左利き・バランス型）",
    })
    pid_c = pc["data"]["id"]
    print(f"  C: {pc['data']['name']} (id={pid_c})")

    pd = post("/players", {
        "name": "中村 海斗",
        "name_en": "Kaito Nakamura",
        "team": "東大BC",
        "dominant_hand": "R",
        "birth_year": 2001,
        "is_target": False,
        "notes": "PoC サンプル: 相手選手3（右利き・ネット前重視）",
    })
    pid_d = pd["data"]["id"]
    print(f"  D: {pd['data']['name']} (id={pid_d})")

    # ------------------------------------------------------------------
    # 2. 試合作成（複数年：2023・2024・2025）
    # ------------------------------------------------------------------
    print("\n[2] 試合作成（複数年）...")

    MATCHES = [
        # 2023年
        {
            "tournament": "全日本学生2023",
            "tournament_level": "全日本",
            "round": "R16",
            "date": "2023-09-10",
            "venue": "代々木体育館",
            "format": "singles",
            "player_a_id": pid_a,
            "player_b_id": pid_b,
            "result": "win",
            "final_score": "21-15, 21-17",
            "notes": "2023年 対 鈴木",
            "obs": {
                "opponent_id": pid_b,
                "handedness": "R",
                "physical_caution": "none",
                "tactical_style": "defender",
                "self_condition": "normal",
                "self_timing": "normal",
            },
            "sets": [
                [SMASH_WIN, NET_WIN_A, OUT_B, SMASH_WIN, NET_WIN_A,
                 B_WIN, SMASH_WIN, OUT_B, NET_WIN_A, SMASH_WIN,
                 LONG_B_WIN, NET_WIN_A, SMASH_WIN, OUT_B, NET_WIN_A],
                [SMASH_WIN, NET_WIN_A, SMASH_WIN, B_WIN, OUT_B,
                 NET_WIN_A, SMASH_WIN, LONG_B_WIN, NET_WIN_A, SMASH_WIN,
                 B_WIN, NET_WIN_A, SMASH_WIN, OUT_B, SMASH_WIN],
            ],
        },
        {
            "tournament": "関東学生秋季2023",
            "tournament_level": "国内",
            "round": "SF",
            "date": "2023-11-05",
            "venue": "東京武道館",
            "format": "singles",
            "player_a_id": pid_a,
            "player_b_id": pid_c,
            "result": "loss",
            "final_score": "18-21, 14-21",
            "notes": "2023年 対 高橋（左利き）",
            "obs": {
                "opponent_id": pid_c,
                "handedness": "L",
                "physical_caution": "none",
                "tactical_style": "balanced",
                "self_condition": "poor",
                "self_timing": "off",
            },
            "sets": [
                [B_WIN, SMASH_WIN, LONG_B_WIN, B_WIN, NET_WIN_A,
                 B_WIN, LONG_B_WIN, SMASH_WIN, B_WIN, LONG_B_WIN,
                 NET_WIN_A, B_WIN, LONG_B_WIN, B_WIN, NET_WIN_A,
                 B_WIN, LONG_B_WIN, B_WIN, NET_WIN_A, B_WIN],
                [B_WIN, LONG_B_WIN, B_WIN, LONG_B_WIN, NET_WIN_A,
                 B_WIN, LONG_B_WIN, B_WIN, OUT_B, B_WIN,
                 LONG_B_WIN, B_WIN, LONG_B_WIN, SMASH_WIN, B_WIN,
                 LONG_B_WIN, B_WIN, LONG_B_WIN, B_WIN, B_WIN],
            ],
        },
        # 2024年
        {
            "tournament": "全日本学生2024",
            "tournament_level": "全日本",
            "round": "QF",
            "date": "2024-09-08",
            "venue": "代々木体育館",
            "format": "singles",
            "player_a_id": pid_a,
            "player_b_id": pid_b,
            "result": "win",
            "final_score": "21-12, 21-14",
            "notes": "2024年 対 鈴木（リベンジ）",
            "obs": {
                "opponent_id": pid_b,
                "handedness": "R",
                "physical_caution": "light",
                "tactical_style": "defender",
                "self_condition": "great",
                "self_timing": "sharp",
            },
            "sets": [
                [SMASH_WIN, NET_WIN_A, SMASH_WIN, OUT_B, NET_WIN_A,
                 SMASH_WIN, SMASH_WIN, NET_WIN_A, OUT_B, SMASH_WIN,
                 NET_WIN_A, SMASH_WIN],
                [SMASH_WIN, NET_WIN_A, SMASH_WIN, SMASH_WIN, OUT_B,
                 NET_WIN_A, SMASH_WIN, NET_WIN_A, SMASH_WIN, SMASH_WIN,
                 OUT_B, NET_WIN_A, SMASH_WIN, NET_WIN_A],
            ],
        },
        {
            "tournament": "関東学生春季2024",
            "tournament_level": "国内",
            "round": "F",
            "date": "2024-05-20",
            "venue": "日本武道館",
            "format": "singles",
            "player_a_id": pid_a,
            "player_b_id": pid_c,
            "result": "win",
            "final_score": "21-18, 19-21, 21-16",
            "notes": "2024年 対 高橋（3セット激戦）",
            "obs": {
                "opponent_id": pid_c,
                "handedness": "L",
                "physical_caution": "none",
                "tactical_style": "balanced",
                "self_condition": "normal",
                "self_timing": "sharp",
            },
            "sets": [
                [SMASH_WIN, NET_WIN_A, SMASH_WIN, B_WIN, LONG_B_WIN,
                 NET_WIN_A, SMASH_WIN, B_WIN, NET_WIN_A, SMASH_WIN,
                 LONG_B_WIN, SMASH_WIN, NET_WIN_A, B_WIN, SMASH_WIN,
                 LONG_B_WIN, NET_WIN_A, SMASH_WIN, NET_WIN_A, SMASH_WIN,
                 NET_WIN_A],
                [B_WIN, LONG_B_WIN, NET_WIN_A, B_WIN, SMASH_WIN,
                 LONG_B_WIN, B_WIN, NET_WIN_A, B_WIN, LONG_B_WIN,
                 NET_WIN_A, B_WIN, SMASH_WIN, LONG_B_WIN, B_WIN,
                 NET_WIN_A, B_WIN, LONG_B_WIN, SMASH_WIN, B_WIN,
                 LONG_B_WIN],
                [SMASH_WIN, NET_WIN_A, SMASH_WIN, B_WIN, NET_WIN_A,
                 SMASH_WIN, NET_WIN_A, B_WIN, SMASH_WIN, NET_WIN_A,
                 SMASH_WIN, OUT_B, NET_WIN_A, SMASH_WIN, NET_WIN_A,
                 SMASH_WIN, NET_WIN_A, SMASH_WIN, NET_WIN_A, SMASH_WIN,
                 NET_WIN_A],
            ],
        },
        {
            "tournament": "関東学生秋季2023",
            "tournament_level": "国内",
            "round": "R16",
            "date": "2023-10-15",
            "venue": "東京武道館",
            "format": "singles",
            "player_a_id": pid_a,
            "player_b_id": pid_d,
            "result": "win",
            "final_score": "21-14, 21-18",
            "notes": "2023年 対 中村（初対戦）",
            "obs": {
                "opponent_id": pid_d,
                "handedness": "R",
                "physical_caution": "none",
                "tactical_style": "attacker",
                "self_condition": "normal",
                "self_timing": "normal",
            },
            "sets": [
                [SMASH_WIN, NET_WIN_A, SMASH_WIN, B_WIN, SMASH_WIN,
                 NET_WIN_A, OUT_B, SMASH_WIN, B_WIN, NET_WIN_A,
                 SMASH_WIN, SMASH_WIN, NET_WIN_A, B_WIN],
                [SMASH_WIN, NET_WIN_A, SMASH_WIN, B_WIN, NET_WIN_A,
                 SMASH_WIN, OUT_B, NET_WIN_A, SMASH_WIN, B_WIN,
                 SMASH_WIN, NET_WIN_A, SMASH_WIN, LONG_B_WIN, NET_WIN_A,
                 SMASH_WIN, B_WIN, SMASH_WIN],
            ],
        },
        {
            "tournament": "インカレ2024",
            "tournament_level": "IC",
            "round": "R32",
            "date": "2024-12-14",
            "venue": "大阪府立体育館",
            "format": "singles",
            "player_a_id": pid_a,
            "player_b_id": pid_d,
            "result": "win",
            "final_score": "21-16, 21-13",
            "notes": "2024年 対 中村",
            "obs": {
                "opponent_id": pid_d,
                "handedness": "R",
                "physical_caution": "none",
                "tactical_style": "attacker",
                "self_condition": "great",
                "self_timing": "normal",
            },
            "sets": [
                [SMASH_WIN, NET_WIN_A, SMASH_WIN, B_WIN, SMASH_WIN,
                 NET_WIN_A, SMASH_WIN, OUT_B, SMASH_WIN, NET_WIN_A,
                 B_WIN, NET_WIN_A, SMASH_WIN, SMASH_WIN, NET_WIN_A,
                 SMASH_WIN],
                [SMASH_WIN, SMASH_WIN, NET_WIN_A, SMASH_WIN, OUT_B,
                 NET_WIN_A, SMASH_WIN, SMASH_WIN, NET_WIN_A, SMASH_WIN,
                 NET_WIN_A, SMASH_WIN, OUT_B],
            ],
        },
        # 2025年
        {
            "tournament": "全日本学生2025",
            "tournament_level": "全日本",
            "round": "SF",
            "date": "2025-09-07",
            "venue": "代々木体育館",
            "format": "singles",
            "player_a_id": pid_a,
            "player_b_id": pid_b,
            "result": "win",
            "final_score": "21-10, 21-8",
            "notes": "2025年 対 鈴木（圧勝）",
            "obs": {
                "opponent_id": pid_b,
                "handedness": "R",
                "physical_caution": "moderate",
                "tactical_style": "defender",
                "self_condition": "great",
                "self_timing": "sharp",
            },
            "sets": [
                [SMASH_WIN, SMASH_WIN, NET_WIN_A, SMASH_WIN, SMASH_WIN,
                 NET_WIN_A, SMASH_WIN, B_WIN, SMASH_WIN, SMASH_WIN],
                [SMASH_WIN, NET_WIN_A, SMASH_WIN, SMASH_WIN, NET_WIN_A,
                 SMASH_WIN, B_WIN, NET_WIN_A],
            ],
        },
        {
            "tournament": "関東学生秋季2025",
            "tournament_level": "国内",
            "round": "QF",
            "date": "2025-10-12",
            "venue": "東京武道館",
            "format": "singles",
            "player_a_id": pid_a,
            "player_b_id": pid_d,
            "result": "win",
            "final_score": "21-11, 21-9",
            "notes": "2025年 対 中村（完勝）",
            "obs": {
                "opponent_id": pid_d,
                "handedness": "R",
                "physical_caution": "light",
                "tactical_style": "attacker",
                "self_condition": "great",
                "self_timing": "sharp",
            },
            "sets": [
                [SMASH_WIN, SMASH_WIN, NET_WIN_A, SMASH_WIN, OUT_B,
                 SMASH_WIN, NET_WIN_A, SMASH_WIN, SMASH_WIN, NET_WIN_A,
                 SMASH_WIN],
                [SMASH_WIN, SMASH_WIN, NET_WIN_A, SMASH_WIN, SMASH_WIN,
                 OUT_B, SMASH_WIN, NET_WIN_A, SMASH_WIN],
            ],
        },
        {
            "tournament": "関東学生春季2025",
            "tournament_level": "国内",
            "round": "QF",
            "date": "2025-05-25",
            "venue": "東京武道館",
            "format": "singles",
            "player_a_id": pid_a,
            "player_b_id": pid_c,
            "result": "win",
            "final_score": "21-14, 21-17",
            "notes": "2025年 対 高橋（成長を確認）",
            "obs": {
                "opponent_id": pid_c,
                "handedness": "L",
                "physical_caution": "none",
                "tactical_style": "balanced",
                "self_condition": "normal",
                "self_timing": "normal",
            },
            "sets": [
                [SMASH_WIN, NET_WIN_A, SMASH_WIN, B_WIN, SMASH_WIN,
                 LONG_B_WIN, NET_WIN_A, SMASH_WIN, B_WIN, NET_WIN_A,
                 SMASH_WIN, NET_WIN_A, B_WIN, SMASH_WIN],
                [SMASH_WIN, NET_WIN_A, B_WIN, SMASH_WIN, NET_WIN_A,
                 SMASH_WIN, LONG_B_WIN, SMASH_WIN, NET_WIN_A, B_WIN,
                 SMASH_WIN, NET_WIN_A, SMASH_WIN, LONG_B_WIN, NET_WIN_A,
                 SMASH_WIN, NET_WIN_A],
            ],
        },
    ]

    for m_def in MATCHES:
        sets_def = m_def.pop("sets")
        obs_def = m_def.pop("obs")

        m_res = post("/matches", m_def)
        mid = m_res["data"]["id"]
        print(f"\n  試合 id={mid}: {m_def['tournament']} ({m_def['date']}) vs 選手id={m_def['player_b_id']}")

        for s_num, s_rallies in enumerate(sets_def, start=1):
            print(f"  [Set {s_num}]")
            _, sa, sb = create_set(mid, s_num, s_rallies)

        # 試合終了
        put(f"/matches/{mid}/end", {
            "result": m_def["result"],
            "final_score": m_def["final_score"],
            "annotation_status": "completed",
            "annotation_progress": 1.0,
        })

        # 試合前観察記録を投入
        opp_id = obs_def["opponent_id"]
        observations = [
            {
                "match_id": mid,
                "player_id": opp_id,
                "observation_type": "handedness",
                "observation_value": obs_def["handedness"],
                "confidence_level": "confirmed",
                "created_by": "analyst",
            },
            {
                "match_id": mid,
                "player_id": opp_id,
                "observation_type": "physical_caution",
                "observation_value": obs_def["physical_caution"],
                "confidence_level": "likely",
                "created_by": "analyst",
            },
            {
                "match_id": mid,
                "player_id": opp_id,
                "observation_type": "tactical_style",
                "observation_value": obs_def["tactical_style"],
                "confidence_level": "tentative",
                "created_by": "analyst",
            },
        ]
        # 自コンディション（player_a = pid_a に対して保存）
        if obs_def.get("self_condition"):
            observations.append({
                "match_id": mid,
                "player_id": pid_a,
                "observation_type": "self_condition",
                "observation_value": obs_def["self_condition"],
                "confidence_level": "confirmed",
                "created_by": "analyst",
            })
        if obs_def.get("self_timing"):
            observations.append({
                "match_id": mid,
                "player_id": pid_a,
                "observation_type": "self_timing",
                "observation_value": obs_def["self_timing"],
                "confidence_level": "confirmed",
                "created_by": "analyst",
            })

        post(f"/warmup/observations/{mid}", {"observations": observations})
        print(f"  → 試合前観察 {len(observations)} 件保存")

    # ------------------------------------------------------------------
    # 完了
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("  サンプルデータ投入完了！")
    print(f"  選手: A=id{pid_a} / B=id{pid_b} / C=id{pid_c} / D=id{pid_d}")
    print(f"  試合数: {len(MATCHES)}")
    print("  ダッシュボード・予測ページで佐藤健太 (id={}) を選択して確認してください".format(pid_a))
    print("=" * 60)


if __name__ == "__main__":
    main()
