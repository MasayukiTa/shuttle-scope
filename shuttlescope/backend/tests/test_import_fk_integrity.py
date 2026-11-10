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


# ── E1: 取り込みは全レコードか皆無か / 取り込み前の自動バックアップ ─────────────

import io
import json
import uuid as _uuid_mod
import zipfile
from pathlib import Path

from backend.db.models import GameSet
from backend.services.import_package import import_package


def _sspkg(members: dict[str, list[dict]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, records in members.items():
            zf.writestr(f"{name}.json", json.dumps(records))
    return buf.getvalue()


def _player_rec(pk: int, name: str) -> dict:
    return {
        "id": pk,
        "uuid": str(_uuid_mod.uuid4()),
        "name": name,
        "dominant_hand": "R",
        "updated_at": datetime.utcnow().isoformat(),
    }


def _orphan_set_rec() -> dict:
    # match_id=999 はパッケージ内の matches に無い -> _remap_fks が ValueError。
    return {
        "id": 1,
        "uuid": str(_uuid_mod.uuid4()),
        "match_id": 999,
        "set_num": 1,
        "score_a": 0,
        "score_b": 0,
        "updated_at": datetime.utcnow().isoformat(),
    }


def test_failure_in_a_later_record_leaves_the_database_unchanged(db_session):
    # players は sets より先に処理される。1 件目 (選手) は適用でき、2 件目 (セット) が失敗する。
    good = _player_rec(1, "適用される選手")
    raw = _sspkg({"players": [good], "sets": [_orphan_set_rec()]})

    summary = import_package(db_session, raw, dry_run=False, importer_team_id=None)

    assert summary.rolled_back is True
    assert summary.failures == 1
    assert any(e.startswith("sets[") for e in summary.errors), summary.errors
    # 1 件目も残らない (旧実装はレコードごとに commit していたので残った)
    assert summary.added == 0
    db_session.expire_all()
    assert db_session.query(Player).filter_by(uuid=good["uuid"]).first() is None
    assert db_session.query(Player).count() == 0
    assert db_session.query(GameSet).count() == 0


def test_a_clean_package_is_committed_as_a_whole(db_session):
    a = _player_rec(1, "選手A")
    b = _player_rec(2, "選手B")

    summary = import_package(db_session, _sspkg({"players": [a, b]}), dry_run=False,
                             importer_team_id=None)

    assert summary.rolled_back is False
    assert summary.failures == 0
    assert summary.added == 2
    db_session.rollback()  # commit 済みなら rollback しても残る
    assert db_session.query(Player).count() == 2


def test_successful_import_takes_a_backup_before_writing(db_session, monkeypatch):
    import backend.services.import_package as import_mod

    seen: list[int] = []

    def fake_backup(label=None, max_generations=10):
        # バックアップ時点では、まだ 1 件も書かれていないこと
        seen.append(db_session.query(Player).count())
        assert label == "pre_import"
        return Path("backup_fake.zip")

    monkeypatch.setattr(import_mod, "create_backup", fake_backup)

    summary = import_package(
        db_session, _sspkg({"players": [_player_rec(1, "選手A")]}),
        dry_run=False, importer_team_id=None, backup_before_apply=True,
    )

    assert seen == [0]
    assert summary.backup_path == "backup_fake.zip"
    assert summary.added == 1
    assert db_session.query(Player).count() == 1


def test_failed_backup_aborts_the_import_without_writing(db_session, monkeypatch):
    import backend.services.import_package as import_mod

    def broken_backup(label=None, max_generations=10):
        raise RuntimeError("[backup] SS_BACKUP_PASSPHRASE 未設定")

    monkeypatch.setattr(import_mod, "create_backup", broken_backup)

    summary = import_package(
        db_session, _sspkg({"players": [_player_rec(1, "選手A")]}),
        dry_run=False, importer_team_id=None, backup_before_apply=True,
    )

    assert summary.backup_failed is True
    assert summary.added == 0
    assert summary.backup_path is None
    assert any("バックアップ" in e for e in summary.errors)
    assert db_session.query(Player).count() == 0


def test_unsupported_backup_engine_does_not_block_the_import(db_session, monkeypatch):
    """PostgreSQL: create_backup は NotImplementedError。1 トランザクションが保護を担う。"""
    import backend.services.import_package as import_mod

    def unsupported(label=None, max_generations=10):
        raise NotImplementedError("create_backup は SQLite 専用です")

    monkeypatch.setattr(import_mod, "create_backup", unsupported)

    summary = import_package(
        db_session, _sspkg({"players": [_player_rec(1, "選手A")]}),
        dry_run=False, importer_team_id=None, backup_before_apply=True,
    )

    assert summary.backup_failed is False
    assert summary.backup_path is None
    assert summary.added == 1


def test_dry_run_never_takes_a_backup(db_session, monkeypatch):
    import backend.services.import_package as import_mod

    def must_not_run(label=None, max_generations=10):
        raise AssertionError("dry_run で create_backup を呼んではいけない")

    monkeypatch.setattr(import_mod, "create_backup", must_not_run)

    summary = import_package(
        db_session, _sspkg({"players": [_player_rec(1, "選手A")]}),
        dry_run=True, importer_team_id=None, backup_before_apply=True,
    )

    assert summary.added == 1
    assert db_session.query(Player).count() == 0


def test_router_maps_backup_failure_and_rollback_to_http_errors(db_session, monkeypatch):
    from fastapi import HTTPException

    import backend.routers.sync as sync_mod
    from backend.services.import_package import ImportSummary

    calls: list[bool] = []

    def stub(_db, _raw, dry_run=False, importer_team_id=None, backup_before_apply=False):
        calls.append(backup_before_apply)
        return ImportSummary(backup_failed=True, errors=["x"])

    monkeypatch.setattr(sync_mod, "import_package", stub)
    with pytest.raises(HTTPException) as e:
        sync_mod._run_import(db_session, b"", False, None)
    assert e.value.status_code == 500
    assert calls == [True]  # 実取り込みは必ずバックアップ付きで呼ぶ

    def stub2(_db, _raw, dry_run=False, importer_team_id=None, backup_before_apply=False):
        return ImportSummary(rolled_back=True, failures=2, errors=["a", "b"])

    monkeypatch.setattr(sync_mod, "import_package", stub2)
    with pytest.raises(HTTPException) as e2:
        sync_mod._run_import(db_session, b"", False, None)
    assert e2.value.status_code == 409

    # プレビュー (dry_run=True) ではバックアップを要求しない
    calls.clear()

    def stub3(_db, _raw, dry_run=False, importer_team_id=None, backup_before_apply=False):
        calls.append(backup_before_apply)
        return ImportSummary()

    monkeypatch.setattr(sync_mod, "import_package", stub3)
    sync_mod._run_import(db_session, b"", True, None)
    assert calls == [False]
