"""
テストデータセット作成スクリプト
ShuttleScope 動作確認用のサンプルデータを投入します。

実行方法:
  python scripts/create_test_dataset.py
"""
import json
import urllib.request
import urllib.error
import sys

BASE_URL = "http://localhost:8765/api"


def req(method: str, path: str, body: dict | None = None) -> dict:
    url = BASE_URL + path
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8")
        print(f"[ERROR] {method} {path} → HTTP {e.code}: {detail}")
        sys.exit(1)


def get(path: str) -> dict:
    return req("GET", path)


def post(path: str, body: dict) -> dict:
    return req("POST", path, body)


def put(path: str, body: dict) -> dict:
    return req("PUT", path, body)


print("=" * 50)
print("  ShuttleScope テストデータセット作成")
print("=" * 50)

# --- 1. 選手作成 ---
print("\n[1] 選手を作成中...")

pa = post("/players", {
    "name": "田中 太郎",
    "name_en": "Taro Tanaka",
    "team": "東大BC",
    "dominant_hand": "R",
    "birth_year": 2000,
    "is_target": True,
    "notes": "テスト選手A",
})
player_a_id = pa["data"]["id"]
print(f"  選手A: {pa['data']['name']} (id={player_a_id})")

pb = post("/players", {
    "name": "山田 次郎",
    "name_en": "Jiro Yamada",
    "team": "京大BC",
    "dominant_hand": "R",
    "birth_year": 2001,
    "is_target": False,
    "notes": "テスト選手B",
})
player_b_id = pb["data"]["id"]
print(f"  選手B: {pb['data']['name']} (id={player_b_id})")

# --- 2. 試合作成 ---
print("\n[2] 試合を作成中...")

match_res = post("/matches", {
    "tournament": "テスト大会2024",
    "tournament_level": "国内",
    "round": "QF",
    "date": "2024-10-01",
    "venue": "東京体育館",
    "format": "singles",
    "player_a_id": player_a_id,
    "player_b_id": player_b_id,
    "result": "win",
    "final_score": "21-18, 21-15",
    "video_url": "",
    "annotation_status": "in_progress",
    "annotation_progress": 0.0,
    "notes": "テスト用サンプルデータ",
})
match_id = match_res["data"]["id"]
print(f"  試合: {match_res['data']['tournament']} (id={match_id})")

# --- 3. セット1作成 ---
print("\n[3] セット1を作成中...")

set_res = post("/sets", {
    "match_id": match_id,
    "set_num": 1,
})
set1_id = set_res["data"]["id"]
print(f"  Set1 (id={set1_id})")

# --- 4. ラリーとストロークを一括保存 ---
print("\n[4] ラリー10本を保存中...")

# ラリーデータ: (winner, end_type, strokes_list)
# strokes_list: (player, shot_type, hit_zone, land_zone, is_backhand, is_around_head)
RALLIES = [
    # Rally 1: A得点 - サーブからのネット前勝負
    ("player_a", "ace", [
        ("player_a", "short_service", None, "NL", False, False),
        ("player_b", "net_shot", "NL", "NC", False, False),
        ("player_a", "push_rush", "NC", "NR", False, False),
    ]),
    # Rally 2: B得点 - スマッシュ決め
    ("player_b", "forced_error", [
        ("player_a", "short_service", None, "NC", False, False),
        ("player_b", "clear", "NC", "BC", False, False),
        ("player_a", "smash", "BC", "ML", False, False),
        ("player_b", "defensive", "ML", "BC", False, False),
        ("player_a", "smash", "BC", "MR", False, False),
        ("player_b", "cant_reach", None, None, False, False),
    ]),
    # Rally 3: A得点 - ネット
    ("player_a", "net", [
        ("player_a", "long_service", None, "BC", False, False),
        ("player_b", "clear", "BC", "BC", False, False),
        ("player_a", "drop", "BC", "NL", False, False),
        ("player_b", "net_shot", "NL", "NC", False, False),
        ("player_a", "push_rush", "NC", "NC", False, False),
    ]),
    # Rally 4: A得点
    ("player_a", "unforced_error", [
        ("player_a", "short_service", None, "NR", False, False),
        ("player_b", "net_shot", "NR", "NL", False, False),
        ("player_a", "cross_net", "NL", "NR", False, False),
    ]),
    # Rally 5: B得点
    ("player_b", "out", [
        ("player_a", "short_service", None, "NC", False, False),
        ("player_b", "lob", "NC", "BL", True, False),
        ("player_a", "clear", "BL", "BR", False, False),
        ("player_b", "smash", "BR", "ML", False, False),
        ("player_a", "lob", "ML", "BC", False, False),
        ("player_b", "smash", "BC", "MC", False, False),
    ]),
    # Rally 6: A得点
    ("player_a", "ace", [
        ("player_a", "long_service", None, "BL", False, False),
        ("player_b", "clear", "BL", "BR", True, False),
        ("player_a", "around_head", "BR", "NL", False, True),
        ("player_b", "cant_reach", None, None, False, False),
    ]),
    # Rally 7: B得点
    ("player_b", "forced_error", [
        ("player_a", "short_service", None, "NC", False, False),
        ("player_b", "push_rush", "NC", "NL", False, False),
        ("player_a", "cross_net", "NL", "NR", False, False),
        ("player_b", "drive", "NR", "MC", False, False),
        ("player_a", "drive", "MC", "ML", False, False),
        ("player_b", "smash", "ML", "MR", False, False),
    ]),
    # Rally 8: A得点
    ("player_a", "net", [
        ("player_a", "short_service", None, "NL", False, False),
        ("player_b", "flick", "NL", "BC", False, False),
        ("player_a", "smash", "BC", "ML", False, False),
        ("player_b", "block", "ML", "NC", False, False),
        ("player_a", "push_rush", "NC", "NR", False, False),
    ]),
    # Rally 9: A得点
    ("player_a", "unforced_error", [
        ("player_a", "long_service", None, "BC", False, False),
        ("player_b", "drop", "BC", "NR", False, False),
        ("player_a", "net_shot", "NR", "NC", False, False),
        ("player_b", "cross_net", "NC", "NL", False, False),
        ("player_a", "push_rush", "NL", "NL", False, False),
    ]),
    # Rally 10: B得点
    ("player_b", "forced_error", [
        ("player_a", "short_service", None, "NC", False, False),
        ("player_b", "lob", "NC", "BC", True, False),
        ("player_a", "half_smash", "BC", "MR", False, False),
        ("player_b", "defensive", "MR", "BL", False, False),
        ("player_a", "smash", "BL", "ML", False, False),
        ("player_b", "lob", "ML", "BL", False, False),
        ("player_a", "smash", "BL", "MR", False, False),
        ("player_b", "cant_reach", None, None, False, False),
    ]),
]

score_a = 0
score_b = 0

for rally_num, (winner, end_type, strokes) in enumerate(RALLIES, start=1):
    new_score_a = score_a + (1 if winner == "player_a" else 0)
    new_score_b = score_b + (1 if winner == "player_b" else 0)

    stroke_list = [
        {
            "stroke_num": i + 1,
            "player": player,
            "shot_type": shot_type,
            "hit_zone": hit_zone,
            "land_zone": land_zone,
            "is_backhand": is_backhand,
            "is_around_head": is_around_head,
            "above_net": None,
            "is_cross": False,
            "timestamp_sec": float(rally_num * 30 + i * 3),
        }
        for i, (player, shot_type, hit_zone, land_zone, is_backhand, is_around_head) in enumerate(strokes)
    ]

    res = post("/strokes/batch", {
        "rally": {
            "set_id": set1_id,
            "rally_num": rally_num,
            "server": "player_a",
            "winner": winner,
            "end_type": end_type,
            "rally_length": len(strokes),
            "score_a_after": new_score_a,
            "score_b_after": new_score_b,
            "is_deuce": new_score_a >= 20 and new_score_b >= 20,
            "video_timestamp_start": float(rally_num * 30),
        },
        "strokes": stroke_list,
    })

    score_a = new_score_a
    score_b = new_score_b
    print(f"  Rally {rally_num:2d}: {winner} 得点 ({end_type}), {len(strokes)}球"
          f"  → スコア {score_a}-{score_b}")

# --- 5. セット1終了 ---
print("\n[5] セット1を終了中...")

set_end_winner = "player_a" if score_a > score_b else "player_b"
put(f"/sets/{set1_id}/end", {
    "winner": set_end_winner,
    "score_a": score_a,
    "score_b": score_b,
})
print(f"  Set1 終了: {score_a}-{score_b} ({set_end_winner} 勝利)")

# --- 完了 ---
print("\n" + "=" * 50)
print(f"  完了！")
print(f"  試合ID: {match_id}")
print(f"  選手A: 田中 太郎 (id={player_a_id})")
print(f"  選手B: 山田 次郎 (id={player_b_id})")
print(f"  ラリー数: {len(RALLIES)}")
print(f"  最終スコア: {score_a}-{score_b}")
print("=" * 50)
print(f"\nアノテーター: http://localhost:5173/annotator/{match_id}")
print(f"(Electron アプリから試合一覧で確認してください)")
