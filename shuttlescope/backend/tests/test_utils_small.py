"""C5: small unit tests for backend/utils modules."""
from __future__ import annotations

import pytest
from starlette.requests import Request

from backend.utils import control_plane as cp
from backend.utils import field_sensitivity as fs
from backend.utils import match_players as mp


class TestFieldSensitivity:
    def test_get_max_tier_known_roles(self):
        assert fs.get_max_tier("admin") == 4
        assert fs.get_max_tier("analyst") == 4
        assert fs.get_max_tier("coach") == 3
        assert fs.get_max_tier("player") == 2

    def test_get_max_tier_unknown_or_none(self):
        assert fs.get_max_tier(None) == 0
        assert fs.get_max_tier("") == 0
        assert fs.get_max_tier("unknown") == 0

    def test_filter_keeps_tier0_ids(self):
        row = {"id": 1, "player_id": 5, "measured_at": "2026-01-01"}
        assert fs.filter_condition_fields(row, "player") == row

    def test_filter_drops_higher_tier_for_player(self):
        row = {
            "id": 1,
            "hooper_fatigue": 3,
            "weight_kg": 70.0,
            "injury_notes": "sprain",
        }
        got = fs.filter_condition_fields(row, "player")
        assert "weight_kg" not in got
        assert "injury_notes" not in got
        assert got["hooper_fatigue"] == 3

    def test_filter_coach_sees_body_composition_but_not_medical(self):
        row = {"weight_kg": 70.0, "injury_notes": "sprain"}
        got = fs.filter_condition_fields(row, "coach")
        assert got.get("weight_kg") == 70.0
        assert "injury_notes" not in got

    def test_filter_analyst_sees_all(self):
        row = {"weight_kg": 70.0, "injury_notes": "sprain", "general_comment": "ok"}
        assert fs.filter_condition_fields(row, "analyst") == row

    def test_filter_unknown_field_defaults_to_tier0(self):
        row = {"brand_new_field": "value"}
        assert fs.filter_condition_fields(row, "player") == row


class TestMatchPlayers:
    def _mk_match(self, db, **kwargs):
        from datetime import date as _date

        from backend.db.models import Match

        kwargs.setdefault("tournament", "t")
        kwargs.setdefault("tournament_level", "other")
        kwargs.setdefault("round", "F")
        kwargs.setdefault("date", _date(2026, 1, 1))
        kwargs.setdefault("format", "singles")
        kwargs.setdefault("result", "win")
        m = Match(**kwargs)
        db.add(m)
        db.commit()
        db.refresh(m)
        return m

    def test_players_for_match_none(self, test_engine):
        from sqlalchemy.orm import sessionmaker

        Session = sessionmaker(bind=test_engine)
        with Session() as s:
            assert mp.players_for_match(s, None) == []

    def test_players_for_match_missing(self, test_engine):
        from sqlalchemy.orm import sessionmaker

        Session = sessionmaker(bind=test_engine)
        with Session() as s:
            assert mp.players_for_match(s, 999999) == []

    def test_players_for_match_singles(self, test_engine):
        from sqlalchemy.orm import sessionmaker

        from backend.db.models import Player

        Session = sessionmaker(bind=test_engine)
        with Session() as s:
            pa = Player(name="A")
            pb = Player(name="B")
            s.add_all([pa, pb])
            s.commit()
            m = self._mk_match(s, player_a_id=pa.id, player_b_id=pb.id)
            ids = mp.players_for_match(s, m.id)
            assert sorted(ids) == sorted([pa.id, pb.id])

    def test_players_for_match_doubles(self, test_engine):
        from sqlalchemy.orm import sessionmaker

        from backend.db.models import Player

        Session = sessionmaker(bind=test_engine)
        with Session() as s:
            players = [Player(name=n) for n in ("A", "B", "C", "D")]
            s.add_all(players)
            s.commit()
            m = self._mk_match(
                s,
                player_a_id=players[0].id,
                partner_a_id=players[1].id,
                player_b_id=players[2].id,
                partner_b_id=players[3].id,
            )
            ids = mp.players_for_match(s, m.id)
            assert sorted(ids) == sorted([p.id for p in players])

    def test_players_for_set_and_rally(self, test_engine):
        from sqlalchemy.orm import sessionmaker

        from backend.db.models import GameSet, Player, Rally

        Session = sessionmaker(bind=test_engine)
        with Session() as s:
            pa = Player(name="A")
            pb = Player(name="B")
            s.add_all([pa, pb])
            s.commit()
            m = self._mk_match(s, player_a_id=pa.id, player_b_id=pb.id)
            gs = GameSet(match_id=m.id, set_num=1)
            s.add(gs)
            s.commit()
            r = Rally(
                set_id=gs.id,
                rally_num=1,
                server="player_a",
                winner="player_a",
                end_type="ace",
                rally_length=1,
            )
            s.add(r)
            s.commit()

            assert sorted(mp.players_for_set(s, gs.id)) == sorted([pa.id, pb.id])
            assert sorted(mp.players_for_rally(s, r.id)) == sorted([pa.id, pb.id])
            assert mp.players_for_set(s, None) == []
            assert mp.players_for_rally(s, None) == []
            assert mp.players_for_set(s, 999999) == []
            assert mp.players_for_rally(s, 999999) == []


def _mk_request(headers: dict | None = None, client_host: str | None = "127.0.0.1") -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "client": (client_host, 50000) if client_host is not None else None,
    }
    return Request(scope)


class TestControlPlane:
    def test_loopback_detection(self):
        assert cp.is_loopback_request(_mk_request(client_host="127.0.0.1")) is True
        assert cp.is_loopback_request(_mk_request(client_host="::1")) is True
        assert cp.is_loopback_request(_mk_request(client_host="8.8.8.8")) is False

    def test_cf_connecting_ip_overrides_client(self):
        r = _mk_request({"CF-Connecting-IP": "8.8.8.8"}, client_host="127.0.0.1")
        assert cp.is_loopback_request(r) is False

    def test_trusted_subnet(self, monkeypatch):
        monkeypatch.setattr(cp, "_TRUSTED_PREFIXES", ["192.168.100."])
        r = _mk_request(client_host="192.168.100.5")
        assert cp.is_trusted_cluster_request(r) is True
        r2 = _mk_request(client_host="10.0.0.1")
        assert cp.is_trusted_cluster_request(r2) is False

    def test_operator_token_valid(self, monkeypatch):
        monkeypatch.setattr(cp, "_OPERATOR_TOKEN", "secret123")
        r = _mk_request({"X-Operator-Token": "secret123"}, client_host="8.8.8.8")
        assert cp._has_valid_operator_token(r) is True

    def test_operator_token_mismatch(self, monkeypatch):
        monkeypatch.setattr(cp, "_OPERATOR_TOKEN", "secret123")
        r = _mk_request({"X-Operator-Token": "wrong"}, client_host="8.8.8.8")
        assert cp._has_valid_operator_token(r) is False

    def test_operator_token_empty_config(self, monkeypatch):
        monkeypatch.setattr(cp, "_OPERATOR_TOKEN", "")
        r = _mk_request({"X-Operator-Token": "anything"}, client_host="8.8.8.8")
        assert cp._has_valid_operator_token(r) is False

    def test_require_local_allows_loopback(self):
        cp.require_local_or_operator_token(_mk_request(client_host="127.0.0.1"))

    def test_require_local_allows_trusted_subnet(self, monkeypatch):
        monkeypatch.setattr(cp, "_TRUSTED_PREFIXES", ["10.10."])
        cp.require_local_or_operator_token(_mk_request(client_host="10.10.0.5"))

    def test_require_local_allows_operator_token(self, monkeypatch):
        monkeypatch.setattr(cp, "_OPERATOR_TOKEN", "tok")
        monkeypatch.setattr(cp, "_TRUSTED_PREFIXES", [])
        cp.require_local_or_operator_token(
            _mk_request({"X-Operator-Token": "tok"}, client_host="8.8.8.8")
        )

    def test_require_local_rejects_external(self, monkeypatch):
        from fastapi import HTTPException

        monkeypatch.setattr(cp, "_OPERATOR_TOKEN", "")
        monkeypatch.setattr(cp, "_TRUSTED_PREFIXES", [])
        with pytest.raises(HTTPException) as exc:
            cp.require_local_or_operator_token(_mk_request(client_host="8.8.8.8"))
        assert exc.value.status_code == 403

    def test_allow_helpers(self):
        r_local = _mk_request(client_host="127.0.0.1")
        r_ext = _mk_request(client_host="8.8.8.8")
        assert cp.allow_legacy_header_auth(r_local) is True
        assert cp.allow_legacy_header_auth(r_ext) is False
        assert cp.allow_select_login(r_local) is True
        assert cp.allow_seed_admin(r_local) is True
        assert cp.allow_local_file_control(r_local) is True
        assert cp.allow_local_file_control(r_ext) is False
