"""テンプレ生成。LLM 不要・決定論的。

選手安全ルール:
- ja は「弱点」禁止 → 「伸びしろ」/「成長余地」
- en は "weakness" 禁止 → "growth area" / "next step"
ConfidenceBadge と歩調を合わせるため最低サンプル N をチェック。
"""
from __future__ import annotations

from datetime import datetime, timezone

from backend.analysis.insights.types import (
    InsightContext,
    InsightItem,
    InsightResult,
)

# 最低サンプル N (ConfidenceBadge の最低警告ラインに合わせる: <500 でも emit するが、
# ここでは「データが薄すぎる」状態のカットオフを 30 ラリーに設定)
_MIN_SAMPLE_N = 30


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fmt_shot_label(key: str, lang: str) -> str:
    """ショット内部キー → 表示ラベル。"""
    table_ja = {
        "smash": "スマッシュ",
        "clear": "クリアー",
        "drop": "ドロップ",
        "drive": "ドライブ",
        "net": "ネット",
        "push": "プッシュ",
        "lob": "ロブ",
        "serve": "サーブ",
    }
    table_en = {
        "smash": "smash",
        "clear": "clear",
        "drop": "drop",
        "drive": "drive",
        "net": "net shot",
        "push": "push",
        "lob": "lob",
        "serve": "serve",
    }
    if lang == "ja":
        return table_ja.get(key, key)
    return table_en.get(key, key)


def _confidence_from_sample(n: int) -> float:
    """N=30 → 0.4, N=500 → 0.7, N=2000+ → 0.9 程度に丸める。"""
    if n < _MIN_SAMPLE_N:
        return 0.0
    if n >= 2000:
        return 0.9
    if n >= 500:
        return 0.7 + (n - 500) / 1500 * 0.2
    return 0.4 + (n - _MIN_SAMPLE_N) / (500 - _MIN_SAMPLE_N) * 0.3


class TemplateGenerator:
    """テンプレベース。`ctx.analytics` から 2-3 件を抽出。

    期待する analytics スキーマ (caller が用意):
    {
      "shot_win_loss": [
         {"shot": "smash", "win_rate": 0.62, "delta_pp": +4.0, "sample_n": 120,
          "alt_shot": "drop"},
         ...
      ],
      "recent_form": {"win_rate": 0.58, "delta_pp": +6.0, "sample_n": 40},
      "growth_timeline_delta": {"metric": "serve_win_rate",
         "delta_pp": +3.5, "sample_n": 80},
    }
    """

    name = "template"

    def generate(self, ctx: InsightContext) -> InsightResult:
        lang = ctx.get("lang", "ja")
        analytics = ctx.get("analytics") or {}
        player_id = ctx.get("player_id")
        period_days = ctx.get("period_days", 30)
        items: list[InsightItem] = []

        # ── 1) ショット別勝率の伸び ─────────────────────────────────
        shots = analytics.get("shot_win_loss") or []
        # win_rate 高い順 + sample_n 十分なものから 1 件
        shots_sorted = sorted(
            [s for s in shots if int(s.get("sample_n", 0)) >= _MIN_SAMPLE_N],
            key=lambda s: float(s.get("win_rate", 0.0)),
            reverse=True,
        )
        if shots_sorted:
            top = shots_sorted[0]
            shot_label = _fmt_shot_label(str(top.get("shot", "")), lang)
            alt_label = _fmt_shot_label(str(top.get("alt_shot", "drop")), lang)
            pct = int(round(float(top.get("win_rate", 0.0)) * 100))
            delta_pp = float(top.get("delta_pp", 0.0))
            n = int(top.get("sample_n", 0))
            if lang == "ja":
                prose = (
                    f"{shot_label}の勝率は{pct}%。直近{period_days}日より{delta_pp:+.1f}pp。"
                    f"次は{alt_label}を増やすと伸びしろがあります。"
                )
            else:
                prose = (
                    f"Your {shot_label} win rate is {pct}%, {delta_pp:+.1f}pp vs. the last "
                    f"{period_days} days. Adding more {alt_label} would broaden your growth area."
                )
            items.append(
                InsightItem(
                    id="growth_shot",
                    prose=prose,
                    evidence_path=f"/api/analysis/shot_win_loss?player_id={player_id}",
                    confidence=_confidence_from_sample(n),
                    metric={
                        "shot": top.get("shot"),
                        "win_rate": top.get("win_rate"),
                        "delta_pp": delta_pp,
                        "sample_n": n,
                        "alt_shot": top.get("alt_shot"),
                    },
                )
            )

        # ── 2) 直近フォーム ───────────────────────────────────────────
        rf = analytics.get("recent_form") or {}
        n = int(rf.get("sample_n", 0))
        if n >= _MIN_SAMPLE_N:
            pct = int(round(float(rf.get("win_rate", 0.0)) * 100))
            delta_pp = float(rf.get("delta_pp", 0.0))
            if lang == "ja":
                prose = (
                    f"直近{period_days}日の勝率は{pct}% ({delta_pp:+.1f}pp)。"
                    f"このペースを次の週も維持すると、安定の成長余地が広がります。"
                )
            else:
                prose = (
                    f"Recent {period_days}-day win rate is {pct}% ({delta_pp:+.1f}pp). "
                    f"Holding this pace next week opens a steady growth area for consistency."
                )
            items.append(
                InsightItem(
                    id="consistency_lift",
                    prose=prose,
                    evidence_path=f"/api/analysis/recent_form?player_id={player_id}",
                    confidence=_confidence_from_sample(n),
                    metric={"win_rate": rf.get("win_rate"), "delta_pp": delta_pp, "sample_n": n},
                )
            )

        # ── 3) 成長タイムライン delta ─────────────────────────────
        gt = analytics.get("growth_timeline_delta") or {}
        n = int(gt.get("sample_n", 0))
        if n >= _MIN_SAMPLE_N:
            metric_key = str(gt.get("metric", "win_rate"))
            delta_pp = float(gt.get("delta_pp", 0.0))
            if lang == "ja":
                metric_ja = {
                    "win_rate": "勝率",
                    "serve_win_rate": "サーブ勝率",
                }.get(metric_key, metric_key)
                prose = (
                    f"{metric_ja}は前期間より{delta_pp:+.1f}pp。"
                    f"少し追い風です。次の伸びしろは継続です。"
                )
            else:
                metric_en = {
                    "win_rate": "win rate",
                    "serve_win_rate": "serve win rate",
                }.get(metric_key, metric_key)
                prose = (
                    f"Your {metric_en} moved {delta_pp:+.1f}pp vs. the previous period. "
                    f"A small tailwind — the next growth area is continuity."
                )
            items.append(
                InsightItem(
                    id="growth_timeline",
                    prose=prose,
                    evidence_path=f"/api/analysis/growth_timeline?player_id={player_id}",
                    confidence=_confidence_from_sample(n),
                    metric={
                        "metric": metric_key,
                        "delta_pp": delta_pp,
                        "sample_n": n,
                    },
                )
            )

        # 信頼度の高い順に最大 3 件
        items = sorted(items, key=lambda it: it["confidence"], reverse=True)[:3]

        return InsightResult(
            items=items,
            generator=self.name,
            generated_at=_now_iso(),
        )
