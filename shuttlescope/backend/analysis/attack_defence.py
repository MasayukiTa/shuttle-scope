"""Official attack/defence height classification (coach + university request).

Single source of truth for ONE rule
-----------------------------------
A coach and a university group asked that the HEIGHT of the hit become an *official*
classification instead of an ad-hoc analysis. The rule they agreed on is
body-relative and must live in exactly one place:

    wrist AT OR ABOVE racket height  -> "attack"
    wrist BELOW racket height        -> "defence"

The raw observation is stored on the stroke as ``wrist_vs_racket`` with the values
``at_or_above`` / ``below`` (NULL = not recorded). The attack/defence *label* is NOT
stored; it is derived here so the rule can never drift between call sites.

Why a new field was needed (and not an existing one)
----------------------------------------------------
None of the pre-existing stroke fields can express the wrist-vs-racket rule:

- ``hit_height`` (above_net / slightly_above / slightly_below / below) is measured
  relative to the NET, not to the player's wrist and racket.
- ``contact_height`` (overhead / side / underhand / scoop) is the swing FORM, not
  where the wrist sits relative to the racket head.
- ``above_net`` is where the SHUTTLE was relative to the net.

So this classification reads only ``wrist_vs_racket``. When that is NULL/unknown the
classification is ``None`` (unknown) — we never guess from a different concept.

This module has no heavy dependencies (no DB, no numpy) and returns a *derived*
value only; it does not mutate strokes and does not change any existing aggregation.
"""
from __future__ import annotations

from typing import Iterable, Optional

# Raw stored observation -> official class. Keep this mapping as the one definition.
WRIST_AT_OR_ABOVE = "at_or_above"
WRIST_BELOW = "below"
VALID_WRIST_VS_RACKET = frozenset({WRIST_AT_OR_ABOVE, WRIST_BELOW})

ATTACK = "attack"
DEFENCE = "defence"


def classify_attack_defence(wrist_vs_racket: Optional[str]) -> Optional[str]:
    """Official height classification for one stroke.

    Rule (the single definition):
        wrist at or above racket height -> "attack"
        wrist below racket height       -> "defence"

    Returns ``None`` when the input is NULL or an unknown label, i.e. the official
    classification is simply not known for that stroke. We do not fall back to
    net-relative height or swing form, because those are different concepts.
    """
    if wrist_vs_racket == WRIST_AT_OR_ABOVE:
        return ATTACK
    if wrist_vs_racket == WRIST_BELOW:
        return DEFENCE
    return None


def stroke_attack_defence(stroke: object) -> Optional[str]:
    """Derive the official class from a stroke (ORM object or dict).

    Reads only the ``wrist_vs_racket`` field. Never mutates the stroke.
    """
    if isinstance(stroke, dict):
        raw = stroke.get("wrist_vs_racket")
    else:
        raw = getattr(stroke, "wrist_vs_racket", None)
    return classify_attack_defence(raw)


def summarize_attack_defence(strokes: Iterable[object]) -> dict:
    """Count official attack/defence classes across strokes.

    Strokes whose ``wrist_vs_racket`` is unrecorded are counted under ``unknown``
    and excluded from ``attack_rate`` so the rate is over *classified* strokes only.

    Returns a dict:
      attack      : number of strokes classified as attack
      defence     : number of strokes classified as defence
      unknown     : number of strokes with no official classification
      classified  : attack + defence
      attack_rate : attack / classified, or None when classified == 0
    """
    attack = 0
    defence = 0
    unknown = 0
    for s in strokes:
        label = stroke_attack_defence(s)
        if label == ATTACK:
            attack += 1
        elif label == DEFENCE:
            defence += 1
        else:
            unknown += 1
    classified = attack + defence
    attack_rate = (attack / classified) if classified else None
    return {
        "attack": attack,
        "defence": defence,
        "unknown": unknown,
        "classified": classified,
        "attack_rate": attack_rate,
    }
