"""Shot classifier training data: the stroke query runs on the real schema and the
validation split keeps every match on one side (audit 875 / 876)."""
from __future__ import annotations

import pytest
from sqlalchemy import text

from backend.analysis import shot_classifier_clip as clip_mod
from backend.analysis import shot_classifier_lstm as lstm_mod
from backend.analysis.group_split import split_indices_by_group
from backend.tests.test_cross_team_write_scope import _seed


def test_stroke_queries_run_on_the_real_schema_and_return_match_id(db_session):
    _seed(db_session)  # match 1 has a video path and stroke 1; match 2 has stroke 2 and no video
    lstm_rows = db_session.execute(text(lstm_mod.STROKE_QUERY)).fetchall()
    assert sorted((r.id, r.match_id) for r in lstm_rows) == [(1, 1), (2, 2)]
    clip_rows = db_session.execute(text(clip_mod.STROKE_QUERY)).fetchall()
    assert [(r.id, r.match_id) for r in clip_rows] == [(1, 1)]


def test_split_keeps_each_group_on_one_side():
    groups = [m for m in (1, 2, 3, 4, 5, 6) for _ in range(10)]
    train_idx, val_idx, val_groups = split_indices_by_group(groups, 0.3, seed=7)
    assert val_idx and train_idx
    assert not set(train_idx) & set(val_idx)
    assert sorted(train_idx + val_idx) == list(range(len(groups)))
    train_groups = {groups[i] for i in train_idx}
    val_group_set = {groups[i] for i in val_idx}
    assert not train_groups & val_group_set
    assert val_group_set == set(val_groups)
    assert len(val_idx) >= int(len(groups) * 0.3)


def test_split_is_deterministic_for_a_seed():
    groups = [m for m in (1, 2, 3, 4) for _ in range(5)]
    assert split_indices_by_group(groups, 0.25, seed=3) == split_indices_by_group(groups, 0.25, seed=3)


def test_split_needs_two_groups_and_keeps_one_for_train():
    with pytest.raises(ValueError):
        split_indices_by_group([1, 1, 1, 1], 0.2)
    train_idx, val_idx, _ = split_indices_by_group([1, 1, 2, 2], 0.9)
    assert train_idx and val_idx
