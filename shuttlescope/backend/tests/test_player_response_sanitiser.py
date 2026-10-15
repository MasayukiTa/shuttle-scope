"""player ロール向け応答サニタイザのテスト (2026-10-15 監査 行 8-14)。

  1. 純関数 sanitize_for_player / クエリ除去 (宣言テーブルの単体テスト)
  2. 純 ASGI ミドルウェア (非 JSON・ストリーミング・fail-closed・Content-Length)
  3. 実アプリ + player JWT での統合テスト (ルート群ごとに落ちるキーを固定)
  4. analyst / coach / admin は無加工とバイト単位で同一
"""
from __future__ import annotations

import copy
import json

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, StreamingResponse
from starlette.routing import Route
from starlette.testclient import TestClient as StarletteClient
from fastapi.testclient import TestClient

from backend.main import app
from backend.middleware import player_response_sanitiser as mw_mod
from backend.middleware.player_response_sanitiser import PlayerResponseSanitiserMiddleware
from backend.tests.test_player_output_privacy import (  # noqa: F401  (fixtures)
    _OTHER_ROLES, _headers, _player_h, _walk_keys, world,
)
from backend.utils import response_cache
from backend.utils import player_response_sanitiser as san
from backend.utils.player_response_sanitiser import (
    PLAYER_ANNOTATION_FLOW_PATHS, PLAYER_RESPONSE_RULES, UNCERTAINTY_KEYS,
    keys_to_drop, normalize_path, query_params_to_drop, sanitize_for_player,
    strip_query_for_player,
)


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


# ─── 1. 純関数 ───────────────────────────────────────────────────────────────

WIN_META = {"sample_size": 5, "confidence": {"level": "low", "warning": "n<10"}}


class TestPureFunction:
    def test_descriptive_drops_win_keys_keeps_counts_and_meta(self):
        payload = {
            "success": True,
            "data": {
                "total_matches": 1, "total_rallies": 5, "win_rate": 0.6,
                "avg_rally_length": 2.0, "end_type_distribution": {"smash_winner": 5},
                "win_by_end_type": {"smash_winner": {"wins": 3, "total": 5}},
                "server_win_rate": {"as_server": 0.6, "as_receiver": 0.0},
            },
            "meta": WIN_META,
        }
        out = sanitize_for_player("/api/analysis/descriptive", payload)
        assert out["data"] == {
            "total_matches": 1, "total_rallies": 5, "avg_rally_length": 2.0,
            "end_type_distribution": {"smash_winner": 5},
            "win_by_end_type": {},  # 画面が Object.entries で落ちないよう空に置換
        }
        assert out["meta"] == WIN_META  # 不確実性メタは無傷

    def test_input_not_mutated(self):
        payload = {"data": [{"shot_type": "clear", "count": 5, "win_rate": 0.6}], "meta": WIN_META}
        before = copy.deepcopy(payload)
        out = sanitize_for_player("/api/analysis/shot_types", payload)
        assert payload == before
        assert out["data"] == [{"shot_type": "clear", "count": 5}]

    @pytest.mark.parametrize("path,payload,gone,kept", [
        ("/api/analysis/set_comparison",
         {"data": [{"set_number": 1, "total_rallies": 5, "win_rate": 0.6}]},
         {"win_rate"}, {"set_number", "total_rallies"}),
        ("/api/analysis/tournament_level_comparison",
         {"data": {"levels": [{"level": "x", "match_count": 1, "win_rate": 1.0, "sample_size": 5}]}},
         {"win_rate"}, {"level", "match_count", "sample_size"}),
        ("/api/analysis/zone_detail",
         {"data": {"zone": "BL", "total_shots": 4, "win_rate": 0.5,
                   "shot_breakdown": [{"shot_type": "clear", "count": 2, "win_rate": 0.5}]}},
         {"win_rate"}, {"zone", "total_shots", "shot_breakdown", "shot_type", "count"}),
        ("/api/analysis/effective_distribution_map",
         {"data": {"zone_effectiveness": {"BR": {"win_count": 3, "total_count": 5, "win_rate": 0.6,
                                                 "effectiveness": 0.6}}, "top_zones": ["BR"]}},
         {"win_count", "win_rate", "effectiveness"}, {"total_count", "top_zones", "BR"}),
        ("/api/analysis/effective_distribution_map/zone_detail",
         {"data": {"zone": "BR", "total_count": 5, "win_count": 3, "win_rate": 0.6}},
         {"win_count", "win_rate"}, {"zone", "total_count"}),
        ("/api/analysis/matches_summary",
         {"data": [{"match_id": 1, "opponent": "O", "result": "win", "rally_count": 5,
                    "set_scores": [{"set_num": 1, "score_player": 21, "score_opponent": 10, "won": True}]}]},
         {"result", "score_player", "score_opponent", "won", "set_num"},
         {"match_id", "opponent", "rally_count", "set_scores"}),
        ("/api/analysis/score_progression",
         {"data": {"sets": [{"set_id": 1, "rallies": [
             {"rally_id": 1, "score_a": 1, "score_b": 0, "winner": "player_a", "point_diff": 1,
              "server": "player_a", "rally_length": 2}], "momentum_changes": [1]}]},
          "meta": WIN_META},
         {"score_a", "score_b", "winner", "point_diff"},
         {"rally_id", "server", "rally_length", "meta", "momentum_changes"}),
        ("/api/analysis/set_summary",
         {"data": {"set_num": 1, "score_a": 5, "score_b": 0, "winner": "player_a",
                   "total_rallies": 5, "recent_loss_patterns": [{"label": "x"}],
                   "effective_shots": [{"shot_type": "clear", "win_rate": 0.6, "count": 5}],
                   "risky_shots": []}},
         {"score_a", "score_b", "winner", "win_rate", "label"},
         {"set_num", "total_rallies", "effective_shots", "shot_type", "count",
          "recent_loss_patterns", "risky_shots"}),
        ("/api/matches",
         {"data": [{"id": 1, "result": "win", "final_score": "21-10", "tournament": "Cup"}]},
         {"result", "final_score"}, {"id", "tournament"}),
        ("/api/matches/needs_review",
         {"data": [{"id": 1, "result": "win", "final_score": "21-10"}]},
         {"result", "final_score"}, {"id"}),
        ("/api/matches/12",
         {"data": {"id": 12, "result": "loss", "final_score": "10-21", "player_a": {"id": 1}}},
         {"result", "final_score"}, {"id", "player_a"}),
        ("/api/matches/12/rallies",
         {"data": [{"id": 1, "winner": "player_a", "score_a_after": 1, "rally_num": 1}]},
         {"winner", "score_a_after"}, {"id", "rally_num"}),
        ("/api/players/3/matches",
         {"data": [{"id": 1, "result": "win"}]}, {"result"}, {"id"}),
        ("/api/players/3/stats",
         {"data": {"total_matches": 4, "wins": 3}}, {"wins"}, {"total_matches"}),
        ("/api/review/playlist",
         {"rallies": [{"id": 1, "winner": "player_a", "score_a_before": 0, "score_b_before": 0,
                       "score_a_after": 1, "score_b_after": 0, "end_type": "ace",
                       "video_timestamp_start": 3.0}]},
         {"winner", "score_a_before", "score_b_before", "score_a_after", "score_b_after"},
         {"id", "end_type", "video_timestamp_start"}),
        ("/api/conditions/best_profile",
         {"data": {"win_rate_in_profile": 1.0, "win_rate_outside": None, "n_matches": 1,
                   "n_top": 1, "confidence": "low", "top_profile": {"ccs_score": {"mean": 55}}}},
         {"win_rate_in_profile", "win_rate_outside"},
         {"n_matches", "n_top", "confidence", "top_profile"}),
        ("/api/reports/interval_flash",
         {"data": {"match_id": 1, "set_scores": [{"set_num": 1, "winner": "player_a"}],
                   "sets_a": 1, "sets_b": 0, "current_leader": "player_a",
                   "disclaimer": "d"}, "meta": WIN_META},
         {"sets_a", "sets_b", "current_leader", "winner", "set_num"},
         {"match_id", "disclaimer", "meta", "set_scores"}),
    ])
    def test_table_rows(self, path, payload, gone, kept):
        out = sanitize_for_player(path, payload)
        keys_out = _walk_keys(out)
        assert not (gone & keys_out), gone & keys_out
        assert kept <= keys_out, kept - keys_out
        # 落とした分だけ減っている (他のキーは同数のまま)
        assert keys_out == _walk_keys(payload) - gone

    def test_neutralised_keys_become_empty_values_not_missing(self):
        """画面が .map / .length を直接呼ぶキーは、削除でなく空に置換する (描画が落ちない)。"""
        out = sanitize_for_player("/api/analysis/set_summary", {"data": {
            "risky_shots": [{"shot_type": "x"}], "recent_loss_patterns": [{"label": "y"}]}})
        assert out == {"data": {"risky_shots": [], "recent_loss_patterns": []}}
        out = sanitize_for_player("/api/analysis/score_progression", {"data": {"sets": [
            {"momentum_changes": [3, 4], "rallies": []}]}})
        assert out["data"]["sets"][0]["momentum_changes"] == []
        out = sanitize_for_player("/api/analysis/matches_summary", {"data": [
            {"set_scores": [{"won": True}]}]})
        assert out["data"][0]["set_scores"] == []

    def test_neutral_value_is_not_shared_between_calls(self):
        a = sanitize_for_player("/api/analysis/set_summary", {"risky_shots": [1]})
        a["risky_shots"].append("mutated")
        b = sanitize_for_player("/api/analysis/set_summary", {"risky_shots": [1]})
        assert b["risky_shots"] == []

    def test_unlisted_path_is_returned_as_is(self):
        payload = {"data": {"win_rate": 0.5, "result": "win"}}
        assert sanitize_for_player("/api/some/other", payload) is payload

    def test_non_get_is_untouched(self):
        payload = {"data": {"id": 1, "winner": "player_a", "result": "win"}}
        assert sanitize_for_player("/api/matches/1", payload, method="PUT") is payload
        assert keys_to_drop("/api/matches/1", "POST") == frozenset()

    @pytest.mark.parametrize("path", [
        "/api/analysis/descriptive/", "//api//analysis//descriptive", "/api/./analysis/descriptive",
        "/API/Analysis/Descriptive",
    ])
    def test_path_variants_still_match(self, path):
        assert "win_rate" in keys_to_drop(path)

    def test_normalize_path(self):
        assert normalize_path("//api///x/./y/") == "/api/x/y"

    @pytest.mark.parametrize("path", [
        "/api/rallies/match/1", "/api/sets/match/1", "/api/annotation/1/state",
    ])
    def test_annotation_flow_is_deliberately_not_sanitised(self, path):
        assert any(p.fullmatch(path) for p in PLAYER_ANNOTATION_FLOW_PATHS)
        assert keys_to_drop(path) == frozenset()

    def test_every_rule_does_something_and_uncertainty_keys_are_never_dropped(self):
        for r in PLAYER_RESPONSE_RULES:
            assert r.keys or r.drop_query, r.name
            assert not (r.keys & UNCERTAINTY_KEYS), (r.name, r.keys & UNCERTAINTY_KEYS)
            assert not (r.keys & {"sample_size", "confidence", "n", "rally_count", "meta"})

    def test_rule_names_unique(self):
        names = [r.name for r in PLAYER_RESPONSE_RULES]
        assert len(names) == len(set(names))


class TestQueryStrip:
    def test_result_filter_dropped_on_stable_routes(self):
        q = b"player_id=1&result=win&tournament_level=x"
        assert strip_query_for_player("/api/analysis/shot_types", q) == b"player_id=1&tournament_level=x"
        assert query_params_to_drop("/api/analysis/descriptive") >= {"result"}

    def test_repeated_and_encoded_names(self):
        q = b"result=win&player_id=1&%72esult=loss&Result=x"
        out = strip_query_for_player("/api/analysis/descriptive", q)
        assert out == b"player_id=1&Result=x"

    def test_playlist_winner_filter_dropped(self):
        out = strip_query_for_player("/api/review/playlist", b"match_id=1&winner=player_a&set_num=1")
        assert out == b"match_id=1&set_num=1"

    def test_other_paths_untouched(self):
        q = b"result=win&x=1"
        assert strip_query_for_player("/api/other", q) is q


# ─── 2. ミドルウェア単体 (小さな ASGI アプリ) ────────────────────────────────

def _wrap(inner_app):
    return PlayerResponseSanitiserMiddleware(inner_app)


class TestMiddlewareUnit:
    def _client(self, routes, monkeypatch, player=True):
        monkeypatch.setattr(mw_mod, "_is_player", lambda scope: player)
        return StarletteClient(_wrap(Starlette(routes=routes)))

    def test_json_rewritten_and_content_length_correct(self, monkeypatch):
        async def ep(request):
            return JSONResponse({"data": {"win_rate": 0.6, "total_rallies": 5}, "meta": WIN_META})
        c = self._client([Route("/api/analysis/descriptive", ep)], monkeypatch)
        r = c.get("/api/analysis/descriptive")
        assert r.json() == {"data": {"total_rallies": 5}, "meta": WIN_META}
        assert int(r.headers["content-length"]) == len(r.content)

    def test_non_player_bytes_identical(self, monkeypatch):
        async def ep(request):
            return JSONResponse({"data": {"win_rate": 0.6}})
        routes = [Route("/api/analysis/descriptive", ep)]
        base = StarletteClient(Starlette(routes=routes)).get("/api/analysis/descriptive")
        r = self._client(routes, monkeypatch, player=False).get("/api/analysis/descriptive")
        assert r.content == base.content and r.headers["content-length"] == base.headers["content-length"]

    def test_non_json_response_untouched(self, monkeypatch):
        async def ep(request):
            return PlainTextResponse("win_rate=0.6")
        c = self._client([Route("/api/analysis/descriptive", ep)], monkeypatch)
        assert c.get("/api/analysis/descriptive").text == "win_rate=0.6"

    def test_stream_non_json_not_buffered(self, monkeypatch):
        async def gen():
            for i in range(3):
                yield f"chunk{i}".encode()

        async def ep(request):
            return StreamingResponse(gen(), media_type="video/mp4")
        c = self._client([Route("/api/analysis/descriptive", ep)], monkeypatch)
        assert c.get("/api/analysis/descriptive").content == b"chunk0chunk1chunk2"

    def test_chunked_json_stream_is_sanitised(self, monkeypatch):
        async def gen():
            yield b'{"data": {"win_ra'
            yield b'te": 0.6, "n": 3}}'

        async def ep(request):
            return StreamingResponse(gen(), media_type="application/json")
        c = self._client([Route("/api/analysis/descriptive", ep)], monkeypatch)
        r = c.get("/api/analysis/descriptive")
        assert r.json() == {"data": {"n": 3}}
        assert int(r.headers["content-length"]) == len(r.content)

    def test_unparseable_json_fails_closed_500(self, monkeypatch):
        async def ep(request):
            return StreamingResponse(iter([b'{"win_rate": 0.6, oops']), media_type="application/json")
        c = self._client([Route("/api/analysis/descriptive", ep)], monkeypatch)
        r = c.get("/api/analysis/descriptive")
        assert r.status_code == 500 and b"win_rate" not in r.content

    def test_sanitiser_exception_fails_closed_500(self, monkeypatch):
        async def ep(request):
            return JSONResponse({"data": {"win_rate": 0.6}})

        def boom(*a, **k):
            raise RuntimeError("x")
        monkeypatch.setattr(mw_mod, "sanitize_for_player", boom)
        c = self._client([Route("/api/analysis/descriptive", ep)], monkeypatch)
        r = c.get("/api/analysis/descriptive")
        assert r.status_code == 500 and b"0.6" not in r.content

    def test_compressed_json_fails_closed_500(self, monkeypatch):
        async def ep(request):
            return JSONResponse({"data": {"win_rate": 0.6}}, headers={"content-encoding": "gzip"})
        c = self._client([Route("/api/analysis/descriptive", ep)], monkeypatch)
        assert c.get("/api/analysis/descriptive").status_code == 500

    def test_unlisted_path_passthrough_even_for_player(self, monkeypatch):
        async def ep(request):
            return JSONResponse({"win_rate": 0.6})
        c = self._client([Route("/api/free", ep)], monkeypatch)
        assert c.get("/api/free").json() == {"win_rate": 0.6}

    def test_post_untouched(self, monkeypatch):
        async def ep(request):
            return JSONResponse({"result": "win"})
        c = self._client([Route("/api/matches", ep, methods=["POST"])], monkeypatch)
        assert c.post("/api/matches").json() == {"result": "win"}

    def test_result_query_not_seen_by_player_handler(self, monkeypatch):
        seen = {}

        async def ep(request):
            seen["q"] = dict(request.query_params)
            return JSONResponse({"data": {}})
        c = self._client([Route("/api/analysis/shot_types", ep)], monkeypatch)
        c.get("/api/analysis/shot_types?player_id=1&result=win")
        assert seen["q"] == {"player_id": "1"}
        monkeypatch.setattr(mw_mod, "_is_player", lambda scope: False)
        c.get("/api/analysis/shot_types?player_id=1&result=win")
        assert seen["q"] == {"player_id": "1", "result": "win"}

    def test_role_detection_failure_is_treated_as_player(self, monkeypatch):
        import backend.utils.auth as auth_mod

        def boom(request):
            raise RuntimeError("auth down")
        monkeypatch.setattr(auth_mod, "get_auth", boom)
        assert mw_mod._is_player({"type": "http", "headers": [], "method": "GET", "path": "/x",
                                  "query_string": b""}) is True


# ─── 3/4. 実アプリ統合 ───────────────────────────────────────────────────────

def _routes(w):
    from backend.db.models import GameSet
    pid, mid = w["own"].id, w["match"].id
    sid = w["db"].query(GameSet).filter(GameSet.match_id == mid).first().id
    base = f"player_id={pid}"
    return {
        "descriptive": f"/api/analysis/descriptive?{base}",
        "shot_types": f"/api/analysis/shot_types?{base}",
        "set_comparison": f"/api/analysis/set_comparison?{base}",
        "tournament_level_comparison": f"/api/analysis/tournament_level_comparison?{base}",
        "zone_detail": f"/api/analysis/zone_detail?{base}&zone=BR&type=land",
        "heatmap_zone_detail": f"/api/analysis/heatmap_zone_detail?{base}&zone=BR&type=land",
        "effective_distribution_map": f"/api/analysis/effective_distribution_map?{base}",
        "effective_distribution_map_zone_detail":
            f"/api/analysis/effective_distribution_map/zone_detail?{base}&zone=BR",
        "matches_summary": f"/api/analysis/matches_summary?{base}",
        "score_progression": f"/api/analysis/score_progression?match_id={mid}&{base}",
        "set_summary": f"/api/analysis/set_summary?set_id={sid}",
        "matches": "/api/matches",
        "matches_needs_review": "/api/matches/needs_review",
        "match_detail": f"/api/matches/{mid}",
        "match_rallies": f"/api/matches/{mid}/rallies",
        "player_matches": f"/api/players/{pid}/matches",
        "player_stats": f"/api/players/{pid}/stats",
        "playlist": f"/api/review/playlist?match_id={mid}",
        "best_profile": f"/api/conditions/best_profile?{base}",
        "interval_flash": f"/api/reports/interval_flash?match_id={mid}&completed_set_num=1&{base}",
    }


# route -> player が失うキー (analyst のキー集合 − player のキー集合)。実測で固定。
EXPECTED_REMOVED = {
    "descriptive": {"win_rate", "wins", "server_win_rate", "as_server", "as_receiver"},
    "zone_detail": {"win_rate"},
    "heatmap_zone_detail": {"win_rate", "wins"},
    "shot_types": {"win_rate"},
    "set_comparison": {"win_rate"},
    "tournament_level_comparison": {"win_rate"},
    "effective_distribution_map": {"win_count", "win_rate", "effectiveness"},
    "effective_distribution_map_zone_detail": {"win_count", "win_rate"},
    "matches_summary": {"result", "score_player", "score_opponent", "won", "set_num"},
    "score_progression": {"score_a", "score_b", "winner", "point_diff"},
    "set_summary": {"score_a", "score_b", "winner", "win_rate", "pct"},
    "matches": {"result", "final_score"},
    "matches_needs_review": {"result", "final_score"},
    "match_detail": {"result", "final_score"},
    "match_rallies": {"winner", "score_a_before", "score_b_before", "score_a_after", "score_b_after"},
    "player_matches": {"result"},
    "player_stats": {"wins"},
    "playlist": {"winner", "score_a_before", "score_b_before", "score_a_after", "score_b_after"},
    "best_profile": {"win_rate_in_profile", "win_rate_outside"},
    "interval_flash": {"winner", "current_leader", "rally_wins_a", "rally_wins_b",
                       "sets_a", "sets_b", "score_a", "score_b", "set_num"},
}


def _get(client, url, headers):
    response_cache.MEMORY_CACHE.clear()
    return client.get(url, headers=headers)


class TestIntegration:
    def test_player_loses_exactly_the_declared_keys(self, world, client, monkeypatch):
        """同じ player トークンで、関門あり / なし (= 変更前) を比べ、落ちたキーを固定する。"""
        w = world
        live = {n: _get(client, u, _player_h(w)) for n, u in _routes(w).items()}
        monkeypatch.setattr(mw_mod, "_is_player", lambda scope: False)
        raw = {n: _get(client, u, _player_h(w)) for n, u in _routes(w).items()}
        bad: dict[str, object] = {}
        for name in live:
            if live[name].status_code != 200 or raw[name].status_code != 200:
                bad[name] = ("status", live[name].status_code, raw[name].status_code)
                continue
            removed = _walk_keys(raw[name].json()) - _walk_keys(live[name].json())
            added = _walk_keys(live[name].json()) - _walk_keys(raw[name].json())
            if added or removed != EXPECTED_REMOVED.get(name, set()):
                bad[name] = {"removed": sorted(removed), "added": sorted(added)}
        assert not bad, json.dumps(bad, sort_keys=True)

    def test_player_payloads_have_no_outcome_keys_anywhere(self, world, client):
        banned = {"win_rate", "wins", "win_count", "winner", "result", "final_score",
                  "score_a", "score_b", "server_win_rate"}
        w = world
        for name, url in _routes(w).items():
            rp = _get(client, url, _player_h(w))
            if rp.status_code == 200:
                assert not (_walk_keys(rp.json()) & banned), (name, _walk_keys(rp.json()) & banned)

    def test_uncertainty_meta_survives(self, world, client):
        w = world
        r = _get(client, _routes(w)["descriptive"], _player_h(w)).json()
        assert r["meta"]["sample_size"] == 5
        assert r["meta"]["confidence"]["level"] == "low"
        assert r["data"]["total_rallies"] == 5
        r = _get(client, _routes(w)["set_summary"], _player_h(w)).json()
        assert "confidence" in r["meta"] and "sample_size" in r["meta"]
        r = _get(client, _routes(w)["best_profile"], _player_h(w)).json()
        assert r["data"]["confidence"] == "low" and r["data"]["n_matches"] == 1
        r = _get(client, _routes(w)["player_stats"], _player_h(w)).json()
        assert r["data"]["total_matches"] == 1

    def test_content_length_matches_body(self, world, client):
        w = world
        for name, url in _routes(w).items():
            rp = _get(client, url, _player_h(w))
            if rp.status_code == 200 and "content-length" in rp.headers:
                assert int(rp.headers["content-length"]) == len(rp.content), name

    @pytest.mark.parametrize("role", _OTHER_ROLES)
    def test_other_roles_bytes_identical_to_unsanitised(self, world, client, role, monkeypatch):
        w = world
        hdr = _headers(role)
        live = {n: _get(client, u, hdr) for n, u in _routes(w).items()}
        # 関門を完全に無効化した場合の応答 (= 変更前の挙動) と比較
        monkeypatch.setattr(mw_mod, "_is_player", lambda scope: False)
        raw = {n: _get(client, u, hdr) for n, u in _routes(w).items()}
        for n in live:
            assert live[n].status_code == raw[n].status_code, n
            assert live[n].content == raw[n].content, n
        assert any(r.status_code == 200 for r in live.values())

    def test_other_roles_keep_win_data(self, world, client):
        w = world
        for role in _OTHER_ROLES:
            r = _get(client, _routes(w)["descriptive"], _headers(role)).json()
            assert r["data"]["win_rate"] == 0.6
            r = _get(client, _routes(w)["matches"], _headers(role)).json()
            assert r["data"][0]["result"] == "win"

    def test_result_filter_ignored_for_player(self, world, client):
        w = world
        pid = w["own"].id
        base = _get(client, f"/api/analysis/shot_types?player_id={pid}", _player_h(w)).json()
        for val in ("win", "loss"):
            r = _get(client, f"/api/analysis/shot_types?player_id={pid}&result={val}", _player_h(w))
            assert r.status_code == 200
            assert r.json() == base
        # analyst では従来どおり絞り込まれる (試合結果は win なので loss は空)
        a_loss = _get(client, f"/api/analysis/shot_types?player_id={pid}&result=loss", _headers("analyst"))
        a_all = _get(client, f"/api/analysis/shot_types?player_id={pid}", _headers("analyst"))
        assert a_loss.json() != a_all.json()

    def test_playlist_winner_filter_ignored_for_player(self, world, client):
        w = world
        mid = w["match"].id
        full = _get(client, f"/api/review/playlist?match_id={mid}", _player_h(w)).json()
        filt = _get(client, f"/api/review/playlist?match_id={mid}&winner=player_a", _player_h(w)).json()
        assert len(full["rallies"]) == len(filt["rallies"]) == 5
        a = _get(client, f"/api/review/playlist?match_id={mid}&winner=player_a", _headers("analyst")).json()
        assert len(a["rallies"]) == 3

    def test_annotation_flow_still_returns_outcomes_for_player(self, world, client):
        w = world
        mid = w["match"].id
        r = _get(client, f"/api/rallies/match/{mid}", _player_h(w))
        assert r.status_code == 200 and all("winner" in x for x in r.json()["data"])
        r = _get(client, f"/api/sets/match/{mid}", _player_h(w))
        assert r.status_code == 200 and "winner" in r.json()["data"][0]
        r = _get(client, f"/api/annotation/{mid}/state", _player_h(w))
        assert r.status_code == 200 and "score_a" in r.json()["data"]

    def test_unauthenticated_and_forbidden_still_denied(self, world, client):
        r = client.get("/api/analysis/shot_win_loss?player_id=1", headers=_player_h(world))
        assert r.status_code == 403

    def test_registered_in_app(self):
        assert any(m.cls is PlayerResponseSanitiserMiddleware for m in app.user_middleware)
