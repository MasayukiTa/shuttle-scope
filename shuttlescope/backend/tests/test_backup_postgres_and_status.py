"""PostgreSQL のバックアップ (pg_dump) と、バックアップ画面の状態、hold 判定の反映。

- create_backup は PostgreSQL では pg_dump の出力を ZIP に入れる。
- パスワードはコマンドラインにもログにも出ない (環境変数 PGPASSWORD でだけ子プロセスへ渡す)。
- pg_dump が無いときは BackupUnavailable (NotImplementedError の一種)。取り込み前バックアップは
  この型を「作れない環境」として扱い、取り込みを続ける。
- backup_status は最終成功時刻を、実在するバックアップ ZIP からだけ出す。
- /analysis/meta/evidence は昇格 override の status を各分析に添える。
"""
from __future__ import annotations

import zipfile

import pytest

import backend.services.backup_service as bs

PW = "s3cret-pw-VALUE"
PG_URL = f"postgresql://appuser:{PW}@db.example:5432/shuttle"


class _Recorder:
    def __init__(self):
        self.lines: list[str] = []

    def _add(self, msg, *args):
        self.lines.append(str(msg) % args if args else str(msg))

    info = warning = error = exception = _add


@pytest.fixture()
def pg_env(tmp_path, monkeypatch):
    monkeypatch.setattr(bs.settings, "DATABASE_URL", PG_URL, raising=False)
    monkeypatch.setattr(bs, "get_backup_dir", lambda: tmp_path, raising=False)
    monkeypatch.setattr(bs, "_passphrase", lambda: None, raising=False)
    # 平文 ZIP の禁止は test_production_posture_is_single_source.py が見ている。ここは pg_dump の経路だけを見る
    monkeypatch.setattr(bs, "_enforce_passphrase_policy", lambda p: None, raising=False)
    rec = _Recorder()
    monkeypatch.setattr(bs, "logger", rec, raising=False)
    return tmp_path, rec


class _Done:
    def __init__(self, returncode=0, stderr=""):
        self.returncode = returncode
        self.stderr = stderr


def test_postgres_backup_zips_the_pg_dump_output_without_leaking_the_password(pg_env, monkeypatch):
    tmp_path, rec = pg_env
    seen = {}

    def fake_run(cmd, env=None, **kw):
        seen["cmd"], seen["env"] = list(cmd), dict(env or {})
        out = cmd[cmd.index("--file") + 1]
        with open(out, "wb") as f:
            f.write(b"PGDMP-fake")
        return _Done(0)

    monkeypatch.setattr(bs.shutil, "which", lambda name: "/usr/bin/pg_dump")
    monkeypatch.setattr(bs.subprocess, "run", fake_run)

    path = bs.create_backup(label="manual")

    assert path.exists() and path.parent == tmp_path
    with zipfile.ZipFile(path) as zf:
        assert zf.namelist() == ["database.pgdump"]
        assert zf.read("database.pgdump") == b"PGDMP-fake"
    assert not list(tmp_path.glob(".pgdump_*"))                      # 一時ファイルは残さない
    assert PW not in " ".join(seen["cmd"])                             # コマンドラインに出ない
    assert seen["env"]["PGPASSWORD"] == PW                             # 子プロセスの環境でだけ渡す
    assert all(PW not in line for line in rec.lines)                   # ログにも出ない


def test_failed_pg_dump_hides_the_password_and_leaves_no_files(pg_env, monkeypatch):
    tmp_path, rec = pg_env
    monkeypatch.setattr(bs.shutil, "which", lambda name: "/usr/bin/pg_dump")
    monkeypatch.setattr(bs.subprocess, "run", lambda cmd, env=None, **kw: _Done(1, f"connection failed for password {PW}"))

    with pytest.raises(RuntimeError) as exc:
        bs.create_backup()

    assert PW not in str(exc.value)
    assert all(PW not in line for line in rec.lines)
    assert any("pg_dump failed" in line for line in rec.lines)
    assert list(tmp_path.iterdir()) == []


def test_missing_pg_dump_is_reported_as_unavailable(pg_env, monkeypatch):
    monkeypatch.setattr(bs.shutil, "which", lambda name: None)

    with pytest.raises(bs.BackupUnavailable) as exc:
        bs.create_backup()

    assert isinstance(exc.value, NotImplementedError)                  # 取り込み前バックアップは「作れない環境」として続行する
    assert "pg_dump" in str(exc.value)


def test_backup_status_reports_the_last_success_only_from_real_backups(tmp_path, monkeypatch):
    db = tmp_path / "shuttlescope.db"
    db.write_bytes(b"x")
    monkeypatch.setattr(bs.settings, "DATABASE_URL", f"sqlite:///{db}", raising=False)
    monkeypatch.setattr(bs, "get_backup_dir", lambda: tmp_path, raising=False)

    empty = bs.backup_status()
    assert empty["engine"] == "sqlite" and empty["supported"] is True
    assert empty["count"] == 0 and empty["last_success_at"] is None

    with zipfile.ZipFile(tmp_path / "backup_20260101_000000_abc.zip", "w") as zf:
        zf.writestr("shuttlescope.db", b"x")
    got = bs.backup_status()
    assert got["count"] == 1
    assert got["last_success_at"].endswith("Z")
    assert got["max_generations"] == bs.DEFAULT_MAX_GENERATIONS


def test_backup_status_for_postgres_depends_on_pg_dump(tmp_path, monkeypatch):
    monkeypatch.setattr(bs.settings, "DATABASE_URL", PG_URL, raising=False)
    monkeypatch.setattr(bs, "get_backup_dir", lambda: tmp_path, raising=False)

    monkeypatch.setattr(bs.shutil, "which", lambda name: None)
    missing = bs.backup_status()
    assert missing["engine"] == "postgresql" and missing["supported"] is False
    assert missing["reason"] == "pg_dump_missing"

    monkeypatch.setattr(bs.shutil, "which", lambda name: "/usr/bin/pg_dump")
    assert bs.backup_status()["supported"] is True


def test_evidence_meta_carries_the_override_status(tmp_path, monkeypatch):
    from backend.analysis import promotion_override_store as store
    from backend.routers.analysis_spine import get_evidence_meta

    monkeypatch.setattr(store, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "_OVERRIDE_FILE", tmp_path / "promotion_overrides.json")
    monkeypatch.setattr(store, "_AUDIT_LOG_FILE", tmp_path / "promotion_audit_log.json")
    store.save_override("pressure", "hold", note="要確認", analyst="admin")

    data = {e["analysis_type"]: e for e in get_evidence_meta()["data"]}

    assert data["pressure"]["override_status"] == "hold"
    assert data["transition"]["override_status"] is None
    assert "note" not in data["pressure"] and "analyst" not in data["pressure"]   # 判断の中身は出さない
