"""ZIP メンバーの展開を、申告値ではなく実測バイト数で打ち切る。

調査md の X-9 は「`check_zip_bomb_caps` は攻撃者が書いた中央ディレクトリの
申告値から上限を計算し、`zf.read()` は無制限にメモリへ展開する」としていた。
**前半は正しいが、後半は成立しない。** 実測した挙動 (CPython 3.14):

    file_size を 1 と偽る     → `zf.read()` は BadZipFile (Bad CRC-32)
    compress_size を 1 と偽る → 同上

`ZipExtFile` は申告された `file_size` までしか復元せず、CRC が合わずに落ちる。
**少なく申告してもメモリには入らない**ので、記載された bomb 経路は無い。
多く申告すれば `check_zip_bomb_caps` が展開前に弾く。

それでも上限を実測で持つのは、いまの保護が「stdlib が `file_size` を守る」
という実装依存の性質に丸ごと乗っているため。ここは多層防御であって、
塞いだ穴ではない。
"""
from __future__ import annotations

import io
import zipfile

import pytest

from backend.services.import_package import (
    ZipBombError,
    check_zip_bomb_caps,
    read_member_capped,
)


def _zip(name: str, data: bytes) -> zipfile.ZipFile:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(name, data)
    buf.seek(0)
    return zipfile.ZipFile(buf, "r")


class TestUnderstatingTheSizeGainsNothing:
    """記載された経路が成立しないことを、推測ではなく実行で固定する。"""

    def _lying(self) -> zipfile.ZipFile:
        zf = _zip("big.json", b"A" * (2 * 1024 * 1024))
        info = zf.getinfo("big.json")
        info.file_size = 1
        info.compress_size = 1
        return zf

    def test_the_pre_check_is_fooled(self):
        """事前検査は申告値しか見ないので、嘘は素通りする。"""
        assert check_zip_bomb_caps(self._lying()) is None

    def test_but_the_stdlib_refuses_to_expand_it(self):
        """申告 1 byte を超えて復元されないので CRC が合わない。"""
        with pytest.raises(zipfile.BadZipFile):
            self._lying().read("big.json")

    def test_our_reader_also_refuses(self):
        """経路がどちらでも、2MB がメモリに載らないこと。"""
        with pytest.raises((ZipBombError, zipfile.BadZipFile)):
            read_member_capped(self._lying(), "big.json", cap=1024)


class TestTheCapIsEnforcedOnRealBytes:
    def test_a_member_within_the_cap_is_returned_intact(self):
        payload = b'{"hello": "world"}'
        assert read_member_capped(_zip("small.json", payload), "small.json", cap=1024) == payload

    def test_exactly_at_the_cap_is_allowed(self):
        payload = b"A" * 1024
        assert read_member_capped(_zip("edge.json", payload), "edge.json", cap=1024) == payload

    def test_one_byte_over_the_cap_is_refused(self):
        with pytest.raises(ZipBombError):
            read_member_capped(_zip("edge.json", b"A" * 1025), "edge.json", cap=1024)


class TestThePreCheckStillCatchesHonestPackages:
    def test_an_honest_oversized_member_is_reported(self):
        zf = _zip("big.json", b"A" * 16)
        zf.getinfo("big.json").file_size = 512 * 1024 * 1024  # 256MB/file の上限超え
        assert "big.json" in (check_zip_bomb_caps(zf) or "")
