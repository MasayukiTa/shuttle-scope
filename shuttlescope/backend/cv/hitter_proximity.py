"""Perspective-aware image-space proximity for CV hitter attribution.

The shuttle is airborne, so projecting it through a floor homography is
physically wrong (D-1).  At the same time, a fixed normalized-image threshold
is perspective-biased: a far-side player is visually smaller, so the same
0.35 image distance covers much more real space.

This module stays entirely in image space and uses the detected person's
apparent bbox height as a local scale estimate.  It therefore removes the
first-order perspective scale bias without pretending the shuttle lies on the
court floor.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Optional


# Preserve the former 0.35 threshold only as an absolute upper bound.
MAX_IMAGE_DISTANCE = 0.35
# Avoid making tiny/noisy far-side boxes produce a near-zero acceptance radius.
MIN_IMAGE_DISTANCE = 0.08
# A shuttle within roughly 1.5 apparent body heights of the player's centroid
# is considered a proximity candidate. The absolute cap above still applies.
MAX_BODY_HEIGHTS = 1.5


@dataclass(frozen=True)
class PlayerProximity:
    player: dict
    raw_distance: float
    allowed_distance: float
    normalized_distance: float


def _bbox_height(player: dict) -> Optional[float]:
    bbox = player.get("bbox")
    if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
        return None
    try:
        y1 = float(bbox[1])
        y2 = float(bbox[3])
    except (TypeError, ValueError):
        return None
    height = abs(y2 - y1)
    if not math.isfinite(height) or height <= 1e-6:
        return None
    return height


def proximity_for_player(
    player: dict,
    x_norm: float,
    y_norm: float,
    *,
    max_image_distance: float = MAX_IMAGE_DISTANCE,
    min_image_distance: float = MIN_IMAGE_DISTANCE,
    max_body_heights: float = MAX_BODY_HEIGHTS,
) -> Optional[PlayerProximity]:
    """Return scale-normalized image proximity for one player.

    Missing/invalid bbox returns None rather than silently falling back to the
    old perspective-biased fixed threshold.
    """
    centroid = player.get("centroid")
    if not isinstance(centroid, (list, tuple)) or len(centroid) < 2:
        return None
    height = _bbox_height(player)
    if height is None:
        return None
    try:
        cx = float(centroid[0])
        cy = float(centroid[1])
        sx = float(x_norm)
        sy = float(y_norm)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(v) for v in (cx, cy, sx, sy)):
        return None

    max_dist = max(1e-6, float(max_image_distance))
    min_dist = max(1e-6, min(float(min_image_distance), max_dist))
    body_scale = max(1e-6, float(max_body_heights))
    allowed = max(min_dist, min(max_dist, height * body_scale))
    raw = math.hypot(cx - sx, cy - sy)
    return PlayerProximity(
        player=player,
        raw_distance=raw,
        allowed_distance=allowed,
        normalized_distance=raw / allowed,
    )


def nearest_player_by_proximity(
    players: Iterable[dict],
    x_norm: float,
    y_norm: float,
    *,
    labels: Optional[set[str]] = None,
    max_image_distance: float = MAX_IMAGE_DISTANCE,
    min_image_distance: float = MIN_IMAGE_DISTANCE,
    max_body_heights: float = MAX_BODY_HEIGHTS,
) -> Optional[PlayerProximity]:
    """Pick the closest player in local body-scale units."""
    candidates: list[PlayerProximity] = []
    for player in players:
        label = player.get("label")
        if labels is not None and label not in labels:
            continue
        proximity = proximity_for_player(
            player,
            x_norm,
            y_norm,
            max_image_distance=max_image_distance,
            min_image_distance=min_image_distance,
            max_body_heights=max_body_heights,
        )
        if proximity is not None:
            candidates.append(proximity)
    if not candidates:
        return None
    return min(candidates, key=lambda p: p.normalized_distance)


def players_within_proximity(
    players: Iterable[dict],
    x_norm: float,
    y_norm: float,
    *,
    labels: Optional[set[str]] = None,
    max_image_distance: float = MAX_IMAGE_DISTANCE,
    min_image_distance: float = MIN_IMAGE_DISTANCE,
    max_body_heights: float = MAX_BODY_HEIGHTS,
) -> list[PlayerProximity]:
    """Return players whose scale-normalized proximity is within threshold."""
    out: list[PlayerProximity] = []
    for player in players:
        label = player.get("label")
        if labels is not None and label not in labels:
            continue
        proximity = proximity_for_player(
            player,
            x_norm,
            y_norm,
            max_image_distance=max_image_distance,
            min_image_distance=min_image_distance,
            max_body_heights=max_body_heights,
        )
        if proximity is not None and proximity.normalized_distance <= 1.0:
            out.append(proximity)
    return out
