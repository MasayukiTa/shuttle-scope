"""Audit #576: CommentCreate / frontend POST /comments contract.

The Annotator's handleSubmitComment (src/pages/AnnotatorPage.tsx) must not send
`author_role`: the server derives it from the authenticated context (ctx.role).
CommentCreate uses model_config={"extra": "forbid"}, so an extra `author_role`
field would make every post fail with 422. This contract test pins:

  1. CommentCreate forbids `author_role` (and any other extra field).
  2. The exact set of keys the frontend is allowed to send equals the model's
     own field set, and `author_role` is NOT among them.

If a future change re-adds author_role to the frontend payload or relaxes the
model, this test fails and the 422 regression is caught before deploy.

No ORM rows are created here (pure Pydantic validation), so there is no NOT NULL
fixture to populate.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.routers.comments import CommentCreate

# The keys the Annotator's handleSubmitComment is allowed to put on the
# POST /comments body (src/pages/AnnotatorPage.tsx handleSubmitComment).
# `author_role` is intentionally absent: the server owns it.
FRONTEND_KEYS = {"match_id", "rally_id", "text", "is_flagged"}


def test_frontend_keys_are_a_subset_of_allowed_fields():
    allowed = set(CommentCreate.model_fields.keys())
    assert FRONTEND_KEYS <= allowed, FRONTEND_KEYS - allowed


def test_author_role_is_not_an_allowed_field():
    # Server-side provenance only: the client must never be able to set it.
    assert "author_role" not in CommentCreate.model_fields
    assert "author_role" not in FRONTEND_KEYS


def test_frontend_payload_validates():
    body = {"match_id": 1, "rally_id": 7, "text": "good rally", "is_flagged": False}
    assert set(body) <= FRONTEND_KEYS
    model = CommentCreate(**body)
    assert model.match_id == 1
    assert model.text == "good rally"


def test_author_role_is_rejected_as_extra_field():
    body = {"match_id": 1, "text": "x", "author_role": "admin"}
    with pytest.raises(ValidationError):
        CommentCreate(**body)
