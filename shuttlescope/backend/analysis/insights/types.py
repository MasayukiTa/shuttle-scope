"""Insight 共通型定義。"""
from __future__ import annotations

import sys
from typing import Optional, TypedDict

# `NotRequired` は 3.11 以降の `typing` にしかない。これ 1 行のために
# **backend.main を import するテスト 112 ファイルが 3.10 で収集できず**、
# ローカルの回帰確認がその範囲を丸ごと素通りしていた
# （その状態で push して CI を 1 回赤くした）。
# 本番も CI も 3.12 のまま。ここは収集できるようにするためだけの分岐。
if sys.version_info >= (3, 11):
    from typing import NotRequired
else:  # pragma: no cover - 3.10 でのテスト収集用
    from typing_extensions import NotRequired


class InsightContext(TypedDict):
    """ジェネレータに渡す入力コンテキスト。"""
    player_id: int
    period_days: int
    analytics: dict  # caller が事前 fetch した解析スナップショット
    role: str        # 'player' / 'coach' / 'analyst' / 'admin'
    lang: str        # 'ja' / 'en'
    # 2026-05-25: 生のユーザ入力テキスト。ExternalApiGenerator が intent
    #   分類 (meta / forecast / data) と prompt 切替に使う。
    user_text: NotRequired[str]


class InsightItem(TypedDict):
    """1 行のインサイト。"""
    id: str               # 'growth_smash', 'consistency_lift', ...
    prose: str            # 2-3 文の日本語または英語
    evidence_path: str    # e.g. '/api/analysis/shot_win_loss?player_id=12'
    # None = 「信頼度という概念が当てはまらない出力」。定型の拒否文や
    # ナンセンス短絡のように、分析を経ていない応答に数値を付けると
    # UI が「信頼度 100%」と表示してしまう。UI は数値でないとき
    # バッジを描かない (ChatMessageBubble.tsx:39-42)。
    confidence: Optional[float]   # 0..1、または None
    metric: dict          # prose の裏付け生数値


class InsightResult(TypedDict):
    """ジェネレータ出力。"""
    items: list[InsightItem]
    generator: str        # 'template' or future 'nvidia-nemotron-70b', 'openai-gpt-4o', ...
    generated_at: str     # iso 8601
