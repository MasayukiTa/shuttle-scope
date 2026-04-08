"""ライブソース品質スコアリング

ソース種別・解像度・fps から優先度と suitability を算出するユーティリティ。
sessions.py の source 登録時に使用する。

suitability レベル:
  high     — 推論・記録に十分な品質（推奨）
  usable   — 使用可能だが最適ではない
  fallback — 代替手段として使用可能だが品質は低い

source_priority: 数値が小さいほど優先度が高い（1 = 最高優先）。
複数ソースが同じ priority の場合は id 昇順でソートされる。
"""
from __future__ import annotations

# ─── デフォルトスコア（ソース種別のみで決まるベースライン） ────────────────

_KIND_BASE: dict[str, tuple[int, str]] = {
    "iphone_webrtc":  (1, "high"),      # LAN 経由 iPhone — 最優先
    "ipad_webrtc":    (1, "high"),       # LAN 経由 iPad
    "usb_camera":     (2, "high"),       # USB 有線カメラ
    "builtin_camera": (3, "usable"),     # PC 内蔵カメラ
    "pc_local":       (3, "usable"),     # PC ローカルカメラ（汎用）
}

_FALLBACK_BASE: tuple[int, str] = (4, "fallback")


def _parse_resolution(resolution: str | None) -> tuple[int, int] | None:
    """'1280x720' → (1280, 720)。パース失敗時は None。"""
    if not resolution:
        return None
    try:
        parts = resolution.lower().split("x")
        if len(parts) != 2:
            return None
        w, h = int(parts[0]), int(parts[1])
        return (w, h)
    except (ValueError, AttributeError):
        return None


def _resolution_score(resolution: str | None) -> int:
    """解像度の品質スコア（大きいほど良い）。"""
    parsed = _parse_resolution(resolution)
    if parsed is None:
        return 0
    w, h = parsed
    pixels = w * h
    if pixels >= 1920 * 1080:   # Full HD 以上
        return 3
    if pixels >= 1280 * 720:    # HD
        return 2
    if pixels >= 640 * 480:     # VGA
        return 1
    return 0


def compute_suitability(
    source_kind: str,
    resolution: str | None = None,
    fps: int | None = None,
) -> tuple[int, str]:
    """ソース品質を算出して (priority, suitability) を返す。

    Rules:
      1. ソース種別のベース値を起点とする。
      2. 解像度が Full HD 以上であれば suitability が usable の場合に high へ昇格。
      3. fps が 60 以上であれば usable → high へ昇格。
      4. 解像度が高い / fps が高いほど priority を 1 段階改善（最低 1 に固定）。
      5. fallback 種別は解像度・fps による suitability 昇格なし（priority のみ改善）。
    """
    priority, suitability = _KIND_BASE.get(source_kind, _FALLBACK_BASE)
    is_fallback_kind = source_kind not in _KIND_BASE

    res_score = _resolution_score(resolution)
    fps_val = fps or 0

    # ─ suitability 昇格（fallback 種別には適用しない） ─
    if not is_fallback_kind and suitability == "usable":
        if res_score >= 3 or fps_val >= 60:
            suitability = "high"

    # ─ priority ボーナス（解像度・fps が良ければ 1 段階改善） ─
    if res_score >= 3 or fps_val >= 60:
        priority = max(1, priority - 1)

    return priority, suitability


def compute_source_score(
    source_kind: str,
    resolution: str | None = None,
    fps: int | None = None,
) -> float:
    """推奨度の数値スコア（大きいほど良い）。UI ランキング・ソートに使用。

    スコアの内訳:
      - ベーススコア: suitability × 種別重み
      - 解像度ボーナス: 0〜15
      - fps ボーナス: 0〜10
    """
    _, suitability = compute_suitability(source_kind, resolution, fps)

    base = {
        "high":     60.0,
        "usable":   40.0,
        "fallback": 20.0,
    }.get(suitability, 20.0)

    res_score = _resolution_score(resolution)
    res_bonus = res_score * 5.0   # 最大 15

    fps_bonus = 0.0
    if fps:
        if fps >= 120:
            fps_bonus = 10.0
        elif fps >= 60:
            fps_bonus = 7.0
        elif fps >= 30:
            fps_bonus = 3.0

    return base + res_bonus + fps_bonus


def rank_sources(
    sources: list[dict],
) -> list[dict]:
    """ソースリストを品質スコア降順でソートして返す。

    各 source dict は source_kind / source_resolution? / source_fps? を持つこと。
    """
    def score(s: dict) -> float:
        return compute_source_score(
            s.get("source_kind", ""),
            s.get("source_resolution"),
            s.get("source_fps"),
        )
    return sorted(sources, key=score, reverse=True)
