"""Split training samples into train / validation by group (for example by match).

Samples from one match share the court, camera, players and lighting. Splitting at the
stroke level puts near-identical samples on both sides and overstates accuracy on unseen
matches. This helper keeps every group entirely on one side. It needs no torch.
"""
from __future__ import annotations

import random
from typing import Hashable, Sequence


def split_indices_by_group(
    groups: Sequence[Hashable],
    val_split: float,
    seed: int = 42,
) -> tuple[list[int], list[int], list[Hashable]]:
    """Return (train_indices, val_indices, val_groups).

    Whole groups are moved to validation, in a seeded random order, until the validation
    side holds at least ``val_split`` of the samples (at least one group). At least one
    group always stays in train. Raises ValueError when there are fewer than two groups,
    because an independent validation set cannot be built.
    """
    if not 0.0 < val_split < 1.0:
        raise ValueError("val_split must be between 0 and 1")
    members: dict[Hashable, list[int]] = {}
    for i, g in enumerate(groups):
        members.setdefault(g, []).append(i)
    if len(members) < 2:
        raise ValueError("need samples from at least two groups to split by group")

    order = sorted(members, key=lambda g: str(g))
    random.Random(seed).shuffle(order)

    total = len(groups)
    target = max(1, int(total * val_split))
    val_groups: list[Hashable] = []
    val_count = 0
    for g in order[:-1]:  # the last group always stays in train
        if val_count >= target:
            break
        val_groups.append(g)
        val_count += len(members[g])

    val_set = set(val_groups)
    train_idx = [i for g in order if g not in val_set for i in members[g]]
    val_idx = [i for g in val_groups for i in members[g]]
    return sorted(train_idx), sorted(val_idx), val_groups
