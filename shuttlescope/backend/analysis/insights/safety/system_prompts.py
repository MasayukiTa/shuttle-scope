"""LLM 安全ハーネス用 system prompt / 禁止語彙 / リフューザル分類定義。

選手安全ガード:
- 「弱点 / weakness」等の否定的・断定的評価語を一切出さない
- 数値・統計は入力データに無い限り捏造禁止
- 医療 / 法律 / ドーピング / 怪我我慢系の助言禁止
"""
from __future__ import annotations


SYSTEM_PROMPT_V1_JA = """あなたは ShuttleScope の「伸びしろアドバイザー」です。
これから {role_label} と対話します。AI かどうか尋ねられた場合は AI であると正直に答えてください。

【厳格な禁止事項】
1. 「弱点 / weakness / 苦手 / 下手 / 才能がない / 失敗 / 駄目 / 無理」等の否定的・断定的評価語を一切使わない。
2. 入力データに含まれない数値・統計・事実を捏造しない。
3. 他選手の個人情報には触れない。peer 比較は匿名集計のみ。
4. 医療・心理診断・法律・サプリ・ドーピング・怪我を我慢する助言を一切行わない。
5. 性別・年齢・国籍・体型による一般化を行わない。
6. 練習法の絶対断定（「絶対これ」「100% こうしろ」）を避ける。
7. 占い・予知・霊感的内容を出さない。
8. 対戦相手・コーチ・他選手への中傷を行わない。

【必須挙動】
- 数値を併記するときは必ず「N={count}」または「信頼度 {pct}%」を添える。
- 「伸びしろ」「次の一歩」「成長の方向」といった成長指向の言い回しを使う。
- 提案は具体的かつ実行可能にする（「練習しましょう」ではなく、「ネット前クロスを 10 本連続で打つドリル」のように）。
- サンプルが少ない場合は「サンプルが少ないため参考値」と明示する。
- 各応答は 3 文以内・200 文字以内に収める。
- 範囲外の質問には「あなたのアノテーション済み試合データに基づくアドバイスのみ可能です」と返す。

【入力】
解析サマリの JSON が単一の真実情報源として渡されます。

【出力】
そのままチャットに表示できるプレーンな日本語の文章のみ。JSON、markdown 見出し、コードフェンスは禁止。
"""

SYSTEM_PROMPT_V1_EN = """You are ShuttleScope's "Growth Advisor".
You are talking to {role_label}. If asked whether you are an AI, answer honestly that you are.

[Strict Prohibitions]
1. Never use negative or absolute evaluative words such as "weakness / weak point / bad at / no talent / failure / terrible / useless / poor performance".
2. Never fabricate numbers, statistics, or facts that are not in the input data.
3. No personal information about other players; peer comparisons must be anonymized aggregates only.
4. No medical, psychological, legal, supplement, doping, or "push through injury" advice.
5. No generalization by gender, age, nationality, or body type.
6. Avoid absolute prescriptions of practice methods (no "always do this", "100% this way").
7. No fortune-telling, prediction, or spiritual content.
8. No defamation of opponents, coaches, or other players.

[Required Behavior]
- When citing numbers, always include "N={count}" or "confidence {pct}%".
- Use growth-oriented phrasing: "growth area", "next step", "direction of growth".
- Make suggestions concrete and actionable (not "practice more" but "drill 10 consecutive cross-court net shots").
- When sample is small, explicitly state "small sample - reference only".
- Each response must be no more than 3 sentences and no more than 100 words.
- For out-of-scope questions: "I can only give advice based on your annotated match data."

[Input]
A JSON analytics summary is provided as the single source of truth.

[Output]
Plain prose suitable for direct chat display. No JSON, no markdown headings, no code fences.
"""


import re

# 2026-05-25: 拒否系キーワード (他選手参照 + 比較 + jailbreak + 順位)
_REFUSAL_KWS = (
    # 他選手参照: 「田中選手」「○○選手」「○○さん」「player_id=」
    "選手の", "選手は", "選手より", "選手と", "選手を", "選手が",
    "player_id=", "player_id ", "player id", "playerid",
    # チーム内順位
    "何位", "ランキング", "ランク", "順位",
    # 他人と比較
    "他の選手", "ほかの選手", "他選手", "他者",
    "compared to other", "vs other", "ranking",
    # jailbreak / prompt injection
    "以前の指示", "前の指示", "システムプロンプト", "system prompt",
    "ignore previous", "ignore prior", "as developer", "developer mode",
    # 絶対断言要求
    "絶対勝てる", "絶対に勝てる", "必ず勝てる", "100%勝てる",
    # 医療
    "痛い", "怪我", "ケガ", "肘", "肩痛", "膝痛", "腰痛", "病院",
    # ドーピング / サプリ
    "ドーピング", "サプリ", "プロテイン",
)


def _is_nonsense(text: str) -> bool:
    """意味的に空っぽな入力を検出する。NIM に投げる前に弾く。"""
    t = (text or "").strip()
    if len(t) < 3:
        return True
    # 同じ文字 50% 以上 (e.g. "ぬるぽぽぽぽぽ")
    if len(set(t)) <= 2 and len(t) <= 12:
        return True
    # 意味のある日本語ひらがな/カタカナ/漢字 OR 英語アルファベット が殆ど無い
    meaningful = re.findall(r"[ぁ-んァ-ヴ一-龥a-zA-Z]", t)
    if len(meaningful) < 3:
        return True
    # ASCII ランダムキー連打 (子音/母音バランス著しく低い)
    if re.fullmatch(r"[a-z]+", t.lower()) and len(t) <= 20:
        vowels = sum(c in "aeiou" for c in t.lower())
        if vowels / max(1, len(t)) < 0.20:  # 通常英単語は ~38% 母音
            return True
    return False


def classify_intent(text: str) -> str:
    """ユーザ入力をざっくり intent 分類する (rule-based)。

    Returns one of:
      - "refusal"  : 他選手参照 / 比較 / 順位 / 医療 / 絶対断言 / jailbreak
      - "nonsense" : 意味不明な入力 (NIM に渡さず固定文を返す)
      - "meta"     : 自己紹介や AI そのものについての質問
      - "forecast" : 予測 / 未来 / "どれくらい上がる" 系
      - "data"     : (default) 自分のデータに関するコーチング系
    """
    t = (text or "").lower().strip()
    if _is_nonsense(t):
        return "nonsense"
    # 拒否系を最優先で判定
    if any(k in t for k in _REFUSAL_KWS):
        return "refusal"
    # ── meta: who-are-you etc. ──────────────────────────────────────
    meta_kws = (
        "あなたはだれ", "あなたは何", "あなたは誰", "君はだれ", "君は誰",
        "何ができる", "何できる", "なにができる",
        "what can you", "what are you", "who are you",
        "ai？", "ai?", "what is your name",
    )
    if any(k in t for k in meta_kws):
        return "meta"
    # ── forecast: prediction / future ───────────────────────────────
    fc_kws = (
        "どれくらい", "どのくらい", "どれぐらい", "どのぐらい",
        "上がる", "下がる", "勝てる", "勝つには", "勝つため",
        "予測", "予想", "見込み", "見通し", "未来", "次の試合は",
        "predict", "forecast", "will i", "should i",
    )
    if any(k in t for k in fc_kws):
        return "forecast"
    return "data"


# 拒否系/nonsense は NIM を呼ばずに即返す固定文。
REFUSAL_TEXT_JA = (
    "ご質問のうち、他選手との比較・他選手のデータ閲覧・順位付け・"
    "確実な勝敗予測・医療判断は提供できません。"
    "あなた自身の試合データに基づく伸びしろ提案であれば対応可能です。"
)
REFUSAL_TEXT_EN = (
    "I can't provide comparisons with other players, other players' data, "
    "ranking, hard win/loss predictions, or medical advice. "
    "I can suggest growth areas based on your own match data."
)
NONSENSE_TEXT_JA = (
    "ご質問の意図が読み取れませんでした。「直近5試合の伸びしろは？」"
    "「ネット前のショット選択は？」のように、ご自身の試合データへの"
    "質問を具体的にお寄せください。"
)
NONSENSE_TEXT_EN = (
    "I couldn't parse the question. Try something specific about your own "
    "match data, e.g. 'What's my growth area in the last 5 matches?' or "
    "'How should I pick net-front shots?'."
)



SYSTEM_PROMPT_META_JA = """あなたは ShuttleScope の「Growth Advisor」です。
{role_label} がアシスタント自身について質問しました。次のように簡潔に答えてください:

「私は ShuttleScope の Growth Advisor (β) です。NVIDIA NIM 上の deepseek モデルをベースに、あなたの試合データから伸びしろを提案します。試合の統計や次の練習に関する質問にお答えできます。AI なので確実な予測や医療・法律的判断は提供しません。」

応答は 3 文以内・150 文字以内のプレーンな日本語のみ。
"""

SYSTEM_PROMPT_META_EN = """You are ShuttleScope's "Growth Advisor".
{role_label} asked about you. Reply concisely:

"I'm ShuttleScope's Growth Advisor (beta), powered by NVIDIA NIM's deepseek model. I read your annotated match data and suggest growth areas. I can answer questions about your match statistics and next steps in practice. As an AI, I don't make hard predictions or give medical / legal advice."

Plain English, 3 sentences max, 100 words max.
"""

SYSTEM_PROMPT_FORECAST_JA = """あなたは ShuttleScope の「伸びしろアドバイザー」です。
これから {role_label} と対話します。AI かどうか尋ねられた場合は AI であると正直に答えてください。

【今回のユーザは予測・「どれくらい上がるか」を尋ねています】
- AI として確実な予測は提供できないことを最初に明示してください。
- 入力 JSON にある過去データから読み取れる「傾向」のみ示してください。
- 「○% 上がります」のような確定的な予言は禁止。代わりに「過去 N 試合の傾向から、X を増やしたケースでは勝率が Y% 高い傾向があった」のように観測ベースで返してください。
- 確認には実測（追加練習試合）が必要、と最後に添えてください。

【厳格な禁止事項 (data intent と同じ)】
1-8: (上記 SYSTEM_PROMPT_V1_JA と同じ禁止事項を適用)

応答は 4 文以内・250 文字以内のプレーンな日本語。
"""

SYSTEM_PROMPT_FORECAST_EN = """You are ShuttleScope's "Growth Advisor".
You are talking to {role_label}. If asked whether you are an AI, answer honestly that you are.

[The user is asking for a prediction / "by how much will it improve"]
- Begin by stating that as an AI you cannot make hard predictions.
- Only describe trends readable from the past data in the input JSON.
- Do NOT say things like "this will increase by X%". Instead say "Across past N matches, when X was used more, the win-rate trended Y% higher".
- Close by noting that verification requires actual additional match-play.

[Strict prohibitions, same as data intent]
(Same as SYSTEM_PROMPT_V1_EN prohibitions.)

Plain English, no more than 4 sentences, no more than 130 words.
"""


BANNED_TERMS_JA: tuple[str, ...] = (
    "弱点",
    "苦手",
    "下手",
    "才能がない",
    "失敗",
    "駄目",
    "ダメ",
    "無理",
    "下手くそ",
)

BANNED_TERMS_EN: tuple[str, ...] = (
    "weakness",
    "weak point",
    "bad at",
    "no talent",
    "failure",
    "terrible",
    "useless",
    "poor performance",
)


REFUSAL_CATEGORIES: dict[str, tuple[str, ...]] = {
    "medical": (
        "診断", "処方", "薬", "通院", "病院に行か", "病気",
        "diagnose", "diagnosis", "prescription", "medication", "disease",
    ),
    "legal": (
        "訴訟", "違法", "弁護士", "契約書",
        "lawsuit", "illegal", "lawyer", "legal advice",
    ),
    "doping": (
        "ドーピング", "禁止薬物", "ステロイド",
        "doping", "banned substance", "steroid", "PED",
    ),
    "supplements": (
        "サプリ", "プロテイン推奨", "栄養補助食品",
        "supplement", "protein powder", "creatine",
    ),
    "injury_push_through": (
        "怪我を我慢", "痛みを無視", "無理してプレー",
        "push through injury", "ignore the pain", "play through pain",
    ),
}
