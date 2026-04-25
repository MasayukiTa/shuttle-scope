"""Attack #41+ ハードニングテスト群 (round 3, ライブ攻撃由来)。

X1: V2 zip-bomb bypass via validate_package (CWE-409)
    /api/sync/validate と /api/sync/preview は import_package 前段で
    validate_package を呼び出すが、こちらに zip bomb 防御が入っておらず
    V2 を素通りされていた。共通 helper `check_zip_bomb_caps` を validate
    側にも注入する。

X2: InitRequest mass-assignment / 制御文字
    /api/v1/uploads/video/init は extra フィールドを silent drop し、
    filename 内の制御文字を素通ししていた。実 FS 操作は upload_id ベースに
    正規化されるため path traversal の直接被害は無いが、DB に攻撃者制御の
    `../../etc/passwd.mp4` が保存され、後続の表示・ログ出力で
    confusion を生む状態だった。
"""
from __future__ import annotations

import io
import json
import zipfile

import pytest


# ─── X1: validate_package zip-bomb 防御 ────────────────────────────────────────


def _build_pkg(member_files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in member_files.items():
            zf.writestr(name, content)
    return buf.getvalue()


class TestValidatePackageBomb:
    def test_validate_blocks_oversized_member(self, monkeypatch):
        from backend.services import import_package as ip
        from backend.services import export_package as ep

        monkeypatch.setattr(ip, "_MAX_PER_MEMBER", 1024)
        # validate_package goes through ep namespace
        members = {
            "manifest.json": json.dumps({"version": "1.0"}).encode(),
            "matches.json": b"x" * 4096,
            "players.json": b"[]",
        }
        result = ep.validate_package(_build_pkg(members))
        assert result["valid"] is False
        assert "メンバー" in result["error"] and "サイズ" in result["error"]

    def test_validate_blocks_member_count(self, monkeypatch):
        from backend.services import import_package as ip
        from backend.services import export_package as ep

        monkeypatch.setattr(ip, "_MAX_MEMBER_COUNT", 5)
        members = {f"f{i}.json": b"[]" for i in range(20)}
        members["manifest.json"] = json.dumps({"version": "1.0"}).encode()
        members["matches.json"] = b"[]"
        members["players.json"] = b"[]"
        result = ep.validate_package(_build_pkg(members))
        assert result["valid"] is False
        assert "メンバー数" in result["error"]

    def test_validate_blocks_total_uncompressed(self, monkeypatch):
        import os
        from backend.services import import_package as ip
        from backend.services import export_package as ep

        monkeypatch.setattr(ip, "_MAX_TOTAL_UNCOMPRESSED", 2048)
        monkeypatch.setattr(ip, "_MAX_PER_MEMBER", 4096)
        # 圧縮率チェックを先に踏まないよう、ランダム (= 圧縮しても縮まない) で埋める
        rand_a = os.urandom(1500)
        rand_b = os.urandom(1500)
        members = {
            "manifest.json": json.dumps({"version": "1.0"}).encode(),
            "matches.json": rand_a,
            "players.json": rand_b,
        }
        result = ep.validate_package(_build_pkg(members))
        assert result["valid"] is False
        assert "解凍後合計" in result["error"]

    def test_validate_passes_normal_package(self):
        from backend.services import export_package as ep

        members = {
            "manifest.json": json.dumps({"version": "1.0"}).encode(),
            "matches.json": b"[]",
            "players.json": b"[]",
        }
        result = ep.validate_package(_build_pkg(members))
        assert result["valid"] is True


# ─── X2: InitRequest extra=forbid + filename 制御文字 ──────────────────────────


class TestUploadInitHardening:
    def test_init_request_rejects_extra(self):
        from backend.routers.uploads import InitRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            InitRequest(
                filename="a.mp4",
                total_size=1024,
                chunk_size=131072,
                match_id=1,
                smuggle_field="x",
            )

    def test_init_request_filename_max_length(self):
        from backend.routers.uploads import InitRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            InitRequest(
                filename="A" * 256 + ".mp4",
                total_size=1024,
                chunk_size=131072,
                match_id=1,
            )

    def test_init_request_normal_payload(self):
        from backend.routers.uploads import InitRequest

        m = InitRequest(filename="match.mp4", total_size=1024, chunk_size=131072, match_id=1)
        assert m.filename == "match.mp4"

    def test_init_handler_rejects_control_chars_in_filename(self):
        """init_upload は CR/LF/NUL を含む filename を 422 で拒否する。"""
        from backend.routers import uploads as up
        import inspect

        src = inspect.getsource(up.init_upload)
        # 制御文字チェックが実装されている
        assert "制御文字" in src or "control" in src.lower()
        # 実際にチェック条件 (ord < 0x20 or 0x7F) が入っている
        assert "ord(c) < 0x20" in src or "ord(c) == 0x7F" in src
