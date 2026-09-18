"""Insight 共通型定義。"""
from __future__ import annotations

from typing import Optional, TypedDict, NotRequired


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
