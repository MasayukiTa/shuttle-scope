"""X-9: package import must not reuse foreign integer PKs across devices."""
from __future__ import annotations

from datetime import datetime

import pytest

from backend.db.models import Player
from backend.services.import_package import _apply_record, _remap_fks
from backend.services.merge_resolver import MergeDecision
from backend.utils.sync_meta import business_payload, compute_content_hash


def test_remap_fks_rejects_unresolved_source_integer():
    data = {"set_id": 42, "rally_num": 1}
    with pytest.raises(ValueError, match="unresolved package foreign key"):
        _remap_fks(data, {"sets": {}})


def test_remap_fks_uses_package_to_local_mapping():
    data = {"set_id": 42, "rally_num": 1}
    _remap_fks(data, {"sets": {42: 9001}})
    assert data["set_id"] == 9001


def test_update_refreshes_hash_and_registers_parent_mapping(db_session, monkeypatch):
    import backend.services.import_package as import_mod

    player = Player(name="before", dominant_hand="R")
    player.content_hash = "stale"
    db_session.add(player)
    db_session.commit()

    source_id = 77
    incoming = {
        "id": source_id,
        "uuid": player.uuid,
        "name": "after",
        "dominant_hand": "R",
        "updated_at": datetime.utcnow().isoformat(),
        # Must never be trusted as the resulting local hash.
        "content_hash": "attacker-controlled",
    }
    decision = MergeDecision(
        uuid=player.uuid,
        action="update",
        table="players",
        local_id=player.id,
        incoming_record=incoming,
        reason="test",
    )
    id_remap: dict[str, dict[int, int]] = {}

    monkeypatch.setattr(import_mod, "_may_write", lambda _obj, _team_id: True)
    _apply_record(
        db_session,
        Player,
        decision,
        id_remap,
        "players",
        importer_team_id=123,
    )

    db_session.expire_all()
    refreshed = db_session.get(Player, player.id)
    assert refreshed is not None
    assert refreshed.name == "after"
    assert refreshed.content_hash == compute_content_hash(business_payload(refreshed))
    assert refreshed.content_hash != "attacker-controlled"
    assert id_remap["players"][source_id] == player.id
