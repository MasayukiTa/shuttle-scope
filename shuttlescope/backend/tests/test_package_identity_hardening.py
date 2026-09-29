"""X-9 package identity / FK hardening regressions."""
from __future__ import annotations

import io
import json
import uuid
import zipfile
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.db.models import Player, Team
from backend.routers.data_package import (
    _find_reusable_import_player,
    _new_imported_player,
    _required_player_mapping,
)
from backend.services.import_package import import_package
from backend.utils.identity_uuid import canonical_identity_uuid


def _uuid() -> str:
    return str(uuid.uuid4())


def test_canonical_identity_uuid_rejects_non_uuid_identity():
    assert canonical_identity_uuid("not-a-uuid") is None
    assert canonical_identity_uuid("a" * 200) is None
    assert canonical_identity_uuid(uuid.uuid4().hex) is None


def test_canonical_identity_uuid_normalizes_case():
    raw = _uuid().upper()
    assert canonical_identity_uuid(raw) == raw.lower()


def test_sspkg_invalid_uuid_is_skipped_before_identity_lookup(db_session):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "players.json",
            json.dumps([{"id": 1, "uuid": "attacker-controlled-identity", "name": "X"}]),
        )

    summary = import_package(
        db_session,
        buf.getvalue(),
        dry_run=True,
        importer_team_id=1,
    )

    assert summary.added == 0
    assert any("不正な uuid" in err for err in summary.errors)


def test_new_json_package_player_is_scouting_owned_not_team_member():
    player_uuid = _uuid()
    player = _new_imported_player(
        {
            "uuid": player_uuid,
            "name": "Imported Opponent",
            "team": "Untrusted Team Label",
            "nationality": "JP",
        },
        actor_team_id=42,
    )

    assert player.uuid == player_uuid
    assert player.team_id is None
    assert player.scouting_owner_team_id == 42
    assert player.name == "Imported Opponent"


def test_json_package_player_reuse_is_scoped_to_importer_team(db_session):
    team_a = Team(name="Pkg A", display_id="PKG-A")
    team_b = Team(name="Pkg B", display_id="PKG-B")
    db_session.add_all([team_a, team_b])
    db_session.flush()

    same_name_other_team = Player(
        uuid=_uuid(),
        name="Same Name",
        team_id=team_b.id,
    )
    own_scouted = Player(
        uuid=_uuid(),
        name="Own Scouted",
        scouting_owner_team_id=team_a.id,
    )
    db_session.add_all([same_name_other_team, own_scouted])
    db_session.commit()

    ctx = SimpleNamespace(is_admin=False, team_id=team_a.id)

    assert _find_reusable_import_player(
        db_session,
        {"uuid": same_name_other_team.uuid, "name": "Same Name"},
        ctx,
    ) is None

    resolved = _find_reusable_import_player(
        db_session,
        {"uuid": own_scouted.uuid, "name": "Own Scouted"},
        ctx,
    )
    assert resolved is not None
    assert resolved.id == own_scouted.id


def test_json_package_fk_mapping_is_fail_closed():
    mapping = {10: 101, 20: 202}
    assert _required_player_mapping(mapping, 10, "player_a_id") == 101
    assert _required_player_mapping(mapping, None, "partner_a_id", optional=True) is None

    with pytest.raises(HTTPException) as exc:
        _required_player_mapping(mapping, 999, "player_b_id")
    assert exc.value.status_code == 422
