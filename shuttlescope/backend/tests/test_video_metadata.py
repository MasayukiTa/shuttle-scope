# -*- coding: utf-8 -*-
"""fetch_video_metadata（配信 URL のタイトル自動取得）の単体テスト。

- 多言語タイトル（日本語等）が Unicode のまま素通りすること（エンコード正当性）
- プレイリスト URL は先頭エントリを採用すること
- uploader 欠落時は channel にフォールバックすること
- yt-dlp が例外を投げても dict（ok=False）を返し、throw しないこと

SSRF 対策（loopback / 内部 IP / 非 http(s)）は呼び出し側ルータの
validate_external_url で行い、その単体テストは別ファイルにあるためここでは扱わない。
"""
from __future__ import annotations

import pytest

import backend.utils.video_downloader as vd

pytestmark = pytest.mark.skipif(
    not vd.YT_DLP_AVAILABLE, reason="yt-dlp 未インストール環境ではスキップ"
)


class _FakeYDL:
    def __init__(self, info, raise_exc=None):
        self._info = info
        self._raise = raise_exc

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=False):
        if self._raise is not None:
            raise self._raise
        return self._info


def _patch_ydl(monkeypatch, info=None, raise_exc=None):
    monkeypatch.setattr(vd.yt_dlp, "YoutubeDL", lambda opts: _FakeYDL(info, raise_exc))


def test_metadata_basic_multilingual(monkeypatch):
    info = {
        "title": "25'S/J合銀戦 vs 伊瀬・伊藤",
        "duration": 3104,
        "uploader": "むぅかな",
        "thumbnail": "https://example.com/t.jpg",
        "upload_date": "20251218",
        "width": 1920,
        "height": 1080,
    }
    _patch_ydl(monkeypatch, info=info)
    out = vd.fetch_video_metadata("https://youtu.be/abc")
    assert out["ok"] is True
    # 多言語タイトル・投稿者名がそのまま Unicode で返る（文字化けしない）
    assert out["title"] == "25'S/J合銀戦 vs 伊瀬・伊藤"
    assert out["uploader"] == "むぅかな"
    assert out["duration"] == 3104
    assert out["height"] == 1080
    assert out["upload_date"] == "20251218"


def test_metadata_playlist_takes_first(monkeypatch):
    info = {
        "_type": "playlist",
        "entries": [
            {"title": "first", "duration": 10},
            {"title": "second", "duration": 20},
        ],
    }
    _patch_ydl(monkeypatch, info=info)
    out = vd.fetch_video_metadata("https://youtu.be/list")
    assert out["ok"] is True
    assert out["title"] == "first"


def test_metadata_empty_playlist_is_error(monkeypatch):
    _patch_ydl(monkeypatch, info={"_type": "playlist", "entries": []})
    out = vd.fetch_video_metadata("https://youtu.be/emptylist")
    assert out["ok"] is False


def test_metadata_uploader_falls_back_to_channel(monkeypatch):
    _patch_ydl(monkeypatch, info={"title": "t", "channel": "chan"})
    out = vd.fetch_video_metadata("https://example.com/x")
    assert out["ok"] is True
    assert out["uploader"] == "chan"


def test_metadata_error_returns_dict_not_raise(monkeypatch):
    _patch_ydl(monkeypatch, raise_exc=RuntimeError("boom-extract"))
    out = vd.fetch_video_metadata("https://example.com/x")
    assert out["ok"] is False
    assert "boom-extract" in out["error"]
