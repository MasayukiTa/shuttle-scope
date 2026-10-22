"""player ロールに出してよい出力の定義 (許可リスト / 禁止パスの単一の置き場)。

CLAUDE.md 非交渉ルール:
  - player に生の勝率型判定 / 直接 EPV / 直接の弱点提示を出さない
  - 他人 (対戦相手・パートナー) の個人情報・体調を出さない

これまで禁止の根拠が main.py のミドルウェア集合・包括レポートの拒否リスト・各レポートの
個別処理に分散しており、入口ごとに規則が食い違っていた (shot_win_loss / pre_loss_patterns は
包括レポートでは削除されるのに直接ルートは player に 200 を返す、等)。
このモジュールに集約し、ミドルウェア・ルート依存・サービス層のすべてがここを参照する。
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import HTTPException, Request

# ─── 1. player 禁止の /api/analysis/* パス (単一の定義) ──────────────────────
# analysis_research / analysis_spine / analysis_bundle の全ルートは main.py 側で
# ルーターから自動収集する。ここには「stable / advanced 内の個別パス」を列挙する。
PLAYER_FORBIDDEN_NAMED_ANALYSIS_PATHS: frozenset[str] = frozenset({
    # weakness / vulnerability
    "/api/analysis/received_vulnerability",
    "/api/analysis/received_vulnerability/zone_detail",
    "/api/analysis/opponent_vulnerability",
    # 対戦相手スカウティング (rival_comparison)
    "/api/analysis/opponent_card",
    "/api/analysis/opponent_stats",
    # 直接 win_rate vs opponent
    "/api/analysis/win_loss_comparison",
    "/api/analysis/partner_comparison",
    # advanced-tier opponent 系 (analysis_advanced.py)
    "/api/analysis/opponent_type_affinity",
    "/api/analysis/opponent_adaptive_shots",
    "/api/analysis/opponent_policy",
    # 球種別の得点/失点 = 生の勝敗内訳 (包括レポートでは従来から player に対し削除済み)
    "/api/analysis/shot_win_loss",
    # 失点前の打球パターン = 直接の弱点提示 (同上)
    "/api/analysis/pre_loss_patterns",
})


def deny_player_on_forbidden_named_path(request: Request) -> None:
    """FastAPI 依存: 禁止パスへの player のリクエストを 403 にする。

    ミドルウェアは `_PLAYER_FORBIDDEN_ANALYSIS_PATHS` で同じ拒否をするが、ミドルウェアは
    経路が増えたり差し替わったりすると外れる。この依存はルーターに付けておくだけで、
    PLAYER_FORBIDDEN_NAMED_ANALYSIS_PATHS に載った全ルートをルート自身が拒否する。
    パスが禁止定義に無ければ何もしない (ほかのロールと player の他ルートは従来どおり)。
    """
    if request.url.path not in PLAYER_FORBIDDEN_NAMED_ANALYSIS_PATHS:
        return
    from backend.utils.auth import get_auth  # 循環 import を避けるため遅延 import

    if get_auth(request).is_player:
        raise HTTPException(status_code=403, detail="この解析は player ロールでは参照できません")


# ─── 2. 包括レポート: player 向け許可リスト ─────────────────────────────────
# 拒否リスト方式は新しい節が増えるたびに漏れた (rally_length_winrate 等が実際に漏れていた)。
# player に見せる節はここに明示したものだけ。各値は「節の中身 (data.data)」を
# player 向けに縮約する関数。meta (sample_size / confidence) は縮約対象外で常に残る。

def _drop_keys(*keys: str) -> Callable[[Any], Any]:
    def _f(inner: Any) -> Any:
        if isinstance(inner, dict):
            return {k: v for k, v in inner.items() if k not in keys}
        if isinstance(inner, list):
            return [_f(x) for x in inner]
        return inner
    return _f


def _keep_keys(*keys: str) -> Callable[[Any], Any]:
    def _f(inner: Any) -> Any:
        if isinstance(inner, dict):
            return {k: v for k, v in inner.items() if k in keys}
        return inner
    return _f


def _tournament_levels(inner: Any) -> Any:
    if isinstance(inner, dict) and isinstance(inner.get("levels"), list):
        return {**inner, "levels": _drop_keys("win_rate")(inner["levels"])}
    return inner


def _identity(inner: Any) -> Any:
    return inner


def _first_return(inner: Any) -> Any:
    """ファーストリターン: 直接 API (/api/analysis/first_return_analysis) と同じ規則で縮約する。

    落とすキーは player_response_sanitiser の宣言テーブルが唯一の定義。ここで別のキー集合を
    持つと、直接 API と包括レポートで規則が食い違う (監査 #949)。
    """
    from backend.utils.player_response_sanitiser import sanitize_for_player

    return sanitize_for_player("/api/analysis/first_return_analysis", inner)


PLAYER_COMPREHENSIVE_ALLOWED_SECTIONS: dict[str, Callable[[Any], Any]] = {
    # 件数・ラリー長・終了種別の分布のみ (win_rate / win_by_end_type / server_win_rate は落とす)
    "descriptive": _keep_keys(
        "total_matches", "total_rallies", "avg_rally_length",
        "end_type_distribution", "rally_length_histogram",
    ),
    "heatmap_hit": _identity,
    "heatmap_land": _identity,
    "shot_types": _drop_keys("win_rate", "winner_end_rate", "winner_end_count"),
    "set_comparison": _drop_keys("win_rate"),
    "first_return": _first_return,
    "tournament_comparison": _tournament_levels,
    # 得点前パターン (成功パターンの傾向。伸びしろ側の情報)
    "pre_win_patterns": _identity,
}

# 包括レポート matches[] で player に残すキー (勝敗・スコア・相手ID・uuid は含めない)
PLAYER_COMPREHENSIVE_MATCH_KEYS: tuple[str, ...] = (
    "id", "date", "tournament", "tournament_level", "round", "format",
    "rally_count", "set_count", "annotation_status", "annotation_progress",
)


def apply_player_comprehensive_view(sections: dict[str, dict]) -> dict[str, dict]:
    """包括レポートの sections を player 向け許可リストで絞る。

    許可リスト外の節は丸ごと落とす。許可された節は、成功 (ok) のときだけ中身を縮約し、
    `{"success", "data", "meta"}` の meta はそのまま残す。
    """
    out: dict[str, dict] = {}
    for name, fn in PLAYER_COMPREHENSIVE_ALLOWED_SECTIONS.items():
        sec = sections.get(name)
        if sec is None:
            continue
        if not sec.get("ok"):
            out[name] = sec
            continue
        wrapped = sec.get("data")
        if isinstance(wrapped, dict) and "data" in wrapped:
            wrapped = {**wrapped, "data": fn(wrapped["data"])}
        else:
            wrapped = fn(wrapped)
        out[name] = {**sec, "data": wrapped}
    return out


def player_match_row(row: dict) -> dict:
    return {k: row.get(k) for k in PLAYER_COMPREHENSIVE_MATCH_KEYS}


# ─── 3. export/package: player 向けの縮約 ───────────────────────────────────

def redact_export_package_for_player(
    payload: dict, own_player_id: Optional[int]
) -> dict:
    """player が試合 export package から持ち出せないものを落とす。

    落とす: 勝敗・最終スコア・セット勝者/スコア・ラリー勝者/スコア・ラリー勝数・
    自分以外の選手プロフィール (名前・所属・国籍・生年・uuid)・EPV。
    conditions は _build_match_package 側で本人分のみ + 同意フィルタ済み。
    """
    out = dict(payload)
    if isinstance(out.get("match"), dict):
        out["match"] = {
            k: v for k, v in out["match"].items() if k not in ("result", "final_score")
        }
    if isinstance(out.get("players"), list):
        out["players"] = [
            p for p in out["players"]
            if isinstance(p, dict) and own_player_id is not None and p.get("id") == own_player_id
        ]
    if isinstance(out.get("sets"), list):
        out["sets"] = [
            {k: v for k, v in s.items() if k not in ("winner", "score_a", "score_b")}
            for s in out["sets"]
        ]
    if isinstance(out.get("rallies"), list):
        drop = ("winner", "score_a_before", "score_b_before", "score_a_after", "score_b_after")
        out["rallies"] = [
            {k: v for k, v in r.items() if k not in drop} for r in out["rallies"]
        ]
    if isinstance(out.get("strokes"), list):
        out["strokes"] = [
            {k: v for k, v in s.items() if k != "epv"} for s in out["strokes"]
        ]
    if isinstance(out.get("reports"), dict):
        out["reports"] = {
            k: v for k, v in out["reports"].items()
            if k not in ("rally_wins_a", "rally_wins_b", "result", "final_score")
        }
    return out
