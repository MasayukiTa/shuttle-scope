"""pg_dump の探し方: PATH → 環境変数 SS_PG_DUMP_PATH → 標準のインストール先。

実際の pg_dump は呼ばない。ダミーの実行ファイル名のファイルを tmp_path に置いて探索だけを見る。
"""
from __future__ import annotations

import pytest

import backend.services.backup_service as bs


@pytest.fixture()
def no_path(monkeypatch):
    monkeypatch.setattr(bs.shutil, "which", lambda name: None)
    monkeypatch.delenv(bs.PG_DUMP_ENV_VAR, raising=False)
    monkeypatch.setattr(bs, "_pg_dump_candidate_dirs", lambda: [])


def _touch_exe(directory):
    directory.mkdir(parents=True, exist_ok=True)
    exe = directory / bs._pg_dump_file_name()
    exe.write_bytes(b"")
    return exe


def test_path_wins_over_everything(monkeypatch, tmp_path):
    monkeypatch.setattr(bs.shutil, "which", lambda name: "/from/path/pg_dump")
    monkeypatch.setenv(bs.PG_DUMP_ENV_VAR, str(_touch_exe(tmp_path / "env")))
    assert bs.find_pg_dump() == "/from/path/pg_dump"


def test_env_var_may_point_to_the_file_or_its_folder(no_path, monkeypatch, tmp_path):
    exe = _touch_exe(tmp_path / "custom")
    monkeypatch.setenv(bs.PG_DUMP_ENV_VAR, str(exe))
    assert bs.find_pg_dump() == str(exe)
    monkeypatch.setenv(bs.PG_DUMP_ENV_VAR, str(exe.parent))
    assert bs.find_pg_dump() == str(exe)


def test_env_var_pointing_nowhere_falls_through(no_path, monkeypatch, tmp_path):
    monkeypatch.setenv(bs.PG_DUMP_ENV_VAR, str(tmp_path / "missing"))
    assert bs.find_pg_dump() is None


def test_standard_install_dirs_are_searched_in_order(no_path, monkeypatch, tmp_path):
    first = _touch_exe(tmp_path / "16" / "bin")
    _touch_exe(tmp_path / "14" / "bin")
    monkeypatch.setattr(bs, "_pg_dump_candidate_dirs", lambda: [tmp_path / "16" / "bin", tmp_path / "14" / "bin"])
    assert bs.find_pg_dump() == str(first)


def test_candidate_dirs_list_newest_version_first(monkeypatch, tmp_path):
    root = tmp_path / "PostgreSQL"
    for ver in ("9.6", "14", "16"):
        (root / ver).mkdir(parents=True)
    monkeypatch.setattr(bs, "_pg_install_roots", lambda: [root, tmp_path / "absent"])
    dirs = bs._pg_dump_candidate_dirs()
    assert [d.parent.name for d in dirs] == ["16", "14", "9.6"]
    assert all(d.name == "bin" for d in dirs)


def test_nothing_found_returns_none(no_path):
    assert bs.find_pg_dump() is None
