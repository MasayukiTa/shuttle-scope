"""player ロール向け応答サニタイザ (純関数 + 宣言的テーブル)。

CLAUDE.md 非交渉ルール: player に 生の絶対勝率判定 / 勝敗結果 / 直接の弱点提示 /
直接 EPV / research tier の出力を見せない。フロントは該当カードを隠しているが、
API が返す限り DevTools / 直接呼び出しで取得できる (監査 2026-10-15 行 8-14)。

個々のルートを直す代わりに、ここの 1 つのテーブル (PLAYER_RESPONSE_RULES) で
「どのパスから、どのキーを落とすか」を宣言し、単一の関門 (ASGI ミドルウェア
backend/middleware/player_response_sanitiser.py) が role=player のときだけ適用する。

設計メモ:
  - 落とすのは「キー」(再帰)。sample_size / n / rally_count / confidence 等の不確実性メタは触らない。
  - 新しいルートが増えても、テーブルに 1 行足すだけでよい。
  - 録画 (アノテーション) 経路 /api/rallies/match, /api/sets/match, /api/annotation/*/state は
    入力ツールが得点・勝者を使って再開するため、ここでは意図的に対象外
    (PLAYER_ANNOTATION_FLOW_PATHS)。方針はオーナー判断。
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

# ─── 共通のキー集合 ──────────────────────────────────────────────────────────
# ラリー / セットの勝敗・スコアを表すキー (どのルートでも「結果」を意味する)
_RALLY_OUTCOME_KEYS: frozenset[str] = frozenset({
    "winner", "score_a_before", "score_b_before", "score_a_after", "score_b_after",
})
_WIN_RATE_KEYS: frozenset[str] = frozenset({"win_rate", "win_rate_basis"})


@dataclass(frozen=True)
class PlayerResponseRule:
    """1 行 = 「このパスの GET 応答から、これらのキーを (再帰的に) 落とす」。"""

    name: str
    pattern: "re.Pattern[str]"
    keys: frozenset[str]
    # このパスで player が付けても無視するクエリパラメータ (結果で絞り込む = 勝敗の取り出し)
    drop_query: frozenset[str] = frozenset()
    # 落とすと画面側が `.map` / `.length` / `Object.entries` で落ちるキーは、空値に置換する
    # (キーは残るが中身は空 = 「データなし」表示になる)。{キー: 置換値}
    neutral: Mapping[str, Any] = field(default_factory=dict)


def _rule(name: str, pattern: str, keys: Iterable[str] = (), drop_query: Iterable[str] = (),
          neutral: Mapping[str, Any] | None = None):
    return PlayerResponseRule(
        name=name, pattern=re.compile(pattern),
        keys=frozenset(keys), drop_query=frozenset(drop_query),
        neutral=dict(neutral or {}),
    )


# ─── 宣言的テーブル ──────────────────────────────────────────────────────────
PLAYER_RESPONSE_RULES: tuple[PlayerResponseRule, ...] = (
    # --- analysis_stable: 記述統計系 (win_rate / wins を返す) ---
    _rule(
        "analysis.descriptive", r"/api/analysis/descriptive",
        _WIN_RATE_KEYS | {"wins", "server_win_rate"},
        neutral={"win_by_end_type": {}},
    ),
    _rule("analysis.shot_types", r"/api/analysis/shot_types", _WIN_RATE_KEYS),
    _rule("analysis.set_comparison", r"/api/analysis/set_comparison", _WIN_RATE_KEYS),
    _rule("analysis.tournament_level_comparison",
          r"/api/analysis/tournament_level_comparison", _WIN_RATE_KEYS),
    _rule("analysis.zone_detail", r"/api/analysis/zone_detail", _WIN_RATE_KEYS | {"wins"}),
    _rule("analysis.heatmap_zone_detail", r"/api/analysis/heatmap_zone_detail",
          _WIN_RATE_KEYS | {"wins", "win_count"}),
    # 有効配球マップは「得点したラリー」だけから作る = 勝敗そのもの。件数 (total_count) と
    # 順位 (top_zones) は残す。effectiveness は win_rate × 頻度 なので同じ扱い。
    _rule("analysis.effective_distribution_map",
          r"/api/analysis/effective_distribution_map(/zone_detail)?",
          _WIN_RATE_KEYS | {"win_count", "wins", "effectiveness"}),
    # --- analysis_stable: 試合単位 (勝敗・スコア・弱点調) ---
    _rule("analysis.matches_summary", r"/api/analysis/matches_summary",
          {"result", "score_player", "score_opponent", "won"}, neutral={"set_scores": []}),
    _rule("analysis.score_progression", r"/api/analysis/score_progression",
          {"score_a", "score_b", "winner", "point_diff"}, neutral={"momentum_changes": []}),
    _rule("analysis.set_summary", r"/api/analysis/set_summary",
          {"score_a", "score_b", "winner"} | _WIN_RATE_KEYS,
          neutral={"recent_loss_patterns": [], "risky_shots": []}),
    # --- 試合・選手一覧 ---
    _rule("matches.list_and_detail", r"/api/matches(/needs_review|/\d+)?",
          {"result", "final_score"}),
    _rule("matches.rallies", r"/api/matches/\d+/rallies", _RALLY_OUTCOME_KEYS),
    _rule("players.matches", r"/api/players/\d+/matches", {"result", "final_score"}),
    _rule("players.stats", r"/api/players/\d+/stats", {"wins", "losses", "win_rate"}),
    # --- レビュー ---
    # winner= で絞り込むと自分が取ったラリーが分かるため、パラメータ自体を無視する
    _rule("review.playlist", r"/api/review/playlist", _RALLY_OUTCOME_KEYS,
          drop_query={"winner"}),
    # --- 体調 × 勝率 ---
    _rule("conditions.best_profile", r"/api/conditions/best_profile",
          _WIN_RATE_KEYS | {"win_rate_in_profile", "win_rate_outside"}),
    # --- インターバル (試合内の優劣) ---
    _rule("reports.interval_flash", r"/api/reports/interval_flash",
          {"sets_a", "sets_b", "current_leader", "winner",
           "rally_wins_a", "rally_wins_b", "score_a", "score_b"},
          neutral={"set_scores": []}),
    # --- result=win|loss フィルタ: 結果で絞った集計から勝敗が逆算できる ---
    _rule("analysis.result_filter", r"/api/analysis/.*", drop_query={"result"}),
    _rule("reports.result_filter", r"/api/reports/.*", drop_query={"result"}),
    _rule("review.result_filter", r"/api/review/.*", drop_query={"result"}),
)

# アノテーション (入力・再開) 経路。入力ツールが得点と勝者を使うため、サニタイズ対象外。
# テストで「対象外であること」を固定し、方針変更時に意図して外せるようにする。
PLAYER_ANNOTATION_FLOW_PATHS: tuple["re.Pattern[str]", ...] = (
    re.compile(r"/api/rallies/match/\d+"),
    re.compile(r"/api/sets/match/\d+"),
    re.compile(r"/api/annotation/\d+/state"),
)

# 触ってはならない不確実性メタ (テストで保持を検証する)
UNCERTAINTY_KEYS: frozenset[str] = frozenset({
    "sample_size", "n", "n_matches", "n_top", "rally_count", "total_rallies",
    "total_matches", "total_count", "count", "confidence", "meta",
})


def normalize_path(path: str) -> str:
    """マッチ用の保守的な正規化 (過剰マッチは無害、取りこぼしは漏えい)。"""
    p = re.sub(r"/+", "/", path or "")
    while "/./" in p:
        p = p.replace("/./", "/")
    if len(p) > 1:
        p = p.rstrip("/")
    return p.lower()


_SAFE_METHODS = ("GET", "HEAD")


def rules_for(path: str, method: str = "GET") -> tuple[PlayerResponseRule, ...]:
    if method.upper() not in _SAFE_METHODS:
        return ()
    p = normalize_path(path)
    return tuple(r for r in PLAYER_RESPONSE_RULES if r.pattern.fullmatch(p))


def keys_to_drop(path: str, method: str = "GET") -> frozenset[str]:
    """このパスで player 応答に手を入れるキー (削除 + 空値置換)。空なら応答は触らない。"""
    out: set[str] = set()
    for r in rules_for(path, method):
        out |= r.keys | set(r.neutral)
    return frozenset(out)


def query_params_to_drop(path: str, method: str = "GET") -> frozenset[str]:
    out: set[str] = set()
    for r in rules_for(path, method):
        out |= r.drop_query
    return frozenset(out)


def neutral_for(path: str, method: str = "GET") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for r in rules_for(path, method):
        out.update(r.neutral)
    return out


def _strip(o: Any, drop: frozenset[str], neutral: Mapping[str, Any]) -> Any:
    if isinstance(o, dict):
        out: dict[str, Any] = {}
        for k, v in o.items():
            if k in neutral:
                out[k] = copy.deepcopy(neutral[k])
            elif k not in drop:
                out[k] = _strip(v, drop, neutral)
        return out
    if isinstance(o, list):
        return [_strip(x, drop, neutral) for x in o]
    return o


def sanitize_for_player(path: str, payload: Any, method: str = "GET") -> Any:
    """role=player の応答 payload から、テーブルで宣言されたキーを再帰的に落とす。

    純関数 (入力を変更しない)。テーブルに該当しないパスは payload をそのまま返す。
    """
    drop = keys_to_drop(path, method)
    if not drop:
        return payload
    neutral = neutral_for(path, method)
    return _strip(payload, drop - set(neutral), neutral)


def strip_query_for_player(path: str, query_string: bytes, method: str = "GET") -> bytes:
    """player のクエリ文字列から、無視すべきパラメータ (result=win|loss 等) を取り除く。

    残りのパラメータは元のバイト列のまま保つ。
    """
    drop = query_params_to_drop(path, method)
    if not drop or not query_string:
        return query_string
    from urllib.parse import unquote_plus

    kept: list[bytes] = []
    for part in query_string.split(b"&"):
        if not part:
            continue
        name = unquote_plus(part.split(b"=", 1)[0].decode("latin-1")).strip()
        if name in drop:
            continue
        kept.append(part)
    return b"&".join(kept)
