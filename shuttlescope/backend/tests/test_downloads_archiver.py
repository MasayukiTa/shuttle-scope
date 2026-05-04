"""24h DL 動画アーカイブのユニットテスト。"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest


@pytest.fixture
def isolated_videos_and_archive(tmp_path, monkeypatch):
    videos = tmp_path / "videos"
    videos.mkdir()
    archive = tmp_path / "archive"
    archive.mkdir()

    # cwd を tmp_path にして "./videos" がここを指すようにする
    monkeypatch.chdir(tmp_path)
    # archive_root は SS_LIVE_ARCHIVE_ROOT で上書き
    monkeypatch.setenv("SS_LIVE_ARCHIVE_ROOT", str(archive))

    # config.settings は import 時にキャッシュされるので、属性を直接差し替える
    from backend import config as _cfg
    monkeypatch.setattr(_cfg.settings, "ss_live_archive_root", str(archive), raising=False)

    return videos, archive


def _make_old_file(path: Path, age_seconds: int) -> None:
    path.write_bytes(b"\x00" * 1024)
    past = time.time() - age_seconds
    os.utime(path, (past, past))


def test_scan_skips_recent_file(isolated_videos_and_archive):
    videos, archive = isolated_videos_and_archive
    f = videos / "recent.mp4"
    _make_old_file(f, age_seconds=60)  # 1 分前

    from backend.services.downloads_archiver import scan_once
    result = scan_once()
    assert result["scanned"] == 1
    assert result["moved"] == 0
    assert result["skipped"] == 1
    assert f.exists()
    assert not any(archive.rglob("*.mp4"))


def test_scan_moves_old_file(isolated_videos_and_archive):
    videos, archive = isolated_videos_and_archive
    f = videos / "old.mp4"
    _make_old_file(f, age_seconds=25 * 3600)  # 25h 前

    from backend.services.downloads_archiver import scan_once
    result = scan_once()
    assert result["moved"] == 1
    assert not f.exists()
    moved = list(archive.rglob("*.mp4"))
    assert len(moved) == 1
    # orphan_ プレフィックス（match 紐付けなし）
    assert moved[0].name.startswith("orphan_")


def test_scan_no_archive_root_noop(tmp_path, monkeypatch):
    videos = tmp_path / "videos"
    videos.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SS_LIVE_ARCHIVE_ROOT", raising=False)

    from backend import config as _cfg
    monkeypatch.setattr(_cfg.settings, "ss_live_archive_root", "", raising=False)

    f = videos / "old.mp4"
    _make_old_file(f, age_seconds=25 * 3600)

    from backend.services.downloads_archiver import scan_once
    result = scan_once()
    assert result["archive_root"] is None
    assert result["moved"] == 0
    assert f.exists()


def test_scan_missing_archive_root_returns_flag(tmp_path, monkeypatch):
    videos = tmp_path / "videos"
    videos.mkdir()
    missing = tmp_path / "not_mounted"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SS_LIVE_ARCHIVE_ROOT", str(missing))

    from backend import config as _cfg
    monkeypatch.setattr(_cfg.settings, "ss_live_archive_root", str(missing), raising=False)

    from backend.services.downloads_archiver import scan_once
    result = scan_once()
    assert result.get("missing_root") is True
    assert result["moved"] == 0


def test_non_video_extension_ignored(isolated_videos_and_archive):
    videos, archive = isolated_videos_and_archive
    f = videos / "not_video.txt"
    _make_old_file(f, age_seconds=25 * 3600)

    from backend.services.downloads_archiver import scan_once
    result = scan_once()
    assert result["scanned"] == 0
    assert f.exists()
