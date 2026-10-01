"""iPhone の HEVC 動画をブラウザで再生できる形にする (受け入れ側で解決する)。

撮影側に「互換性優先で撮ってください」と頼むのは回避策で、受け取る側が
再生できる形にするのが根本。仕様:

  1. source が h264 / vp8 / vp9 以外 (HEVC など) なら、H.264 の再生互換版 ("play")
     を作る。720p の HEVC でも作る (従来は「upscale 不要」で何も作られなかった)
  2. 配信は、画質を明示されなければ再生互換版があればそれを返す。
     明示の quality=source だけは本当の元ファイルを返す
  3. 主動画だけでなく、二視点の 2 本目 (Recording 枝番) も同じ扱いにする
  4. h264 の source は従来どおり何も変わらない (回帰させない)

ffmpeg はローカルに無いことがあるので、ここでは判定と配信の選択だけを固定する。
実際の HEVC → H.264 変換は本番の ffmpeg で確認する。
"""
from __future__ import annotations

import uuid
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.db.database import get_db
from backend.db.models import Match, Player, Recording
from backend.main import app
from backend.services import video_variants as vv
from backend.services.video_variants import (
    PLAYBACK_QUALITY,
    ProbeResult,
    decide_playback,
    decide_variants,
    generate_all_for_source,
    list_available_qualities,
    playback_variant_file,
)


def _probe(codec: str, h: int, w: int | None = None) -> ProbeResult:
    return ProbeResult(height=h, width=w or int(h * 16 / 9), codec=codec,
                       duration_sec=60.0, fps=30.0)


class TestDecidePlayback:
    @pytest.mark.parametrize("codec", ["h264", "vp8", "vp9", "H264"])
    def test_browser_safe_codecs_need_no_playback_copy(self, codec):
        assert decide_playback(_probe(codec, 1080)) is None

    @pytest.mark.parametrize("codec", ["hevc", "h265", "prores", "mpeg2video", "av1", "wmv3"])
    def test_everything_else_gets_one(self, codec):
        plan = decide_playback(_probe(codec, 1080))
        assert plan is not None and plan.quality == PLAYBACK_QUALITY

    def test_an_unknown_codec_is_not_assumed_to_play(self):
        # 「たぶん再生できる」側に倒すと、映らない原因が見えなくなる
        assert decide_playback(_probe("", 1080)) is not None

    @pytest.mark.parametrize("src_h,want", [(2160, 1080), (1080, 1080), (720, 720), (480, 480)])
    def test_height_follows_the_source_capped_at_1080(self, src_h, want):
        assert decide_playback(_probe("hevc", src_h)).target_h == want

    def test_probe_failure_or_bad_dimensions_make_nothing(self):
        assert decide_playback(None) is None
        assert decide_playback(_probe("hevc", 0, 0)) is None

    def test_absurdly_large_sources_are_still_refused(self):
        assert decide_playback(_probe("hevc", 8192, 8192)) is None


class TestGenerateAllForSource:
    """ffmpeg を呼ばずに、どの画質を作ろうとするかだけを見る。"""

    @staticmethod
    def _run(monkeypatch, tmp_path, probe):
        src = tmp_path / "abc.mov"
        src.write_bytes(b"x" * 2048)
        made = []

        monkeypatch.setattr(vv, "probe_source", lambda p: probe)

        def fake_generate(source, target, target_h, crf):
            made.append((Path(target).name, target_h, crf))
            return True, "ok"

        monkeypatch.setattr(vv, "generate_variant", fake_generate)
        result = generate_all_for_source(src, tmp_path, "abc")
        return result, made

    def test_hevc_1080p_makes_play_first_then_hd(self, monkeypatch, tmp_path):
        result, made = self._run(monkeypatch, tmp_path, _probe("hevc", 1080))
        assert [m[0] for m in made] == ["abc_play.mp4", "abc_hd.mp4"]
        assert made[0][1] == 1080
        assert result["play"].startswith("ok")

    def test_hevc_720p_used_to_produce_nothing_and_now_makes_play(self, monkeypatch, tmp_path):
        result, made = self._run(monkeypatch, tmp_path, _probe("hevc", 720))
        assert [m[0] for m in made] == ["abc_play.mp4"]
        assert "_skipped" not in result

    def test_h264_720p_is_unchanged(self, monkeypatch, tmp_path):
        result, made = self._run(monkeypatch, tmp_path, _probe("h264", 720))
        assert made == []
        assert "_skipped" in result

    def test_h264_1080p_is_unchanged(self, monkeypatch, tmp_path):
        _, made = self._run(monkeypatch, tmp_path, _probe("h264", 1080))
        assert [m[0] for m in made] == ["abc_hd.mp4"]

    def test_the_existing_plan_function_is_untouched(self):
        assert [p.quality for p in decide_variants(_probe("hevc", 1080))] == ["hd"]


class TestPlaybackVariantFile:
    def _variants(self, tmp_path) -> Path:
        d = tmp_path / "variants"
        d.mkdir()
        return d

    def test_absent(self, tmp_path):
        assert playback_variant_file(tmp_path, "abc") is None

    def test_an_empty_file_is_not_a_variant(self, tmp_path):
        (self._variants(tmp_path) / "abc_play.mp4").write_bytes(b"")
        assert playback_variant_file(tmp_path, "abc") is None

    def test_present(self, tmp_path):
        p = self._variants(tmp_path) / "abc_play.mp4"
        p.write_bytes(b"data")
        assert playback_variant_file(tmp_path, "abc") == p

    @pytest.mark.parametrize("bad", ["../abc", "a/b", "a\\b", "..", ""])
    def test_path_tricks_are_refused(self, tmp_path, bad):
        assert playback_variant_file(tmp_path, bad) is None


# ─── 配信 ────────────────────────────────────────────────────────────────

SRC_BYTES = b"SOURCE-HEVC-BYTES"
PLAY_BYTES = b"PLAYBACK-H264-BYTES"
# 32 桁 hex の固定文字列は API キーに見えて DevSkim (DS173237) が拾う。
# 値そのものに意味は無い (アップロード ID と配信トークンの形だけ要る) ので、
# 都度生成にして「秘密っぽい定数」をソースに置かない。
UID = uuid.uuid4().hex
TOKEN = uuid.uuid4().hex


@pytest.fixture()
def upload_dir(tmp_path, monkeypatch):
    import backend.routers.uploads as uploads
    monkeypatch.setattr(uploads, "UPLOAD_DIR", tmp_path)
    (tmp_path / f"{UID}.mov").write_bytes(SRC_BYTES)
    return tmp_path


def _add_play(upload_dir: Path) -> None:
    d = upload_dir / "variants"
    d.mkdir(exist_ok=True)
    (d / f"{UID}_play.mp4").write_bytes(PLAY_BYTES)


def _make_match(db_session, **extra) -> Match:
    a, b = Player(name="A"), Player(name="B")
    db_session.add_all([a, b])
    db_session.flush()
    m = Match(tournament="t", tournament_level="practice", round="R1",
              date=date(2026, 9, 29), venue="v", format="singles",
              result="win", final_score="21-10",
              player_a_id=a.id, player_b_id=b.id, **extra)
    db_session.add(m)
    db_session.commit()
    return m


def _client(db_session) -> TestClient:
    app.dependency_overrides[get_db] = lambda: db_session
    # TrustedHostMiddleware rejects TestClient's default "testserver" host.
    return TestClient(
        app,
        base_url="http://localhost",
        raise_server_exceptions=False,
    )


class TestMatchStreamServesPlayableCopy:
    def _match(self, db_session):
        return _make_match(db_session, video_local_path=f"server://{UID}.mov",
                           video_token=TOKEN)

    def test_a_playback_copy_replaces_an_unplayable_source(self, db_session, upload_dir):
        _add_play(upload_dir)
        m = self._match(db_session)
        try:
            r = _client(db_session).get(
                f"/api/v1/uploads/video/by_match/{m.id}/stream?token={TOKEN}")
        finally:
            app.dependency_overrides.clear()
        assert r.status_code == 200, r.text
        assert r.content == PLAY_BYTES
        assert r.headers["content-type"].startswith("video/mp4")

    def test_range_requests_work_on_the_playback_copy(self, db_session, upload_dir):
        _add_play(upload_dir)
        m = self._match(db_session)
        try:
            r = _client(db_session).get(
                f"/api/v1/uploads/video/by_match/{m.id}/stream?token={TOKEN}",
                headers={"Range": "bytes=0-3"})
        finally:
            app.dependency_overrides.clear()
        assert r.status_code == 206
        assert r.content == PLAY_BYTES[:4]

    def test_explicit_source_still_returns_the_real_source(self, db_session, upload_dir):
        _add_play(upload_dir)
        m = self._match(db_session)
        try:
            r = _client(db_session).get(
                f"/api/v1/uploads/video/by_match/{m.id}/stream?token={TOKEN}&quality=source")
        finally:
            app.dependency_overrides.clear()
        assert r.status_code == 200, r.text
        assert r.content == SRC_BYTES

    def test_no_playback_copy_yet_falls_back_to_the_source(self, db_session, upload_dir):
        m = self._match(db_session)
        try:
            r = _client(db_session).get(
                f"/api/v1/uploads/video/by_match/{m.id}/stream?token={TOKEN}")
        finally:
            app.dependency_overrides.clear()
        assert r.status_code == 200, r.text
        assert r.content == SRC_BYTES

    def test_a_missing_hd_variant_falls_back_to_the_playable_copy(self, db_session, upload_dir):
        _add_play(upload_dir)
        m = self._match(db_session)
        try:
            r = _client(db_session).get(
                f"/api/v1/uploads/video/by_match/{m.id}/stream?token={TOKEN}&quality=hd")
        finally:
            app.dependency_overrides.clear()
        assert r.status_code == 200, r.text
        assert r.content == PLAY_BYTES

    def test_malformed_server_ref_never_reaches_filesystem(self, db_session, upload_dir):
        outside = upload_dir.parent / "outside.mp4"
        outside.write_bytes(b"secret")
        m = _make_match(
            db_session,
            video_local_path="server://../outside.mp4",
            video_token=TOKEN,
        )
        try:
            r = _client(db_session).get(
                f"/api/v1/uploads/video/by_match/{m.id}/stream?token={TOKEN}"
            )
        finally:
            app.dependency_overrides.clear()
        assert r.status_code == 404
        assert r.content != b"secret"


class TestRecordingStreamServesPlayableCopy:
    """二視点の 2 本目は Recording 枝番に載る。"""

    def _rec(self, db_session):
        m = _make_match(db_session)
        rec = Recording(match_id=m.id, branch_no=1, kind="upload", status="ready",
                        video_local_path=f"server://{UID}.mov", video_token=TOKEN)
        db_session.add(rec)
        db_session.commit()
        return rec

    def test_a_playback_copy_replaces_an_unplayable_source(self, db_session, upload_dir):
        _add_play(upload_dir)
        rec = self._rec(db_session)
        try:
            r = _client(db_session).get(f"/api/recordings/{rec.id}/stream?token={TOKEN}")
        finally:
            app.dependency_overrides.clear()
        assert r.status_code == 200, r.text
        assert r.content == PLAY_BYTES

    def test_without_a_playback_copy_the_source_is_served(self, db_session, upload_dir):
        rec = self._rec(db_session)
        try:
            r = _client(db_session).get(f"/api/recordings/{rec.id}/stream?token={TOKEN}")
        finally:
            app.dependency_overrides.clear()
        assert r.status_code == 200, r.text
        assert r.content == SRC_BYTES


class TestVariantJobCoversRecordings:
    def test_every_distinct_server_video_of_the_match_is_processed(
        self, db_session, upload_dir, monkeypatch
    ):
        from backend.pipeline import video_pipeline

        uid2, uid3 = "b" * 32, "c" * 32
        (upload_dir / f"{uid2}.mov").write_bytes(b"2")
        (upload_dir / f"{uid3}.mov").write_bytes(b"3")
        m = _make_match(db_session, video_local_path=f"server://{UID}.mov")
        db_session.add_all([
            Recording(match_id=m.id, branch_no=1, kind="upload", status="ready",
                      video_local_path=f"server://{uid2}.mov"),
            # 主動画と同じ upload_id: 二重に変換しない
            Recording(match_id=m.id, branch_no=2, kind="upload", status="ready",
                      video_local_path=f"server://{UID}.mov"),
            Recording(match_id=m.id, branch_no=3, kind="upload", status="ready",
                      video_local_path=f"server://{uid3}.mov"),
            # server:// でないものは対象外
            Recording(match_id=m.id, branch_no=4, kind="live", status="ready",
                      video_local_path="localfile:///C:/x.mp4"),
        ])
        db_session.commit()

        called = []
        monkeypatch.setattr(
            vv, "generate_all_for_source",
            lambda src, up, uid: called.append(uid) or {"play": "ok"},
        )
        out = video_pipeline._run_video_variant_job(db_session, m.id)

        assert called == [UID, uid2, uid3]
        assert set(out) == {"variants", "recording_1", "recording_3"}


class TestPlaybackQualityState:
    def test_play_quality_is_visible_while_preparing(self, tmp_path):
        options = list_available_qualities(
            tmp_path, "abc", 720, playback_height=720,
        )
        play = next(q for q in options if q["quality"] == "play")
        assert play == {"quality": "play", "height": 720, "ready": False}

        variants = tmp_path / "variants"
        variants.mkdir(exist_ok=True)
        (variants / "abc_play.mp4").write_bytes(b"x" * 2048)
        options = list_available_qualities(
            tmp_path, "abc", 720, playback_height=720,
        )
        play = next(q for q in options if q["quality"] == "play")
        assert play["ready"] is True

    def test_safe_source_does_not_advertise_play(self, tmp_path):
        options = list_available_qualities(tmp_path, "abc", 720)
        assert all(q["quality"] != "play" for q in options)


class TestVariantSuccessorIsCheap:
    def test_existing_final_variant_is_not_reencoded(self, monkeypatch, tmp_path):
        src = tmp_path / "abc.mov"
        src.write_bytes(b"source" * 400)
        variants = tmp_path / "variants"
        variants.mkdir()
        (variants / "abc_play.mp4").write_bytes(b"ready" * 300)

        monkeypatch.setattr(vv, "probe_source", lambda _p: _probe("hevc", 720))

        def must_not_run(*_args, **_kwargs):
            raise AssertionError("ready variant was re-encoded")

        monkeypatch.setattr(vv, "generate_variant", must_not_run)
        out = generate_all_for_source(src, tmp_path, "abc")
        assert out["play"] == "skip already ready"


class TestMatchAvailableQualityState:
    def test_match_exposes_pending_then_ready_play(
        self, db_session, upload_dir, monkeypatch
    ):
        from backend.routers.matches import _compute_available_qualities

        monkeypatch.setattr(vv, "probe_source", lambda _p: _probe("hevc", 720))
        m = _make_match(db_session, video_local_path=f"server://{UID}.mov")

        options = _compute_available_qualities(m)
        play = next(q for q in options if q["quality"] == "play")
        assert play["ready"] is False

        _add_play(upload_dir)
        options = _compute_available_qualities(m)
        play = next(q for q in options if q["quality"] == "play")
        assert play["ready"] is True


class TestExplicitPlaybackQuality:
    def _match(self, db_session):
        return _make_match(db_session, video_local_path=f"server://{UID}.mov", video_token=TOKEN)

    def test_explicit_play_is_409_while_preparing(self, db_session, upload_dir):
        m = self._match(db_session)
        try:
            r = _client(db_session).get(
                f"/api/v1/uploads/video/by_match/{m.id}/stream?token={TOKEN}&quality=play"
            )
        finally:
            app.dependency_overrides.clear()
        assert r.status_code == 409

    def test_explicit_play_serves_h264_copy(self, db_session, upload_dir):
        _add_play(upload_dir)
        m = self._match(db_session)
        try:
            r = _client(db_session).get(
                f"/api/v1/uploads/video/by_match/{m.id}/stream?token={TOKEN}&quality=play"
            )
        finally:
            app.dependency_overrides.clear()
        assert r.status_code == 200
        assert r.content == PLAY_BYTES
