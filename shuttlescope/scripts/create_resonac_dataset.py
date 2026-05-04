"""
レゾナックバドミントン部 テストデータセット作成スクリプト
実際の選手データに基づくサンプルデータを投入します。

選手情報出典:
  S/Jリーグ公式サイト (sj-league.jp) / レゾナック公式 (resonac.com)

実行方法:
  python scripts/create_resonac_dataset.py
"""
import json
import urllib.request
import urllib.error
import sys

BASE_URL = "http://localhost:8765/api"


def req(method: str, path: str, body: dict | None = None) -> dict:
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


print("=" * 60)
print("  レゾナックバドミントン部 テストデータセット")
print("=" * 60)

# ─── 1. 選手登録 ────────────────────────────────────────────────
print("\n[1] 選手を登録中...")

# レゾナック選手（実データ）
muroya = req("POST", "/players", {
    "name": "室屋 奏乃",
    "name_en": "Kanano Muroya",
    "team": "レゾナック",
    "dominant_hand": "R",
    "birth_year": 2004,
    "is_target": True,
    "notes": "#5 大分県出身 得意ショット:後ろからのアタック",
})
muroya_id = muroya["data"]["id"]
print(f"  OK {muroya['data']['name']} (id={muroya_id}) ← 解析対象")

ebihara = req("POST", "/players", {
    "name": "海老原 詩織",
    "name_en": "Shiori Ebihara",
    "team": "レゾナック",
    "dominant_hand": "R",
    "birth_year": 1998,
    "is_target": True,
    "notes": "#2 栃木県出身 シングルス '15JOC単優勝",
})
ebihara_id = ebihara["data"]["id"]
print(f"  OK {ebihara['data']['name']} (id={ebihara_id})")

yashiro = req("POST", "/players", {
    "name": "八色 舞",
    "name_en": "Mai Yashiro",
    "team": "レゾナック",
    "dominant_hand": "R",
    "birth_year": 2003,
    "is_target": False,
    "notes": "#8 福岡県出身 ダブルス",
})
yashiro_id = yashiro["data"]["id"]
print(f"  OK {yashiro['data']['name']} (id={yashiro_id})")

sugiyama = req("POST", "/players", {
    "name": "杉山 未来",
    "name_en": "Mirai Sugiyama",
    "team": "レゾナック",
    "dominant_hand": "R",
    "birth_year": 2001,
    "is_target": False,
    "notes": "#3 千葉県出身 ダブルス '23スウェーデンIS複2位",
})
sugiyama_id = sugiyama["data"]["id"]
print(f"  OK {sugiyama['data']['name']} (id={sugiyama_id})")

mizui = req("POST", "/players", {
    "name": "水井 寿々妃",
    "name_en": "Suzuki Mizui",
    "team": "レゾナック",
    "dominant_hand": "R",
    "birth_year": 2005,
    "is_target": False,
    "notes": "#6 奈良県出身 シングルス/ダブルス",
})
mizui_id = mizui["data"]["id"]
print(f"  OK {mizui['data']['name']} (id={mizui_id})")

# 対戦相手（他チーム選手）
hirota = req("POST", "/players", {
    "name": "廣田 彩花",
    "name_en": "Sayaka Hirota",
    "team": "対戦相手チーム",
    "dominant_hand": "R",
    "birth_year": 2000,
    "is_target": False,
    "notes": "対戦相手 シングルス",
})
hirota_id = hirota["data"]["id"]
print(f"  OK {hirota['data']['name']} (id={hirota_id})")

# ─── 2. 試合1: 室屋奏乃 vs 廣田彩花 (シングルス) ────────────────
print("\n[2] 試合1: 室屋奏乃 vs 廣田彩花 (シングルス) 登録中...")

match1 = req("POST", "/matches", {
    "tournament": "S/Jリーグ 2025",
    "tournament_level": "SJL",
    "round": "第3戦",
    "date": "2025-11-15",
    "venue": "大牟田アリーナ",
    "format": "singles",
    "player_a_id": muroya_id,
    "player_b_id": hirota_id,
    "result": "win",
    "final_score": "21-18, 21-16",
    "video_url": "",
    "annotation_status": "in_progress",
    "annotation_progress": 0.0,
    "notes": "S/Jリーグ第3戦 室屋奏乃 vs 廣田彩花",
})
match1_id = match1["data"]["id"]
print(f"  試合1 ID: {match1_id}")

set1 = req("POST", "/sets", {"match_id": match1_id, "set_num": 1})
set1_id = set1["data"]["id"]
print(f"  Set1 ID: {set1_id}")

# シングルスラリーデータ（室屋奏乃のアタック中心の戦術パターン）
RALLIES_M1 = [
    # Rally 1: 室屋A得点 - サービスエース
    ("player_a", "ace", [
        ("player_a", "short_service", None, "NR", False, False),
        ("player_b", "net_shot", "NR", "NL", False, False),
        ("player_a", "push_rush", "NL", "NR", False, False),
    ]),
    # Rally 2: B得点 - クリアからのスマッシュ
    ("player_b", "forced_error", [
        ("player_a", "long_service", None, "BL", False, False),
        ("player_b", "clear", "BL", "BR", False, False),
        ("player_a", "smash", "BR", "ML", False, False),
        ("player_b", "defensive", "ML", "BL", False, False),
        ("player_a", "smash", "BL", "MR", False, False),
        ("player_b", "cant_reach", None, None, False, False),
    ]),
    # Rally 3: 室屋A得点 - アラウンドヘッド
    ("player_a", "ace", [
        ("player_a", "short_service", None, "NC", False, False),
        ("player_b", "flick", "NC", "BC", False, False),
        ("player_a", "around_head", "BC", "NL", False, True),
        ("player_b", "cant_reach", None, None, False, False),
    ]),
    # Rally 4: A得点 - ネット前勝負
    ("player_a", "net", [
        ("player_a", "short_service", None, "NR", False, False),
        ("player_b", "net_shot", "NR", "NL", False, False),
        ("player_a", "cross_net", "NL", "NR", False, False),
        ("player_b", "net_shot", "NR", "NC", False, False),
        ("player_a", "push_rush", "NC", "NR", False, False),
    ]),
    # Rally 5: B得点 - ロブからスマッシュ
    ("player_b", "forced_error", [
        ("player_a", "short_service", None, "NC", False, False),
        ("player_b", "lob", "NC", "BC", True, False),
        ("player_a", "smash", "BC", "ML", False, False),
        ("player_b", "defensive", "ML", "BC", False, False),
        ("player_a", "drop", "BC", "NL", False, False),
        ("player_b", "net_shot", "NL", "NC", False, False),
        ("player_a", "push_rush", "NC", "NR", False, False),
        ("player_b", "cant_reach", None, None, False, False),
    ]),
    # Rally 6: A得点 - バック奥からドロップ
    ("player_a", "unforced_error", [
        ("player_a", "long_service", None, "BL", False, False),
        ("player_b", "clear", "BL", "BR", False, False),
        ("player_a", "drop", "BR", "NR", False, False),
        ("player_b", "net_shot", "NR", "NL", False, False),
        ("player_a", "cross_net", "NL", "NR", False, False),
    ]),
    # Rally 7: B得点
    ("player_b", "out", [
        ("player_a", "short_service", None, "NL", False, False),
        ("player_b", "push_rush", "NL", "NC", False, False),
        ("player_a", "drive", "NC", "MR", False, False),
        ("player_b", "drive", "MR", "ML", False, False),
        ("player_a", "smash", "ML", "MR", False, False),
    ]),
    # Rally 8: A得点 - ハーフスマッシュ
    ("player_a", "forced_error", [
        ("player_a", "short_service", None, "NC", False, False),
        ("player_b", "clear", "NC", "BC", False, False),
        ("player_a", "half_smash", "BC", "ML", False, False),
        ("player_b", "defensive", "ML", "BC", False, False),
        ("player_a", "smash", "BC", "MR", False, False),
        ("player_b", "block", "MR", "NL", False, False),
        ("player_a", "push_rush", "NL", "NR", False, False),
        ("player_b", "cant_reach", None, None, False, False),
    ]),
    # Rally 9: A得点 - バックハンドネット
    ("player_a", "net", [
        ("player_a", "short_service", None, "NL", False, False),
        ("player_b", "net_shot", "NL", "NR", True, False),
        ("player_a", "cross_net", "NR", "NL", True, False),
        ("player_b", "net_shot", "NL", "NC", False, False),
        ("player_a", "push_rush", "NC", "NC", False, False),
    ]),
    # Rally 10: B得点 - アウト
    ("player_b", "unforced_error", [
        ("player_a", "long_service", None, "BC", False, False),
        ("player_b", "clear", "BC", "BL", False, False),
        ("player_a", "smash", "BL", "MC", False, False),
        ("player_b", "lob", "MC", "BC", False, False),
        ("player_a", "smash", "BC", "ML", False, False),
    ]),
    # Rally 11: A得点
    ("player_a", "forced_error", [
        ("player_a", "short_service", None, "NC", False, False),
        ("player_b", "flick", "NC", "BL", False, False),
        ("player_a", "around_head", "BL", "NR", False, True),
        ("player_b", "cant_reach", None, None, False, False),
    ]),
    # Rally 12: A得点
    ("player_a", "ace", [
        ("player_a", "short_service", None, "NR", False, False),
        ("player_b", "net_shot", "NR", "NL", False, False),
        ("player_a", "push_rush", "NL", "NR", False, False),
    ]),
    # Rally 13: B得点
    ("player_b", "net", [
        ("player_a", "short_service", None, "NC", False, False),
        ("player_b", "push_rush", "NC", "NL", False, False),
        ("player_a", "cross_net", "NL", "NR", False, False),
        ("player_b", "drive", "NR", "MC", False, False),
        ("player_a", "drive", "MC", "MR", False, False),
        ("player_b", "smash", "MR", "MR", False, False),
    ]),
    # Rally 14: A得点 - ドライブ戦から制圧
    ("player_a", "forced_error", [
        ("player_a", "short_service", None, "NC", False, False),
        ("player_b", "drive", "NC", "MC", False, False),
        ("player_a", "drive", "MC", "ML", False, False),
        ("player_b", "lob", "ML", "BL", True, False),
        ("player_a", "smash", "BL", "MR", False, False),
        ("player_b", "cant_reach", None, None, False, False),
    ]),
    # Rally 15: A得点 - 最終
    ("player_a", "net", [
        ("player_a", "short_service", None, "NL", False, False),
        ("player_b", "net_shot", "NL", "NC", False, False),
        ("player_a", "push_rush", "NC", "NR", False, False),
    ]),
]

score_a, score_b = 0, 0
for rn, (winner, end_type, strokes) in enumerate(RALLIES_M1, start=1):
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
            "timestamp_sec": float(rn * 30 + i * 3),
        }
        for i, (player, shot_type, hit_zone, land_zone, is_backhand, is_around_head)
        in enumerate(strokes)
    ]

    req("POST", "/strokes/batch", {
        "rally": {
            "set_id": set1_id,
            "rally_num": rn,
            "server": "player_a",
            "winner": winner,
            "end_type": end_type,
            "rally_length": len(strokes),
            "score_a_after": new_score_a,
            "score_b_after": new_score_b,
            "is_deuce": new_score_a >= 20 and new_score_b >= 20,
            "video_timestamp_start": float(rn * 30),
        },
        "strokes": stroke_list,
    })
    score_a, score_b = new_score_a, new_score_b
    print(f"  Rally {rn:2d}: {winner.replace('player_', 'P')} 得点 ({end_type}) "
          f"{len(strokes)}球 → {score_a}-{score_b}")

set_end_winner = "player_a" if score_a > score_b else "player_b"
req("PUT", f"/sets/{set1_id}/end", {
    "winner": set_end_winner,
    "score_a": score_a,
    "score_b": score_b,
})
print(f"  Set1 終了: {score_a}-{score_b} ({set_end_winner.replace('player_', 'P')} 勝利)")

# ─── 3. 試合2: 室屋奏乃 vs 水井寿々妃 (内部練習) ────────────────
print("\n[3] 試合2: 室屋奏乃 vs 水井寿々妃 (チーム内練習試合) 登録中...")

match2 = req("POST", "/matches", {
    "tournament": "チーム内練習試合",
    "tournament_level": "その他",
    "round": "練習",
    "date": "2025-10-20",
    "venue": "レゾナック大牟田練習場",
    "format": "singles",
    "player_a_id": muroya_id,
    "player_b_id": mizui_id,
    "result": "win",
    "final_score": "21-14",
    "video_url": "",
    "annotation_status": "in_progress",
    "annotation_progress": 0.0,
    "notes": "チーム内紅白戦",
})
match2_id = match2["data"]["id"]
print(f"  試合2 ID: {match2_id}")

set2 = req("POST", "/sets", {"match_id": match2_id, "set_num": 1})
set2_id = set2["data"]["id"]

RALLIES_M2 = [
    ("player_a", "ace", [
        ("player_a", "short_service", None, "NC", False, False),
        ("player_b", "net_shot", "NC", "NL", False, False),
        ("player_a", "push_rush", "NL", "NR", False, False),
    ]),
    ("player_a", "forced_error", [
        ("player_a", "long_service", None, "BC", False, False),
        ("player_b", "clear", "BC", "BR", False, False),
        ("player_a", "smash", "BR", "ML", False, False),
        ("player_b", "cant_reach", None, None, False, False),
    ]),
    ("player_b", "net", [
        ("player_a", "short_service", None, "NL", False, False),
        ("player_b", "push_rush", "NL", "NC", False, False),
        ("player_a", "drive", "NC", "ML", False, False),
        ("player_b", "drive", "ML", "MR", False, False),
        ("player_a", "smash", "MR", "MR", False, False),
    ]),
    ("player_a", "net", [
        ("player_a", "short_service", None, "NR", False, False),
        ("player_b", "net_shot", "NR", "NL", True, False),
        ("player_a", "cross_net", "NL", "NR", False, False),
    ]),
    ("player_a", "ace", [
        ("player_a", "short_service", None, "NC", False, False),
        ("player_b", "flick", "NC", "BL", False, False),
        ("player_a", "around_head", "BL", "NL", False, True),
        ("player_b", "cant_reach", None, None, False, False),
    ]),
    ("player_b", "forced_error", [
        ("player_a", "short_service", None, "NC", False, False),
        ("player_b", "lob", "NC", "BC", True, False),
        ("player_a", "smash", "BC", "MR", False, False),
        ("player_b", "defensive", "MR", "BL", False, False),
        ("player_a", "half_smash", "BL", "MC", False, False),
        ("player_b", "cant_reach", None, None, False, False),
    ]),
    ("player_a", "unforced_error", [
        ("player_a", "long_service", None, "BR", False, False),
        ("player_b", "clear", "BR", "BC", False, False),
        ("player_a", "drop", "BC", "NR", False, False),
        ("player_b", "net_shot", "NR", "NC", False, False),
        ("player_a", "push_rush", "NC", "NL", False, False),
    ]),
    ("player_a", "forced_error", [
        ("player_a", "short_service", None, "NL", False, False),
        ("player_b", "flick", "NL", "BC", False, False),
        ("player_a", "smash", "BC", "ML", False, False),
        ("player_b", "defensive", "ML", "BL", False, False),
        ("player_a", "smash", "BL", "MC", False, False),
        ("player_b", "cant_reach", None, None, False, False),
    ]),
]

sa, sb = 0, 0
for rn, (winner, end_type, strokes) in enumerate(RALLIES_M2, start=1):
    nsa = sa + (1 if winner == "player_a" else 0)
    nsb = sb + (1 if winner == "player_b" else 0)
    sl = [
        {
            "stroke_num": i + 1, "player": p, "shot_type": st,
            "hit_zone": hz, "land_zone": lz,
            "is_backhand": bh, "is_around_head": ah,
            "above_net": None, "is_cross": False,
            "timestamp_sec": float(rn * 25 + i * 3),
        }
        for i, (p, st, hz, lz, bh, ah) in enumerate(strokes)
    ]
    req("POST", "/strokes/batch", {
        "rally": {
            "set_id": set2_id, "rally_num": rn, "server": "player_a",
            "winner": winner, "end_type": end_type,
            "rally_length": len(strokes),
            "score_a_after": nsa, "score_b_after": nsb,
            "is_deuce": nsa >= 20 and nsb >= 20,
            "video_timestamp_start": float(rn * 25),
        },
        "strokes": sl,
    })
    sa, sb = nsa, nsb
    print(f"  Rally {rn:2d}: {winner.replace('player_', 'P')} 得点 ({end_type}) → {sa}-{sb}")

req("PUT", f"/sets/{set2_id}/end", {
    "winner": "player_a" if sa > sb else "player_b",
    "score_a": sa, "score_b": sb,
})
print(f"  Set 終了: {sa}-{sb}")

# ─── 完了 ────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("  完了！")
print(f"  選手:")
print(f"    室屋 奏乃     id={muroya_id}  ← 解析対象 (is_target=True)")
print(f"    海老原 詩織   id={ebihara_id}")
print(f"    八色 舞       id={yashiro_id}")
print(f"    杉山 未来     id={sugiyama_id}")
print(f"    水井 寿々妃   id={mizui_id}")
print(f"    廣田 彩花     id={hirota_id}")
print(f"  試合:")
print(f"    Match {match1_id}: 室屋奏乃 vs 廣田彩花  (S/Jリーグ 2025, ラリー{len(RALLIES_M1)}本)")
print(f"    Match {match2_id}: 室屋奏乃 vs 水井寿々妃 (練習試合, ラリー{len(RALLIES_M2)}本)")
print("=" * 60)
print(f"\nアノテーター（試合{match1_id}）: アプリの試合一覧から選択してください")
